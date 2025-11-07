# -*- coding: utf-8 -*-
# ===========================================================
# 🚗 Car Reliability Analyzer – Israel (v4.2.0 • Flask API + DB Ready)
# ===========================================================

import json, re, time, datetime, difflib, traceback, os
from typing import Optional, Tuple, Any, Dict, List

import pandas as pd
from flask import Flask, render_template, request, jsonify
from json_repair import repair_json
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials

# --- 1A. יבוא ספריות חדשות לבסיס הנתונים ---
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
# ---------------------------------------------


# =========================
# ========= CONFIG ========
# =========================
PRIMARY_MODEL = "gemini-2.5-flash"
FALLBACK_MODEL = "gemini-1.5-flash-latest"
RETRIES = 2
RETRY_BACKOFF_SEC = 1.5
GLOBAL_DAILY_LIMIT = 1000
MAX_CACHE_DAYS = 45

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

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(200), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100))
    # זה יוצר קישור לטבלת החיפושים
    searches = db.relationship('SearchHistory', backref='user', lazy=True)

class SearchHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.now)
    make = db.Column(db.String(100))
    model = db.Column(db.String(100))
    year = db.Column(db.Integer)
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
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")

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
# ===== Sheets Layer ======
# =========================
# (כל הלוגיקה של Sheets נשארת כאן *בינתיים*. נמחק אותה בשלב הבא)
REQUIRED_HEADERS = [
    "date","user_id","make","model","sub_model","year","fuel","transmission",
    "mileage_range","base_score_calculated","score_breakdown","avg_cost",
    "issues","search_performed","reliability_summary","issues_with_costs",
    "sources","recommended_checks","common_competitors_brief"
]

def connect_sheet():
    if not (GOOGLE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON):
        raise ValueError("❌ אין חיבור למאגר (Secrets חסרים).")
    try:
        svc = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        if "\\n" in svc.get("private_key", ""):
            svc["private_key"] = svc["private_key"].replace("\\n", "\n")

        credentials = Credentials.from_service_account_info(
            svc, scopes=["https://www.googleapis.com/auth/spreadsheets",
                         "https://www.googleapis.com/auth/drive"]
        )
        gc = gspread.authorize(credentials)
        sh = gc.open_by_key(GOOGLE_SHEET_ID)
        ws = sh.sheet1
        
        current = [c.lower() for c in ws.row_values(1)]
        if current != REQUIRED_HEADERS:
            ws.update("A1", [REQUIRED_HEADERS], value_input_option="USER_ENTERED")
        return ws
    except Exception as e:
        raise ConnectionError(f"❌ אין חיבור למאגר (שיתוף/הרשאות/Sheet): {e}")

def sheet_to_df(ws) -> pd.DataFrame:
    try:
        recs = ws.get_all_records()
        df = pd.DataFrame(recs) if recs else pd.DataFrame(columns=REQUIRED_HEADERS)
    except Exception as e:
        print(f"Error reading sheet: {e}")
        return pd.DataFrame(columns=REQUIRED_HEADERS)
    for h in REQUIRED_HEADERS:
        if h not in df.columns: df[h] = ""
    return df

def append_row_to_sheet(ws, row_dict: dict):
    row = [row_dict.get(k, "") for k in REQUIRED_HEADERS]
    try:
        ws.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"Error appending row: {e}")

# =========================
# ===== Limits/Quota ======
# =========================
def within_daily_global_limit(df: pd.DataFrame, limit=GLOBAL_DAILY_LIMIT) -> Tuple[bool, int]:
    today = datetime.date.today().isoformat()
    if df.empty or "date" not in df.columns: return True, 0
    try: cnt = len(df[df["date"].astype(str) == today])
    except Exception: cnt = 0
    return (cnt < limit), cnt

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

def mileage_is_close(requested: str, stored: str, thr: float = 0.92) -> bool:
    if requested is None or stored is None: return False
    return similarity(str(requested), str(stored)) >= thr

# =========================
# ===== Cache lookup ======
# =========================
def match_hits_core(recent: pd.DataFrame, year: int, make: str, model: str, sub_model: Optional[str], th: float):
    mk, md, sm = normalize_text(make), normalize_text(model), normalize_text(sub_model or "")
    use_sub = len(sm) > 0
    cand = recent[
        (pd.to_numeric(recent["year"], errors="coerce").astype("Int64") == int(year)) &
        (recent["make"].apply(lambda x: similarity(x, mk) >= th)) &
        (recent["model"].apply(lambda x: similarity(x, md) >= th))
    ]
    if use_sub and "sub_model" in recent.columns:
        cand = cand[cand["sub_model"].apply(lambda x: similarity(x, sm) >= th)]
    if "date" in cand.columns:
        try:
            cand["date"] = pd.to_datetime(cand["date"], errors="coerce")
            cand = cand.sort_values("date")
        except Exception: pass
    return cand

