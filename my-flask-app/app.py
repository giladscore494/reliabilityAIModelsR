# -*- coding: utf-8 -*-
# ===================================================================
# 🚗 Car Reliability Analyzer – Israel + Car Advisor (Recommendations)
# v8.0.0
# ===================================================================

import os, re, json, traceback
import time as pytime
from typing import Optional, Tuple, Any, Dict, List
from datetime import datetime, time, timedelta

from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    current_user, login_required
)
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
from json_repair import repair_json
import google.generativeai as genai  # למנוע האמינות
import pandas as pd

# --- Google GenAI החדש (Gemini 3 Pro למנוע המלצות) ---
try:
    from google import genai as genai_new
    from google.genai import types as genai_types
except Exception:
    genai_new = None
    genai_types = None

# ==================================
# === 1. יצירת אובייקטים גלובליים ===
# ==================================
db = SQLAlchemy()
login_manager = LoginManager()
oauth = OAuth()

# =========================
# ========= CONFIG ========
# =========================
PRIMARY_MODEL = "gemini-2.5-flash"
FALLBACK_MODEL = "gemini-1.5-flash-latest"
RETRIES = 2
RETRY_BACKOFF_SEC = 1.5
GLOBAL_DAILY_LIMIT = 1000
USER_DAILY_LIMIT = 5
MAX_CACHE_DAYS = 45

# Car Advisor (מנוע המלצות)
CAR_ADVISOR_MODEL_ID = "gemini-3-pro-preview"
CAR_ADVISOR_OWNER_EMAIL = "gameto818@gmail.com"
gemini3_client = None  # ימולא ב-create_app אם יש מפתח ו-SDK חדש

# ==================================
# === 2. מודלים של DB (גלובלי) ===
# ==================================
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(200), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100))

    searches = db.relationship('SearchHistory', backref='user', lazy=True)
    recommendations = db.relationship('RecommendationHistory', backref='user', lazy=True)


class SearchHistory(db.Model):
    """
    היסטוריית חיפושי אמינות (המערכת הקיימת)
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.now)
    make = db.Column(db.String(100))
    model = db.Column(db.String(100))
    year = db.Column(db.Integer)
    mileage_range = db.Column(db.String(100))
    fuel_type = db.Column(db.String(100))
    transmission = db.Column(db.String(100))
    result_json = db.Column(db.Text, nullable=False)


class RecommendationHistory(db.Model):
    """
    היסטוריית מנוע המלצות (Car Advisor) – חדש
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.now)

    profile_json = db.Column(db.Text, nullable=False)  # פרופיל משתמש (העדפות, שימוש וכו')
    result_json = db.Column(db.Text, nullable=False)   # פלט מלא מג'מיני (כולל recommended_cars + שיטות חישוב)


# ==================================
# === 3. פונקציות עזר (גלובלי) ===
# ==================================
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# --- טעינת המילון של המודלים (אמינות) ---
try:
    from car_models_dict import israeli_car_market_full_compilation
    print(f"[DICT] ✅ Loaded car_models_dict. Manufacturers: {len(israeli_car_market_full_compilation)}")
    try:
        _total_models = sum(len(models) for models in israeli_car_market_full_compilation.values())
        print(f"[DICT] ✅ Total models loaded: {_total_models}")
    except Exception as inner_e:
        print(f"[DICT] ⚠️ Count models failed: {inner_e}")
except Exception as e:
    print(f"[DICT] ❌ Failed to import car_models_dict: {e}")
    israeli_car_market_full_compilation = {"Toyota": ["Corolla (2008-2025)"]}
    print("[DICT] ⚠️ Fallback applied — Toyota only")


import re as _re
def normalize_text(s: Any) -> str:
    if s is None:
        return ""
    s = _re.sub(r"\(.*?\)", " ", str(s)).strip().lower()
    return _re.sub(r"\s+", " ", s)


def mileage_adjustment(mileage_range: str) -> Tuple[int, Optional[str]]:
    m = normalize_text(mileage_range or "")
    if not m:
        return 0, None
    if "200" in m and "+" in m:
        return -15, "הציון הותאם מטה עקב קילומטראז׳ גבוה מאוד (200K+)."
    if "150" in m and "200" in m:
        return -10, "הציון הותאם מטה עקב קילומטראז׳ גבוה (150–200 אלף ק״מ)."
    if "100" in m and "150" in m:
        return -5, "הציון הותאם מעט מטה עקב קילומטראז׳ בינוני-גבוה (100–150 אלף ק״מ)."
    return 0, None


