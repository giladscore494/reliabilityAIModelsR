# -*- coding: utf-8 -*-
# ===========================================================
# 🚗 Car Reliability Analyzer – Israel (v5.0.0 • PostgreSQL DB)
# ===========================================================

import json, re, time, datetime, difflib, traceback, os
from typing import Optional, Tuple, Any, Dict, List

import pandas as pd
from flask import Flask, render_template, request, jsonify
from json_repair import repair_json
import google.generativeai as genai

# --- 1A. יבוא ספריות חדשות לבסיס הנתונים ---
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from datetime import datetime, time, timedelta

# =========================
# ========= CONFIG ========
# =========================
PRIMARY_MODEL = "gemini-2.5-flash"
FALLBACK_MODEL = "gemini-1.5-flash-latest"
RETRIES = 2
RETRY_BACKOFF_SEC = 1.5
GLOBAL_DAILY_LIMIT = 1000
MAX_CACHE_DAYS = 45 # נתונים במטמון יישמרו ל-45 ימים

app = Flask(__name__)

# ==================================
# === 1B. הגדרת בסיס הנתונים (DB) ===
# ==================================

# Railway מספק אוטומטית את ה-DATABASE_URL כמשתנה סביבה
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
# אנחנו קוראים את המפתח הסודי שהוספנו ב-Railway
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') 
    
db = SQLAlchemy(app)

# --- הגדרת מודלים (Blueprints לטבלאות) ---
# זוהי טבלת הלוג הפשוטה שלנו ששומרת כל חיפוש
class SearchLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.now)
    make = db.Column(db.String(100))
    model = db.Column(db.String(100))
    year = db.Column(db.Integer)
    # שומרים את הקלט המלא של המשתמש לצורך חיפוש במטמון
    mileage_range = db.Column(db.String(100))
    fuel_type = db.Column(db.String(100))
    transmission = db.Column(db.String(100))
    # כאן נשמור את כל התוצאה מ-Gemini כטקסט JSON
    result_json = db.Column(db.Text, nullable=False)


# --- יצירת הטבלאות בבסיס הנתונים ---
# הפקודה הזו תיצור את הטבלאות אם הן עדיין לא קיימות
with app.app_context():
    db.create_all()

# =========================
# ======== Secrets ========
# =========================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# -------------------------------------------------------------
# --- (מחקנו את הסודות של Google Sheets כי אין בהם צורך) ---
# -------------------------------------------------------------

if not GEMINI_API_KEY:
    print("WARNING: חסר GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# =========================
# === Models dictionary ===
# =========================
try:
    from car_models_dict import israeli_car_market_full_compilation
except Exception:
    israeli_car_market_full_compilation = {
        "Volkswagen": ["Golf (2004-2025)", "Polo (2005-2025)", "Passat (2005-2025)", "Scirocco (2008-2017)"],
        "Toyota": ["Corolla (2008-2025)", "Yaris (2008-2025)", "CHR (2016-2025)"],
        "Mazda": ["Mazda3 (2003-2025)", "Mazda6 (2003-2021)", "CX-5 (2012-2025)"],
    }

# =========================
# ===== Helper funcs ======
# =========================
def normalize_text(s: Any) -> str:
    if s is None:
        return ""
    s = re.sub(r"\(.*?\)", " ", str(s))
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()

def parse_year_range_from_model_label(model_label: str) -> Tuple[Optional[int], Optional[int]]:
    m = re.search(r"\((\d{4})\s*-\s*(\d{4})\)", str(model_label))
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)

def safe_json_parse(value: Any, default=None):
    if value is None: return default
    if isinstance(value, (list, dict)): return value
    s = str(value)
    if not s.strip(): return default
    try: return json.loads(s)
    except Exception:
        try: return json.loads(repair_json(s))
        except Exception: return default

# =========================
# ==== Mileage logic  =====
# =========================
def mileage_adjustment(mileage_range: str) -> Tuple[int, Optional[str]]:
    m = normalize_text(mileage_range or "")
    if not m: return 0, None
    if "200" in m and "+" in m: return -15, "הציון הותאם מטה עקב קילומטראז׳ גבוה מאוד (200K+)."
    if "150" in m and "200" in m: return -10, "הציון הותאם מטה עקב קילומטראז׳ גבוה (150–200 אלף ק״מ)."
    if "100" in m and "150" in m: return -5, "הציון הותאם מעט מטה עקב קילומטראז׳ בינוני-גבוה (100–150 אלף ק״מ)."
    return 0, None

# (הפונקציה mileage_is_close לא בשימוש כרגע בחיפוש הפשוט, אבל נשמור אותה)
def mileage_is_close(requested: str, stored: str, thr: float = 0.92) -> bool:
    if requested is None or stored is None: return False
    return similarity(str(requested), str(stored)) >= thr

# -------------------------------------------------------------
# --- (מחקנו את כל הפונקציות של Google Sheets) ---
# -------------------------------------------------------------

