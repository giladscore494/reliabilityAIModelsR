# -*- coding: utf-8 -*-
# ===================================================================
# 🚗 Car Reliability Analyzer – Israel
# v6.5.2 (FINAL Auth Fix + Proxy + Safe Mileage + Dict Debug)
# ===================================================================

import os, re, json, difflib, traceback
import time as pytime
from typing import Optional, Tuple, Any, Dict, List
from datetime import datetime, time, timedelta

import pandas as pd
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    current_user, login_required
)
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
from json_repair import repair_json
import google.generativeai as genai

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

# ==================================
# === 2. מודלים של DB (גלובלי) ===
# ==================================
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(200), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100))
    searches = db.relationship('SearchHistory', backref='user', lazy=True)

class SearchHistory(db.Model):
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

# ==================================
# === 3. פונקציות עזר (גלובלי) ===
# ==================================

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- טעינת המילון עם דיבאג בולט ---
try:
    from car_models_dict import israeli_car_market_full_compilation
    print(f"[DICT] ✅ Loaded car_models_dict successfully. Manufacturers: {len(israeli_car_market_full_compilation)}")
    try:
        _total_models = sum(len(models) for models in israeli_car_market_full_compilation.values())
        print(f"[DICT] ✅ Total models loaded: {_total_models}")
    except Exception as inner_e:
        print(f"[DICT] ⚠️ Could not count models: {inner_e}")
except Exception as e:
    print(f"[DICT] ❌ Failed to import car_models_dict: {e}")
    israeli_car_market_full_compilation = {"Toyota": ["Corolla (2008-2025)"]}
    print("[DICT] ⚠️ Fallback applied — Toyota only")

def normalize_text(s: Any) -> str:
    if s is None:
        return ""
    s = re.sub(r"\(.*?\)", " ", str(s)).strip().lower()
    return re.sub(r"\s+", " ", s)

def mileage_adjustment(mileage_range: str) -> Tuple[int, Optional[str]]:
    m = normalize_text(mileage_range or "")
    if not m: return 0, None
    if "200" in m and "+" in m: return -15, "הציון הותאם מטה עקב קילומטראז׳ גבוה מאוד (200K+)."
    if "150" in m and "200" in m: return -10, "הציון הותאם מטה עקב קילומטראז׳ גבוה (150–200 אלף ק״מ)."
    if "100" in m and "150" in m: return -5, "הציון הותאם מעט מטה עקב קילומטראז׳ בינוני-גבוה (100–150 אלף ק״מ)."
    return 0, None

def apply_mileage_logic(model_output: dict, mileage_range: str) -> Tuple[dict, Optional[str]]:
    """אם יש ציון בסיסי כמספר – ניישם התאמה. אחרת לא ניגע."""
    try:
        adj, note = mileage_adjustment(mileage_range)
        base_key = "base_score_calculated"
        if base_key in model_output:
            try:
                base_val = float(model_output[base_key])
            except Exception:
                m = re.search(r"-?\d+(\.\d+)?", str(model_output[base_key]))
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
        try:
            llm = genai.GenerativeModel(model_name)
        except Exception as e:
            last_err = e
            print(f"[AI] ❌ Failed to init model {model_name}: {e}")
            continue
        for attempt in range(1, RETRIES + 1):
            try:
                print(f"[AI] Calling model {model_name} (attempt {attempt})")
                resp = llm.generate_content(prompt)
                raw = (getattr(resp, "text", "") or "").strip()
                try:
                    m = re.search(r"\{.*\}", raw, re.DOTALL)
                    data = json.loads(m.group()) if m else json.loads(raw)
                except Exception:
                    data = json.loads(repair_json(raw))
                print("[AI] ✅ Model call successful.")
                return data
            except Exception as e:
                print(f"[AI] ⚠️ Attempt {attempt} failed on {model_name}: {e}")
                last_err = e
                if attempt < RETRIES:
                    pytime.sleep(RETRY_BACKOFF_SEC)
                continue
    raise RuntimeError(f"Model failed: {repr(last_err)}")