def apply_mileage_logic(model_output: dict, mileage_range: str) -> Tuple[dict, Optional[str]]:
    try:
        adj, note = mileage_adjustment(mileage_range)
        base_key = "base_score_calculated"
        if base_key in model_output:
            try:
                base_val = float(model_output[base_key])
            except Exception:
                m = _re.search(r"-?\d+(\.\d+)?", str(model_output[base_key]))
                base_val = float(m.group()) if m else None
            if base_val is not None:
                new_val = max(0.0, min(100.0, base_val + adj))
                model_output[base_key] = round(new_val, 1)
        return model_output, note
    except Exception:
        return model_output, None


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
  "reliability_summary": "סיכום מקצועי בעברית שמסביר את הציון, יתרונות וחסרונות הרכב, ומאפייני האמינות בצורה מפורטת.",
  "reliability_summary_simple": "הסבר מאוד פשוט וקצר בעברית, ברמה של נהג צעיר שלא מבין ברכבים. בלי מושגים טכניים ובלי קיצורים. להסביר במילים פשוטות למה הציון יצא גבוה/בינוני/נמוך ומה המשמעות ליום-יום (האם זה רכב שיכול לעשות מעט בעיות, הרבה בעיות, כמה להיזהר בקנייה וכו׳).",
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
        try:
            llm = genai.GenerativeModel(model_name)
        except Exception as e:
            last_err = e
            print(f"[AI] ❌ init {model_name}: {e}")
            continue

        for attempt in range(1, RETRIES + 1):
            try:
                print(f"[AI] Calling {model_name} (attempt {attempt})")
                resp = llm.generate_content(prompt)
                raw = (getattr(resp, "text", "") or "").strip()
                try:
                    m = _re.search(r"\{.*\}", raw, _re.DOTALL)
                    data = json.loads(m.group()) if m else json.loads(raw)
                except Exception:
                    data = json.loads(repair_json(raw))
                print("[AI] ✅ success")
                return data
            except Exception as e:
                print(f"[AI] ⚠️ {model_name} attempt {attempt} failed: {e}")
                last_err = e
                if attempt < RETRIES:
                    pytime.sleep(RETRY_BACKOFF_SEC)
                continue

    raise RuntimeError(f"Model failed: {repr(last_err)}")


# ====================================================
# === 3b. פונקציות עזר – מנוע המלצות (Car Advisor) ===
# ====================================================

# מיפויים (אותו דבר כמו ב-Streamlit)
fuel_map = {
    "בנזין": "gasoline",
    "היברידי": "hybrid",
    "דיזל היברידי": "hybrid-diesel",
    "דיזל": "diesel",
    "חשמלי": "electric"
}
gear_map = {"אוטומטית": "automatic", "ידנית": "manual"}
turbo_map = {"לא משנה": "any", "כן": "yes", "לא": "no"}

fuel_map_he = {v: k for k, v in fuel_map.items()}
gear_map_he = {v: k for k, v in gear_map.items()}
turbo_map_he = {"yes": "כן", "no": "לא", "any": "לא משנה", True: "כן", False: "לא"}

column_map_he = {
    "brand": "מותג",
    "model": "דגם",
    "year": "שנה",
    "fuel": "דלק",
    "gear": "תיבה",
    "turbo": "טורבו",
    "engine_cc": "נפח מנוע (סמ\"ק)",
    "price_range_nis": "טווח מחיר (₪)",
    "avg_fuel_consumption": "צריכת דלק ממוצעת (ק\"מ/ל')",
    "annual_fee": "אגרה שנתית (₪)",
    "annual_energy_cost": "עלות דלק שנתית (₪)",
    "total_annual_cost": "עלות כוללת שנתית (₪)",
    "reliability_score": "אמינות",
    "maintenance_cost": "עלות אחזקה (₪/שנה)",
    "safety_rating": "בטיחות",
    "insurance_cost": "עלות ביטוח (₪/שנה)",
    "resale_value": "שמירת ערך",
    "performance_score": "ביצועים",
    "comfort_features": "נוחות",
    "suitability": "התאמה",
    "market_supply": "היצע בשוק",
    "fit_score": "ציון התאמה (0–100)"
}