# =========================
# ===== Model calling =====
# =========================
def build_prompt(make, model, sub_model, year, fuel_type, transmission, mileage_range):
    extra = f" תת-דגם/תצורה: {sub_model}" if sub_model else ""
    return f"""
אתה מומחה לאמינות רכבים בישראל עם גישה לחיפוש אינטרנטי.
הניתוח חייב להתייחס ספציפית לטווח הקילומטראז' הנתון.
החזר JSON בלבד:

{{
  "search_performed": true,
  "score_breakdown": {{
    "engine_transmission_score": "מספר (1-10)",
    "electrical_score": "מספר (1-10)",
    "suspension_brakes_score": "מספר (1-10)",
    "maintenance_cost_score": "מספר (1-10)",
    "satisfaction_score": "מספר (1-10)",
    "recalls_score": "מספר (1-10)"
  }},
  "base_score_calculated": "מספר (0-100)",
  "common_issues": ["תקלות נפוצות רלוונטיות לק\"מ"],
  "avg_repair_cost_ILS": "מספר ממוצע",
  "issues_with_costs": [
    {{"issue": "שם התקלה", "avg_cost_ILS": "מספר", "source": "מקור", "severity": "נמוך/בינוני/גבוה"}}
  ],
  "reliability_summary": "סיכום בעברית",
  "sources": ["רשימת אתרים"],
  "recommended_checks": ["בדיקות מומלצות ספציפיות"],
  "common_competitors_brief": [
      {{"model": "שם מתחרה 1", "brief_summary": "אמינות בקצרה"}},
      {{"model": "שם מתחרה 2", "brief_summary": "אמינות בקצרה"}}
  ]
}}

רכב: {make} {model}{extra} {int(year)}
טווח קילומטראז': {mileage_range}
סוג דלק: {fuel_type}
תיבת הילוכים: {transmission}
כתוב בעברית בלבד.
""".strip()

def call_model_with_retry(prompt: str) -> dict:
    last_err = None
    for model_name in [PRIMARY_MODEL, FALLBACK_MODEL]:
        try: llm = genai.GenerativeModel(model_name)
        except Exception as e: last_err = e; continue
        for attempt in range(1, RETRIES + 1):
            try:
                print(f"Calling model {model_name}...")
                resp = llm.generate_content(prompt)
                raw = (getattr(resp, "text", "") or "").strip()
                try: m = re.search(r"\{.*\}", raw, re.DOTALL); data = json.loads(m.group()) if m else json.loads(raw)
                except Exception: data = json.loads(repair_json(raw))
                print("Model call successful.")
                return data
            except Exception as e:
                print(f"Attempt {attempt} failed: {e}")
                last_err = e
                if attempt < RETRIES: time.sleep(RETRY_BACKOFF_SEC)
                continue
    raise RuntimeError(f"Model failed: {repr(last_err)}")

# =========================
# === Mileage Apply/Notes =
# =========================
def apply_mileage_logic(result_obj: dict, requested_mileage: str) -> Tuple[dict, Optional[str]]:
    delta, note = mileage_adjustment(requested_mileage)
    if delta != 0:
        try: base = int(result_obj.get("base_score_calculated") or 0)
        except Exception: base = 0
        new_base = max(0, min(100, base + delta))
        result_obj["base_score_calculated"] = new_base
    return result_obj, note

# =========================
# ===== Flask Routes ======
# =========================

@app.route('/')
def index():
    """ מגיש את דף ה-HTML הראשי (הפרונטאנד) """
    try:
        # אנו שולחים לפרונטאנד את רשימת הרכבים כדי לבנות את התפריטים
        return render_template('index.html', car_models_data=israeli_car_market_full_compilation)
    except Exception as e:
        print(f"!!! קריסה קריטית: לא ניתן לטעון את index.html: {e}")
        traceback.print_exc()
        return "<h1>שגיאה בטעינת האפליקציה (500)</h1><p>בדוק את הלוגים של השרת.</p>", 500