def get_cached_from_sheet(ws, make: str, model: str, sub_model: str, year: int, mileage_range: str, max_days=MAX_CACHE_DAYS):
    df = sheet_to_df(ws)
    if df.empty:
        return None, df, False, False
    try:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    except Exception: pass
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=max_days)
    recent = df[df["date"] >= cutoff] if "date" in df.columns else df

    used_fallback = False
    mileage_matched = False
    hits = pd.DataFrame()
    for th in (0.97, 0.93):
        hits = match_hits_core(recent, year, make, model, sub_model, th)
        if not hits.empty: break
    if hits.empty and sub_model:
        used_fallback = True
        for th in (0.97, 0.93):
            hits = match_hits_core(recent, year, make, model, None, th)
            if not hits.empty: break
    if hits.empty:
        return None, df, used_fallback, mileage_matched

    req_mil = str(mileage_range or "")
    def row_mil_sim(row):
        stored = str(row.get("mileage_range", "") or "")
        return similarity(req_mil, stored)
    hits = hits.copy()
    hits["__mil_sim"] = hits.apply(row_mil_sim, axis=1)
    hits = hits.sort_values(["__mil_sim", "date"], ascending=[False, False])
    best = hits.iloc[0]
    mileage_matched = mileage_is_close(req_mil, best.get("mileage_range", ""))

    def row_to_parsed(r: dict):
        score_breakdown = safe_json_parse(r.get("score_breakdown"), {}) or {}
        issues_with_costs = safe_json_parse(r.get("issues_with_costs"), []) or []
        recommended_checks = safe_json_parse(r.get("recommended_checks"), []) or []
        competitors = safe_json_parse(r.get("common_competitors_brief"), []) or []
        sources = safe_json_parse(r.get("sources"), []) or r.get("sources","")
        base_calc = r.get("base_score_calculated")
        if base_calc in [None, "", "nan"]:
            legacy_base = r.get("base_score")
            try: base_calc = int(round(float(legacy_base)))
            except Exception: base_calc = None
        issues_raw = r.get("issues", [])
        if isinstance(issues_raw, str) and issues_raw:
            if ";" in issues_raw: issues_list = [x.strip() for x in issues_raw.split(";") if x.strip()]
            elif "," in issues_raw: issues_list = [x.strip() for x in issues_raw.split(",") if x.strip()]
            else: issues_list = [issues_raw.strip()]
        elif isinstance(issues_raw, list): issues_list = [str(x).strip() for x in issues_raw if str(x).strip()]
        else: issues_list = []
        last_dt = r.get("date")
        last_date_str = ""
        if isinstance(last_dt, pd.Timestamp): last_date_str = str(last_dt.date())
        elif last_dt: last_date_str = str(last_dt)[:10]

        return {
            "score_breakdown": score_breakdown,
            "base_score_calculated": base_calc,
            "common_issues": issues_list,
            "avg_repair_cost_ILS": r.get("avg_cost"),
            "issues_with_costs": issues_with_costs,
            "reliability_summary": r.get("reliability_summary") or "",
            "sources": sources,
            "recommended_checks": recommended_checks,
            "common_competitors_brief": competitors,
            "last_date": last_date_str,
            "cached_mileage_range": r.get("mileage_range", "")
        }
    parsed_row = row_to_parsed(best.to_dict())
    parsed_row["is_aggregate"] = False
    parsed_row["count"] = int(len(hits))
    return parsed_row, df, used_fallback, mileage_matched

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
    זהו ה-API Endpoint המשודרג עם דיבאג מתקדם.
    כרגע הוא עדיין משתמש ב-Sheets, אבל התשתית של ה-DB מוכנה.
    """
    try:
        # --- שלב 0: קבלת נתונים ---
        data = request.json
        print(f"DEBUG (0/6): Received data: {data}")
        final_make = normalize_text(data.get('make'))
        final_model = normalize_text(data.get('model'))
        final_sub_model = normalize_text(data.get('sub_model'))
        final_year = int(data.get('year')) if data.get('year') else None
        final_mileage = str(data.get('mileage_range'))
        final_fuel = str(data.get('fuel_type'))
        final_trans = str(data.get('transmission'))

        if not (final_make and final_model and final_year):
            return jsonify({"error": "שגיאת קלט (שלב 0): נא למלא יצרן, דגם ושנה."}), 400

    except Exception as e:
        print(f"!!! שגיאה (שלב 0): הקלט שהתקבל אינו JSON תקין. {e}")
        return jsonify({"error": f"שגיאת קלט (שלב 0): {str(e)}"}), 400

    # --- שלב 1: חיבור ל-Sheets ---
    try:
        print("DEBUG (1/6): Connecting to Google Sheets...")
        ws = connect_sheet()
        print("DEBUG (1/6): Connection successful.")
    except Exception as e:
        print(f"!!! שגיאה (שלב 1): נכשל בחיבור ל-Google Sheets.")
        traceback.print_exc()
        return jsonify({"error": f"שגיאת חיבור (שלב 1): נכשל ביצירת החיבור ל-Google Sheets. ודא שה-API של Sheets ו-Drive מופעלים וההרשאות תקינות. שגיאה: {str(e)}"}), 500

    # --- שלב 2: קריאת Cache ---
    try:
        print("DEBUG (2/6): Fetching cache from sheet...")
        cached_result, df, used_fallback, mileage_matched = get_cached_from_sheet(
            ws, final_make, final_model, final_sub_model, final_year, final_mileage
        )
        print("DEBUG (2/6): Cache fetch complete.")
    except Exception as e:
        print(f"!!! שגיאה (שלב 2): נכשל בקריאת הנתונים מה-Sheet.")
        traceback.print_exc()
        return jsonify({"error": f"שגיאת מטמון (שלב 2): נכשל בקריאת הנתונים מה-Sheet. ודא שהשיתוף (Share) של המייל בוצע כראוי. שגיאה: {str(e)}"}), 500

    # --- שלב 3: בדיקת Quota ו-Cache Hit ---
    is_quota_ok, daily_count = within_daily_global_limit(df)

    if cached_result:
        print("DEBUG (3/6): Cache hit. Skipping model call.")
        cached_result, note = apply_mileage_logic(cached_result, final_mileage)
        source_tag = f"מקור: מטמון (נשמר ב-{cached_result.get('last_date', 'N/A')})"
        if used_fallback: source_tag += " - ללא תת-דגם"
        cached_result['source_tag'] = source_tag
        cached_result['mileage_note'] = note
        cached_result['km_warn'] = not mileage_matched
        return jsonify(cached_result)

    print(f"DEBUG (3/6): Cache miss. Checking quota...")
    if not is_quota_ok:
        print(f"!!! שגיאה (שלב 3): המגבלה היומית הושגה.")
        return jsonify({"error": f"מגבלת שימוש (שלב 3): המגבלה היומית הושגה ({daily_count}/{GLOBAL_DAILY_LIMIT})."}), 429
    
    print(f"DEBUG (3/6): Quota OK. Proceeding ({daily_count + 1}/{GLOBAL_DAILY_LIMIT})")

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

    # --- שלב 6: שמירה ב-Sheet (לא קריטי) ---
    try:
        print("DEBUG (6/6): Saving new result to sheet...")
        issues_list = model_output.get("common_issues", []) or []
        issues_str = "; ".join([str(i) for i in issues_list if str(i).strip()])
        def safe_json_dump(data):
            try: return json.dumps(data, ensure_ascii=False)
            except Exception: return "[]" if isinstance(data, list) else "{}"

        save_row = {
            "date": datetime.date.today().isoformat(), "user_id": "global_flask_v1",
            "make": final_make, "model": final_model, "sub_model": final_sub_model,
            "year": final_year, "fuel": final_fuel, "transmission": final_trans,
            "mileage_range": final_mileage,
            "base_score_calculated": model_output.get("base_score_calculated"),
            "score_breakdown": safe_json_dump(model_output.get("score_breakdown", {})),
            "avg_cost": model_output.get("avg_repair_cost_ILS"), "issues": issues_str,
            "search_performed": model_output.get("search_performed", True),
            "reliability_summary": model_output.get("reliability_summary"),
            "issues_with_costs": safe_json_dump(model_output.get("issues_with_costs", [])),
            "sources": safe_json_dump(model_output.get("sources", [])),
            "recommended_checks": safe_json_dump(model_output.get("recommended_checks", [])),
            "common_competitors_brief": safe_json_dump(model_output.get("common_competitors_brief", []))
        }
        append_row_to_sheet(ws, save_row)
        print("DEBUG (6/6): Save complete.")
    except Exception as e:
        # זו לא שגיאה קריטית, אנחנו לא רוצים שהמשתמש יקבל שגיאה אם רק השמירה נכשלה
        print(f"!!! אזהרה (שלב 6): השמירה ל-Sheet נכשלה (המשתמש קיבל תשובה). שגיאה: {e}")
        traceback.print_exc()

    # --- סיום: החזרת תשובה ---
    model_output['source_tag'] = f"מקור: ניתוח AI חדש (שימוש {daily_count + 1}/{GLOBAL_DAILY_LIMIT})"
    model_output['mileage_note'] = note
    model_output['km_warn'] = False
    return jsonify(model_output)


if __name__ == '__main__':
    # פקודה זו מיועדת לפיתוח מקומי בלבד. Railway ישתמש ב-Gunicorn.
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=True, port=port)