method_map_he = {
    "fuel_method": "שיטת חישוב צריכת דלק/חשמל",
    "fee_method": "שיטת חישוב אגרה",
    "reliability_method": "שיטת חישוב אמינות",
    "maintenance_method": "שיטת חישוב עלות אחזקה",
    "safety_method": "שיטת חישוב בטיחות",
    "insurance_method": "שיטת חישוב ביטוח",
    "resale_method": "שיטת חישוב שמירת ערך",
    "performance_method": "שיטת חישוב ביצועים",
    "comfort_method": "שיטת חישוב נוחות",
    "suitability_method": "שיטת חישוב התאמה",
    "supply_method": "שיטת קביעת היצע"
}


def advisor_make_user_profile(
    budget_min, budget_max, years_range, fuels, gears,
    turbo_required, main_use, annual_km, driver_age,
    family_size, cargo_need, safety_required,
    trim_level, weights, body_style, driving_style,
    excluded_colors, license_years, driver_gender,
    insurance_history, violations, consider_supply,
    fuel_price, electricity_price, seats_choice
) -> dict:
    return {
        "budget_nis": [float(budget_min), float(budget_max)],
        "years": [int(years_range[0]), int(years_range[1])],
        "fuel": [f.lower() for f in fuels],
        "gear": [g.lower() for g in gears],
        "turbo_required": None if turbo_required == "any" else (turbo_required == "yes"),
        "main_use": main_use.strip(),
        "annual_km": int(annual_km),
        "driver_age": int(driver_age),
        "family_size": family_size,
        "cargo_need": cargo_need,
        "safety_required": safety_required,
        "trim_level": trim_level,
        "weights": weights,
        "body_style": body_style,
        "driving_style": driving_style,
        "excluded_colors": excluded_colors,

        "license_years": int(license_years),
        "driver_gender": driver_gender,
        "insurance_history": insurance_history,
        "violations": violations,
        "consider_market_supply": bool(consider_supply),
        "fuel_price_nis_per_liter": float(fuel_price),
        "electricity_price_nis_per_kwh": float(electricity_price),
        "seats": seats_choice
    }


def advisor_clean_gemini_output(cars_raw: Any) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    records, methods = [], []
    if not isinstance(cars_raw, list):
        return pd.DataFrame([]), []

    for car in cars_raw:
        if not isinstance(car, dict):
            continue
        record, method = {}, {}
        for k, v in car.items():
            if k.endswith("_method"):
                method[k] = v
            else:
                record[k] = v
        records.append(record)
        methods.append(method)

    return pd.DataFrame(records), methods


def advisor_normalize_car_values(df: pd.DataFrame) -> pd.DataFrame:
    if "fuel" in df.columns:
        df["fuel"] = df["fuel"].replace({
            "בנזין": "gasoline",
            "דיזל": "diesel",
            "היברידי": "hybrid",
            "דיזל היברידי": "hybrid-diesel",
            "חשמלי": "electric"
        })
    if "gear" in df.columns:
        df["gear"] = df["gear"].replace({
            "אוטומטי": "automatic",
            "אוטומטית": "automatic",
            "אוטומטי (DSG7)": "automatic",
            "אוטומטי (TCT)": "automatic",
            "אוטומטי (רובוטי)": "automatic",
            "ידני": "manual",
            "ידנית": "manual"
        })
    if "turbo" in df.columns:
        df["turbo"] = df["turbo"].replace({"כן": True, "לא": False, True: True, False: False})
    return df