@app.route('/analyze', methods=['POST'])
def analyze_car():
    """
    זהו ה-API Endpoint המשודרג שמשתמש ב-PostgreSQL במקום ב-Sheets.
    """
    global_searches_today = 0 # נגדיר משתנה שנוכל להשתמש בו בסוף
    try:
        # --- שלב 0: קבלת נתונים ---
        data = request.json
        print(f"DEBUG (0/6): Received data: {data}")
        final_make = normalize_text(data.get('make'))
        final_model = normalize_text(data.get('model'))
        final_sub_model = normalize_text(data.get('sub_model')) # נשמור אותו לפרומפט
        final_year = int(data.get('year')) if data.get('year') else None
        final_mileage = str(data.get('mileage_range'))
        final_fuel = str(data.get('fuel_type'))
        final_trans = str(data.get('transmission'))

        if not (final_make and final_model and final_year):
            return jsonify({"error": "שגיאת קלט (שלב 0): נא למלא יצרן, דגם ושנה."}), 400

    except Exception as e:
        print(f"!!! שגיאה (שלב 0): הקלט שהתקבל אינו JSON תקין. {e}")
        return jsonify({"error": f"שגיאת קלט (שלב 0): {str(e)}"}), 400

    # --- שלב 1: (חדש) בדיקת מגבלה גלובלית ---
    try:
        print("DEBUG (1/6): Checking global quota...")
        today_start = datetime.combine(datetime.today().date(), time.min)
        today_end = datetime.combine(datetime.today().date(), time.max)
        
        global_searches_today = SearchLog.query.filter(
            SearchLog.timestamp >= today_start,
            SearchLog.timestamp <= today_end
        ).count()

        if global_searches_today >= GLOBAL_DAILY_LIMIT:
            print(f"!!! שגיאה (שלב 1): המגבלה הגלובלית הושגה.")
            return jsonify({"error": f"שגיאת שרת (שלב 1): המגבלה הגלובלית הושגה ({global_searches_today}/{GLOBAL_DAILY_LIMIT}). נסה שוב מחר."}), 503
        
        print(f"DEBUG (1/6): Global quota OK ({global_searches_today}/{GLOBAL_DAILY_LIMIT}).")
        
    except Exception as e:
        print(f"!!! שגיאה (שלב 1): נכשל בבדיקת המגבלה הגלובלית.")
        traceback.print_exc()
        # אנחנו לא עוצרים את המשתמש, אבל רושמים את השגיאה
        pass # נמשיך בכל מקרה

    # --- שלב 2: (חדש) חיפוש במטמון ב-DB ---
    try:
        print("DEBUG (2/6): Fetching cache from DB...")
        
        # חיפוש רשומה תואמת מ-45 הימים האחרונים
        cutoff_date = datetime.now() - timedelta(days=MAX_CACHE_DAYS)
        
        # נחפש התאמה מדויקת של הקלט
        cached_result_db = SearchLog.query.filter(
            SearchLog.make == final_make,
            SearchLog.model == final_model,
            SearchLog.year == final_year,
            SearchLog.mileage_range == final_mileage,
            SearchLog.fuel_type == final_fuel,
            SearchLog.transmission == final_trans,
            SearchLog.timestamp >= cutoff_date
        ).order_by(SearchLog.timestamp.desc()).first() # קח את החדש ביותר

        if cached_result_db:
            print("DEBUG (3/6): Cache hit. Skipping model call.")
            # טעינת ה-JSON השמור
            cached_result = json.loads(cached_result_db.result_json)
            
            cached_result['source_tag'] = f"מקור: מטמון DB (נשמר ב-{cached_result_db.timestamp.strftime('%Y-%m-%d')})"
            cached_result['mileage_note'] = None
            cached_result['km_warn'] = False
            return jsonify(cached_result)

        print("DEBUG (3/6): Cache miss. Proceeding to API call.")

    except Exception as e:
        print(f"!!! שגיאה (שלב 2): נכשל בחיפוש במטמון ב-DB.")
        traceback.print_exc()
        # לא עוצרים, פשוט נמשיך לקריאה ל-Gemini
        pass

    # --- שלב 4: פנייה ל-Gemini ---
    try:
        print("DEBUG (4/6): Calling Gemini API...")
        prompt = build_prompt(
            final_make, final_model, final_sub_model, final_year,
            final_fuel, final_trans, final_mileage
        )
        model_output = call_model_with_retry(prompt)
        print("DEBUG (4/6): Gemini call successful.")
    except Exception as e:
        print(f"!!! שגיאה (שלב 4): הקריאה ל-Gemini נכשלה.")
        traceback.print_exc()
        return jsonify({"error": f"שגיאת AI (שלב 4): הקריאה למודל ה-AI נכשלה. ודא שה-GEMINI_API_KEY נכון. שגיאה: {str(e)}"}), 500

    # --- שלב 5: החלת לוגיקת ק"מ ---
    print("DEBUG (5/6): Applying mileage logic...")
    model_output, note = apply_mileage_logic(model_output, final_mileage)

    # --- שלב 6: (חדש) שמירה ב-DB ---
    try:
        print("DEBUG (6/6): Saving new result to DB...")
        
        new_log = SearchLog(
            make = final_make,
            model = final_model,
            year = final_year,
            mileage_range = final_mileage,
            fuel_type = final_fuel,
            transmission = final_trans,
            result_json = json.dumps(model_output, ensure_ascii=False) # שומר את כל התשובה
        )
        db.session.add(new_log)
        db.session.commit()
        print("DEBUG (6/6): Save complete.")
    except Exception as e:
        print(f"!!! אזהרה (שלב 6): השמירה ל-DB נכשלה (המשתמש קיבל תשובה). שגיאה: {e}")
        traceback.print_exc()
        db.session.rollback() # חשוב לבטל את הטרנזקציה אם נכשלה

    # --- סיום: החזרת תשובה ---
    model_output['source_tag'] = f"מקור: ניתוח AI חדש (שימוש גלובלי {global_searches_today + 1}/{GLOBAL_DAILY_LIMIT})"
    model_output['mileage_note'] = note
    model_output['km_warn'] = False
    return jsonify(model_output)


if __name__ == '__main__':
    # פקודה זו מיועדת לפיתוח מקומי בלבד. Railway ישתמש ב-Gunicorn.
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=True, port=port)