# ========================================
# ===== 4. פונקציית ה-Factory של Flask ===
# ========================================
def create_app():
    app = Flask(__name__)

    # Proxy/HTTPS behind Railway/NGINX
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.config['PREFERRED_URL_SCHEME'] = 'https'
    if os.environ.get("FLASK_ENV") == "production":
        app.config['SESSION_COOKIE_SECURE'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # Secrets
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

    if not app.config['SQLALCHEMY_DATABASE_URI']:
        print("[BOOT] ⚠️ DATABASE_URL not set. Using in-memory sqlite.")
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

    if not app.config['SECRET_KEY']:
        print("[BOOT] ⚠️ SECRET_KEY not set. Using dev fallback.")
        app.config['SECRET_KEY'] = 'dev-secret-key-that-is-not-secret'

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)

    login_manager.login_view = 'index'

    # Gemini
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    if not GEMINI_API_KEY:
        print("[AI] ⚠️ GEMINI_API_KEY missing")
    genai.configure(api_key=GEMINI_API_KEY)

    # OAuth Google — OIDC discovery + claims_options for iss
    google = oauth.register(
        name='google',
        client_id=os.environ.get('GOOGLE_CLIENT_ID'),
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
        api_base_url='https://www.googleapis.com/oauth2/v1/',
        userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
        claims_options={
            'iss': {'values': ['https://accounts.google.com', 'accounts.google.com']}
        }
    )

    # ------------------ Routes ------------------

    @app.route('/health')
    def health():
        return jsonify({"ok": True, "time": datetime.now().isoformat()})

    @app.route('/')
    def index():
        # דיבאג — לבדוק שהמילון באמת מגיע לפרונט
        try:
            makes_count = len(israeli_car_market_full_compilation)
            print(f"[INDEX] Rendering with {makes_count} manufacturers")
        except Exception as e:
            print(f"[INDEX] ⚠️ Could not count manufacturers: {e}")
        return render_template(
            'index.html',
            car_models_data=israeli_car_market_full_compilation,
            user=current_user
        )

    @app.route('/login')
    def login():
        # build redirect_uri robustly behind proxy
        try:
            redirect_uri = url_for('auth', _external=True)
            if os.environ.get("FLASK_ENV") == "production" and redirect_uri.startswith("http://"):
                redirect_uri = redirect_uri.replace("http://", "https://", 1)
        except Exception:
            domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '127.0.0.1:5001')
            redirect_uri = f"https://{domain}/auth"
            if '127.0.0.1' in redirect_uri:
                redirect_uri = f"http://{domain}/auth"

        # דיבאג פרוטוקול שמגיע מכותרות הפרוקסי
        xf_proto = request.headers.get("X-Forwarded-Proto")
        xf_host = request.headers.get("X-Forwarded-Host")
        print(f"[AUTH] Redirecting to Google. redirect_uri={redirect_uri} X-Forwarded-Proto={xf_proto} X-Forwarded-Host={xf_host}")

        # state=None כדי לעקוף MismatchingState בסביבות פרוקסי
        return google.authorize_redirect(redirect_uri, state=None)

    @app.route('/auth')
    def auth():
        try:
            token = google.authorize_access_token()
            # לוג בסיסי על ה-token (ללא הדפסה של ערכים רגישים)
            print(f"[AUTH] ✅ Access token received. Keys: {list(token.keys()) if isinstance(token, dict) else 'n/a'}")

            userinfo = google.get('userinfo').json()
            print(f"[AUTH] userinfo keys: {list(userinfo.keys()) if isinstance(userinfo, dict) else 'n/a'}")

            if not userinfo or not userinfo.get('id'):
                raise RuntimeError("Userinfo missing or invalid.")

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
            print(f"[AUTH] ❌ Auth error: {e}")
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

    @app.route('/dashboard')
    @login_required
    def dashboard():
        try:
            user_searches = SearchHistory.query.filter_by(
                user_id=current_user.id
            ).order_by(SearchHistory.timestamp.desc()).all()
            searches_data = []
            for search in user_searches:
                search_data = {
                    "timestamp": search.timestamp.strftime('%d/%m/%Y %H:%M'),
                    "make": search.make, "model": search.model, "year": search.year,
                    "data": json.loads(search.result_json)
                }
                searches_data.append(search_data)
            return render_template('dashboard.html', searches=searches_data, user=current_user)
        except Exception as e:
            print(f"[DASH] ❌ Dashboard error: {e}")
            return redirect(url_for('index'))

    @app.route('/analyze', methods=['POST'])
    @login_required
    def analyze_car():
        # --- שלב 0: קלט ---
        try:
            data = request.json
            print(f"[ANALYZE 0/6] payload from user={current_user.id}: {data}")
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
            return jsonify({"error": f"שגיאת קלט (שלב 0): {str(e)}"}), 400

        # --- שלב 1: מגבלת משתמש ---
        try:
            print(f"[ANALYZE 1/6] checking quota for user={current_user.id}")
            today_start = datetime.combine(datetime.today().date(), time.min)
            today_end = datetime.combine(datetime.today().date(), time.max)

            user_searches_today = SearchHistory.query.filter(
                SearchHistory.user_id == current_user.id,
                SearchHistory.timestamp >= today_start,
                SearchHistory.timestamp <= today_end
            ).count()

            if user_searches_today >= USER_DAILY_LIMIT:
                print(f"[ANALYZE] quota exceeded user={current_user.id}")
                return jsonify({"error": f"שגיאת מגבלה (שלב 1): ניצלת את {USER_DAILY_LIMIT} החיפושים היומיים שלך. נסה שוב מחר."}), 429
            print(f"[ANALYZE] quota ok {user_searches_today}/{USER_DAILY_LIMIT}")
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": f"שגיאת שרת (שלב 1): נכשל בבדיקת המגבלה שלך. שגיאה: {str(e)}"}), 500

        # --- שלב 2–3: מטמון DB ---
        try:
            print("[ANALYZE 2/6] DB cache lookup…")
            cutoff_date = datetime.now() - timedelta(days=MAX_CACHE_DAYS)
            cached_result_db = SearchHistory.query.filter(
                SearchHistory.make == final_make,
                SearchHistory.model == final_model,
                SearchHistory.year == final_year,
                SearchHistory.mileage_range == final_mileage,
                SearchHistory.fuel_type == final_fuel,
                SearchHistory.transmission == final_trans,
                SearchHistory.timestamp >= cutoff_date
            ).order_by(SearchHistory.timestamp.desc()).first()

            if cached_result_db:
                print("[ANALYZE 3/6] cache HIT")
                cached_result = json.loads(cached_result_db.result_json)
                cached_result['source_tag'] = f"מקור: מטמון DB (נשמר ב-{cached_result_db.timestamp.strftime('%Y-%m-%d')})"
                return jsonify(cached_result)
            print("[ANALYZE 3/6] cache MISS")
        except Exception as e:
            print(f"[ANALYZE] cache check error: {e}")

        # --- שלב 4: Gemini ---
        try:
            today_start = datetime.combine(datetime.today().date(), time.min)
            today_end = datetime.combine(datetime.today().date(), time.max)
            global_searches_today = SearchHistory.query.filter(
                SearchHistory.timestamp >= today_start,
                SearchHistory.timestamp <= today_end
            ).count()
            if global_searches_today >= GLOBAL_DAILY_LIMIT:
                print("[ANALYZE 4/6] global limit reached")
                return jsonify({"error": f"שגיאת שרת (שלב 4): המגבלה הגלובלית הושגה ({global_searches_today}/{GLOBAL_DAILY_LIMIT}). נסה שוב מאוחר יותר."}), 503

            print("[ANALYZE 4/6] Calling Gemini…")
            prompt = build_prompt(
                final_make, final_model, final_sub_model, final_year,
                final_fuel, final_trans, final_mileage
            )
            model_output = call_model_with_retry(prompt)
            print("[ANALYZE 4/6] Gemini OK")
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": f"שגיאת AI (שלב 4): {str(e)}"}), 500

        # --- שלב 5: לוגיקת ק״מ ---
        print("[ANALYZE 5/6] mileage logic")
        model_output, note = apply_mileage_logic(model_output, final_mileage)

        # --- שלב 6: שמירה ---
        try:
            print(f"[ANALYZE 6/6] save result for user={current_user.id}")
            new_log = SearchHistory(
                user_id=current_user.id,
                make=final_make, model=final_model, year=final_year,
                mileage_range=final_mileage, fuel_type=final_fuel,
                transmission=final_trans,
                result_json=json.dumps(model_output, ensure_ascii=False)
            )
            db.session.add(new_log)
            db.session.commit()
            print("[ANALYZE] save complete")
        except Exception as e:
            print(f"[ANALYZE] ⚠️ DB save failed: {e}")
            db.session.rollback()

        model_output['source_tag'] = f"מקור: ניתוח AI חדש (חיפוש {user_searches_today + 1}/{USER_DAILY_LIMIT})"
        model_output['mileage_note'] = note
        model_output['km_warn'] = False
        return jsonify(model_output)

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