def advisor_call_gemini_with_search(profile: dict) -> dict:
    """
    קריאה ל-Gemini 3 Pro עם Google Search מופעל ו-output כ-JSON בלבד.
    """
    global gemini3_client, genai_types

    if gemini3_client is None or genai_types is None:
        return {"_error": "Gemini 3 client unavailable (SDK או מפתח חסרים)."}

    prompt = f"""
Please recommend cars for an Israeli customer. Here is the user profile (JSON):
{json.dumps(profile, ensure_ascii=False, indent=2)}

You are an independent automotive data analyst for the **Israeli used car market**.

🔴 CRITICAL INSTRUCTION: USE GOOGLE SEARCH TOOL
You MUST use the Google Search tool to verify:
- that the specific model and trim are actually sold in Israel
- realistic used prices in Israel (NIS)
- realistic fuel/energy consumption values
- common issues (DSG, reliability, recalls)

Hard constraints:
- Return only ONE top-level JSON object.
- JSON fields: "search_performed", "search_queries", "recommended_cars".
- search_performed: ALWAYS true (boolean).
- search_queries: array of the real Hebrew queries you would run in Google (max 6).
- All numeric fields must be pure numbers (no units, no text).

recommended_cars: array of 5–10 cars. EACH car MUST include:
  - brand
  - model
  - year
  - fuel
  - gear
  - turbo
  - engine_cc
  - price_range_nis
  - avg_fuel_consumption (+ fuel_method):
      * non-EV: km per liter (number only)
      * EV: kWh per 100 km (number only)
  - annual_fee (₪/year, number only) + fee_method
  - reliability_score (1–10, number only) + reliability_method
  - maintenance_cost (₪/year, number only) + maintenance_method
  - safety_rating (1–10, number only) + safety_method
  - insurance_cost (₪/year, number only) + insurance_method
  - resale_value (1–10, number only) + resale_method
  - performance_score (1–10, number only) + performance_method
  - comfort_features (1–10, number only) + comfort_method
  - suitability (1–10, number only) + suitability_method
  - market_supply ("גבוה" / "בינוני" / "נמוך") + supply_method
  - fit_score (0–100, number only)
  - comparison_comment (Hebrew)
  - not_recommended_reason (Hebrew or null)

**All explanation fields (all *_method, comparison_comment, not_recommended_reason) MUST be in clean, easy Hebrew.**

IMPORTANT MARKET REALITY:
- לפני שאתה בוחר רכבים, תבדוק בזהירות בעזרת החיפוש שדגם כזה אכן נמכר בישראל, בתצורת מנוע וגיר שאתה מציג.
- אל תמציא דגמים או גרסאות שלא קיימים ביד 2 בישראל.
- מודלים שלא נמכרו כמעט / אין להם היצע – סמן "market_supply": "נמוך" והסבר בעברית.

Return ONLY raw JSON. Do not add any backticks or explanation text.
"""

    search_tool = genai_types.Tool(
        google_search=genai_types.GoogleSearch()
    )

    config = genai_types.GenerateContentConfig(
        temperature=0.3,
        top_p=0.9,
        top_k=40,
        tools=[search_tool],
        response_mime_type="application/json",
    )

    try:
        resp = gemini3_client.models.generate_content(
            model=CAR_ADVISOR_MODEL_ID,
            contents=prompt,
            config=config,
        )
        text = getattr(resp, "text", "") or ""
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"_error": "JSON decode error from Gemini", "_raw": text}
    except Exception as e:
        return {"_error": f"Gemini call failed: {e}"}


# ========================================
# ===== ★★★ 4. פונקציית ה-Factory ★★★ ======
# ========================================
def create_app():
    global gemini3_client

    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # פונקציה חכמה לבחירת redirect_uri
    def get_redirect_uri():
        domain = request.host or ""
        if "yedaarechev.com" in domain:
            uri = "https://yedaarechev.com/auth"
        else:
            uri = "https://reliabilityaimodelsr-production.up.railway.app/auth"
        print(f"[AUTH] Using redirect_uri={uri} (host={domain})")
        return uri

    # Secrets
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

    if not app.config['SQLALCHEMY_DATABASE_URI']:
        print("[BOOT] ⚠️ DATABASE_URL not set. Using in-memory sqlite.")
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    if not app.config['SECRET_KEY']:
        print("[BOOT] ⚠️ SECRET_KEY not set. Using dev fallback.")
        app.config['SECRET_KEY'] = 'dev-secret-key-that-is-not-secret'

    # Init
    db.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)

    # לא להפנות בטעות ל-/index
    login_manager.login_view = 'login'

    # Gemini key (למנוע האמינות + מנוע ההמלצות)
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    if not GEMINI_API_KEY:
        print("[AI] ⚠️ GEMINI_API_KEY missing")
    genai.configure(api_key=GEMINI_API_KEY)

    # Client חדש ל-Gemini 3 (Car Advisor)
    if GEMINI_API_KEY and genai_new is not None and genai_types is not None:
        try:
            gemini3_client = genai_new.Client(api_key=GEMINI_API_KEY)
            print("[CAR-ADVISOR] ✅ Gemini 3 client initialized.")
        except Exception as e:
            gemini3_client = None
            print(f"[CAR-ADVISOR] ❌ Failed to init Gemini 3 client: {e}")
    else:
        print("[CAR-ADVISOR] ⚠️ google-genai SDK or types missing – Car Advisor disabled.")

    # OAuth
    oauth.register(
        name='google',
        client_id=os.environ.get('GOOGLE_CLIENT_ID'),
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
        api_base_url='https://www.googleapis.com/oauth2/v1/',
        userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
        claims_options={'iss': {'values': ['https://accounts.google.com', 'accounts.google.com']}}
    )

    # ------------------
    # ===== ROUTES =====
    # ------------------
    @app.route('/')
    def index():
        return render_template(
            'index.html',
            car_models_data=israeli_car_market_full_compilation,
            user=current_user
        )

    @app.route('/login')
    def login():
        redirect_uri = get_redirect_uri()
        return oauth.google.authorize_redirect(redirect_uri, state=None)

    @app.route('/auth')
    def auth():
        try:
            token = oauth.google.authorize_access_token()
            userinfo = oauth.google.get('userinfo').json()
            user = User.query.filter_by(google_id=userinfo['id']).first()
            if not user:
                user = User(
                    google_id=userinfo['id'],
                    email=userinfo.get('email', ''),
                    name=userinfo.get('name', '')
                )
                db.session.add(user)
                db.session.commit()
            login_user(user)
            return redirect(url_for('index'))
        except Exception as e:
            print(f"[AUTH] ❌ {e}")
            traceback.print_exc()
            try:
                logout_user()
            except Exception:
                pass
            return redirect(url_for('index'))

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('index'))

    # Legal pages
    @app.route('/privacy')
    def privacy():
        return render_template('privacy.html', user=current_user)

    @app.route('/terms')
    def terms():
        return render_template('terms.html', user=current_user)

    @app.route('/dashboard')
    @login_required
    def dashboard():
        try:
            user_searches = SearchHistory.query.filter_by(
                user_id=current_user.id
            ).order_by(SearchHistory.timestamp.desc()).all()

            searches_data = []
            for s in user_searches:
                searches_data.append({
                    "id": s.id,
                    "timestamp": s.timestamp.strftime('%d/%m/%Y %H:%M'),
                    "make": s.make,
                    "model": s.model,
                    "year": s.year,
                    "mileage_range": s.mileage_range or '',
                    "fuel_type": s.fuel_type or '',
                    "transmission": s.transmission or '',
                    "data": json.loads(s.result_json)
                })

            # אפשר בהמשך להוסיף גם RecommendationHistory לדשבורד
            return render_template('dashboard.html', searches=searches_data, user=current_user)
        except Exception as e:
            print(f"[DASH] ❌ {e}")
            return redirect(url_for('index'))

    # ✅ NEW ROUTE: שליפת פרטים לדשבורד (AJAX)
    @app.route('/search-details/<int:search_id>')
    @login_required
    def search_details(search_id):
        try:
            s = SearchHistory.query.filter_by(id=search_id, user_id=current_user.id).first()
            if not s:
                return jsonify({"error": "לא נמצא רישום מתאים"}), 404

            meta = {
                "id": s.id,
                "timestamp": s.timestamp.strftime("%d/%m/%Y %H:%M"),
                "make": s.make.title(),
                "model": s.model.title(),
                "year": s.year,
                "mileage_range": s.mileage_range,
                "fuel_type": s.fuel_type,
                "transmission": s.transmission,
            }
            return jsonify({"meta": meta, "data": json.loads(s.result_json)})
        except Exception as e:
            print(f"[DETAILS] ❌ {e}")
            return jsonify({"error": "שגיאת שרת בשליפת נתוני חיפוש"}), 500

    # ======================================================
    # =============== מנוע אמינות – /analyze ===============
    # ======================================================
    @app.route('/analyze', methods=['POST'])
    @login_required
    def analyze_car():
        # 0) Input
        try:
            data = request.json
            print(f"[ANALYZE 0/6] user={current_user.id} payload: {data}")
            final_make = normalize_text(data.get('make'))
            final_model = normalize_text(data.get('model'))
            final_sub_model = normalize_text(data.get('sub_model'))
            final_year = int(data.get('year')) if data.get('year') else None
            final_mileage = str(data.get('mileage_range'))
            final_fuel = str(data.get('fuel_type'))
            final_trans = str(data.get('transmission'))
            if not (final_make and final_model and final_year):
                return jsonify({"error": "שגיאת קלט (שלב 0): נא למלא יצרן, דגם ושנה"}), 400
        except Exception as e:
            return jsonify({"error": f"שגיאת קלט (שלב 0): {str(e)}"}), 400

        # 1) User quota
        try:
            today_start = datetime.combine(datetime.today().date(), time.min)
            today_end = datetime.combine(datetime.today().date(), time.max)
            user_searches_today = SearchHistory.query.filter(
                SearchHistory.user_id == current_user.id,
                SearchHistory.timestamp >= today_start,
                SearchHistory.timestamp <= today_end
            ).count()
            if user_searches_today >= USER_DAILY_LIMIT:
                return jsonify({"error": f"שגיאת מגבלה (שלב 1): ניצלת את {USER_DAILY_LIMIT} החיפושים היומיים שלך. נסה שוב מחר."}), 429
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": f"שגיאת שרת (שלב 1): {str(e)}"}), 500

        # 2–3) Cache
        try:
            cutoff_date = datetime.now() - timedelta(days=MAX_CACHE_DAYS)
            cached = SearchHistory.query.filter(
                SearchHistory.make == final_make,
                SearchHistory.model == final_model,
                SearchHistory.year == final_year,
                SearchHistory.mileage_range == final_mileage,
                SearchHistory.fuel_type == final_fuel,
                SearchHistory.transmission == final_trans,
                SearchHistory.timestamp >= cutoff_date
            ).order_by(SearchHistory.timestamp.desc()).first()
            if cached:
                result = json.loads(cached.result_json)
                result['source_tag'] = f"מקור: מטמון DB (נשמר ב-{cached.timestamp.strftime('%Y-%m-%d')})"
                return jsonify(result)
        except Exception as e:
            print(f"[CACHE] ⚠️ {e}")

        # 4) AI call
        try:
            prompt = build_prompt(
                final_make, final_model, final_sub_model, final_year,
                final_fuel, final_trans, final_mileage
            )
            model_output = call_model_with_retry(prompt)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": f"שגיאת AI (שלב 4): {str(e)}"}), 500

        # 5) Mileage logic
        model_output, note = apply_mileage_logic(model_output, final_mileage)

        # 6) Save
        try:
            new_log = SearchHistory(
                user_id=current_user.id,
                make=final_make,
                model=final_model,
                year=final_year,
                mileage_range=final_mileage,
                fuel_type=final_fuel,
                transmission=final_trans,
                result_json=json.dumps(model_output, ensure_ascii=False)
            )
            db.session.add(new_log)
            db.session.commit()
        except Exception as e:
            print(f"[DB] ⚠️ save failed: {e}")
            db.session.rollback()

        model_output['source_tag'] = f"מקור: ניתוח AI חדש (חיפוש {user_searches_today + 1}/{USER_DAILY_LIMIT})"
        model_output['mileage_note'] = note
        model_output['km_warn'] = False
        return jsonify(model_output)

    # ======================================================
    # ========== מנוע המלצות – /recommendations ============
    # ======================================================
    @app.route('/recommendations')
    @login_required
    def recommendations():
        """
        עמוד מנוע המלצות.
        העיצוב הכללי (Header, Tailwind וכו') נשאר אצלך ב-templates/recommendations.html.
        כאן רק מעבירים האם המשתמש הוא הבעלים (גישה מלאה) או "בקרוב".
        """
        is_owner = current_user.is_authenticated and (
            current_user.email == CAR_ADVISOR_OWNER_EMAIL
        )
        return render_template(
            'recommendations.html',
            user=current_user,
            is_owner=is_owner
        )

    @app.route('/recommendations/submit', methods=['POST'])
    @login_required
    def recommendations_submit():
        """
        API שמקבל פרופיל משתמש (JSON), מריץ Gemini 3 Pro + Google Search
        ומחזיר רשימת רכבים מומלצים + טבלה מוכנה להצגה בפרונט.
        נגיש רק לך (ע"פ אימייל).
        """
        if current_user.email != CAR_ADVISOR_OWNER_EMAIL:
            return jsonify({"error": "גישה למנוע ההמלצות מוגבלת כרגע לבעל האתר בלבד."}), 403

        try:
            payload = request.json or {}
            print(f"[ADVISOR] user={current_user.id} payload={payload}")
        except Exception as e:
            return jsonify({"error": f"שגיאת קלט: {e}"}), 400

        # שליפת ערכים עם ברירות מחדל סבירות
        try:
            budget_min = float(payload.get("budget_min", 40000))
            budget_max = float(payload.get("budget_max", 65000))
            year_min = int(payload.get("year_min", 2015))
            year_max = int(payload.get("year_max", 2019))

            fuels_he = payload.get("fuels_he", ["בנזין"])
            gears_he = payload.get("gears_he", ["אוטומטית"])
            turbo_choice_he = payload.get("turbo_choice_he", "לא משנה")

            main_use = payload.get("main_use", "נסיעה יומיומית לעבודה וטיולים קצרים")
            annual_km = int(payload.get("annual_km", 15000))
            driver_age = int(payload.get("driver_age", 21))
            license_years = int(payload.get("license_years", 2))
            driver_gender = payload.get("driver_gender", "זכר")

            body_style = payload.get("body_style", "כללי")
            driving_style = payload.get("driving_style", "רגוע ונינוח")
            seats_choice = payload.get("seats_choice", "5")
            excluded_colors_raw = payload.get("excluded_colors", "")
            if isinstance(excluded_colors_raw, str):
                excluded_colors = [c.strip() for c in excluded_colors_raw.split(",") if c.strip()]
            elif isinstance(excluded_colors_raw, list):
                excluded_colors = [str(c).strip() for c in excluded_colors_raw if str(c).strip()]
            else:
                excluded_colors = []

            # weights
            weights = payload.get("weights", {})
            if not weights:
                weights = {
                    "reliability": int(payload.get("weight_reliability", 5)),
                    "resale": int(payload.get("weight_resale", 3)),
                    "fuel": int(payload.get("weight_fuel", 4)),
                    "performance": int(payload.get("weight_performance", 2)),
                    "comfort": int(payload.get("weight_comfort", 3)),
                }

            insurance_history = payload.get("insurance_history", "שנתיים ללא תביעות")
            violations = payload.get("violations", "אין")
            family_size = payload.get("family_size", "1-2")
            cargo_need = payload.get("cargo_need", "בינוני")
            safety_required = payload.get("safety_required", "כן")
            trim_level = payload.get("trim_level", "סטנדרטי")
            consider_supply = payload.get("consider_supply", "כן") == "כן"

            fuel_price = float(payload.get("fuel_price", 7.0))
            electricity_price = float(payload.get("electricity_price", 0.65))

            fuels = [fuel_map[f] for f in fuels_he if f in fuel_map]
            if not fuels:
                fuels = ["gasoline"]
            gears = [gear_map[g] for g in gears_he if g in gear_map]
            if not gears:
                gears = ["automatic"]
            turbo_choice = turbo_map.get(turbo_choice_he, "any")

            profile = advisor_make_user_profile(
                budget_min, budget_max, [year_min, year_max],
                fuels, gears, turbo_choice, main_use, annual_km, driver_age,
                family_size, cargo_need, safety_required, trim_level,
                weights, body_style, driving_style, excluded_colors,
                license_years, driver_gender, insurance_history, violations,
                consider_supply, fuel_price, electricity_price, seats_choice
            )
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": f"שגיאה בבניית פרופיל משתמש: {e}"}), 400

        # קריאה ל-Gemini 3
        parsed = advisor_call_gemini_with_search(profile)
        if parsed.get("_error"):
            return jsonify({"error": f"שגיאה מג׳מיני: {parsed.get('_error')}", "raw": parsed.get("_raw")}), 500

        if "recommended_cars" not in parsed:
            return jsonify({"error": "לא התקבל מפתח recommended_cars מפלט ג׳מיני."}), 500

        cars_raw = parsed.get("recommended_cars", [])
        results_df, methods_info = advisor_clean_gemini_output(cars_raw)

        if results_df is None or results_df.empty:
            return jsonify({"error": "לא התקבלו רכבים מפלט ג׳מיני."}), 500

        try:
            # נירמול
            results_df = advisor_normalize_car_values(results_df)

            if "avg_fuel_consumption" not in results_df.columns:
                return jsonify({"error": "חסר שדה avg_fuel_consumption בפלט ג׳מיני."}), 500

            # חישובי אנרגיה
            import numpy as np

            is_ev = results_df["fuel"].astype(str).str.lower().eq("electric")
            km_per_liter = results_df["avg_fuel_consumption"].where(~is_ev, np.nan).replace(0, np.nan)
            kwh_per_100km = results_df["avg_fuel_consumption"].where(is_ev, np.nan)

            fuel_cost = (profile["annual_km"] / km_per_liter) * fuel_price
            elec_cost = (profile["annual_km"] / 100.0) * kwh_per_100km * electricity_price

            results_df["annual_energy_cost"] = np.where(is_ev, elec_cost, fuel_cost)
            results_df["annual_fuel_cost"] = results_df["annual_energy_cost"]

            for col in ["maintenance_cost", "insurance_cost", "annual_fee"]:
                if col not in results_df.columns:
                    results_df[col] = 0.0

            results_df["total_annual_cost"] = (
                results_df["annual_energy_cost"].fillna(0) +
                results_df["maintenance_cost"].fillna(0) +
                results_df["insurance_cost"].fillna(0) +
                results_df["annual_fee"].fillna(0)
            )

            # כותרות צריכה בעברית לפי EV/דלק
            if results_df["fuel"].astype(str).str.lower().eq("electric").any():
                column_map_he["avg_fuel_consumption"] = "צריכת חשמל (קוט\"ש/100 ק\"מ)"
                column_map_he["annual_energy_cost"] = "עלות חשמל שנתית (₪)"
            else:
                column_map_he["avg_fuel_consumption"] = "צריכת דלק ממוצעת (ק\"מ/ל')"
                column_map_he["annual_energy_cost"] = "עלות דלק שנתית (₪)"

            # הכנה לתצוגה בעברית
            results_df_display = results_df.copy()
            if "annual_fuel_cost" in results_df_display.columns:
                results_df_display = results_df_display.drop(columns=["annual_fuel_cost"])
            results_df_display["fuel"] = results_df_display["fuel"].map(fuel_map_he).fillna(results_df_display["fuel"])
            results_df_display["gear"] = results_df_display["gear"].map(gear_map_he).fillna(results_df_display["gear"])
            results_df_display["turbo"] = results_df_display["turbo"].map(turbo_map_he).fillna(results_df_display["turbo"])
            results_df_display = results_df_display.rename(columns=column_map_he)

            cars_display = results_df_display.to_dict(orient="records")
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": f"שגיאה בעיבוד תוצאות ג׳מיני: {e}"}), 500

        # שמירה ב-DB
        try:
            rec = RecommendationHistory(
                user_id=current_user.id,
                profile_json=json.dumps(profile, ensure_ascii=False),
                result_json=json.dumps(parsed, ensure_ascii=False)
            )
            db.session.add(rec)
            db.session.commit()
        except Exception as e:
            print(f"[ADVISOR-DB] ⚠️ save failed: {e}")
            db.session.rollback()

        search_info = {
            "search_performed": parsed.get("search_performed", True),
            "search_queries": parsed.get("search_queries", [])
        }

        return jsonify({
            "ok": True,
            "search_info": search_info,
            "cars": cars_display,
            "methods": methods_info,
            "raw_count": len(cars_raw)
        })

    @app.cli.command("init-db")
    def init_db_command():
        with app.app_context():
            db.create_all()
        print("Initialized the database tables.")

    return app


# ===================================================================
# ===== 5. נקודת כניסה (Gunicorn/Flask) =====
# ===================================================================
app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=True, port=port)
