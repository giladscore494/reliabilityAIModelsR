# -*- coding: utf-8 -*-
# ===================================================================
# 🚗 Car Reliability Analyzer – Israel (v6.2.0 • Factory Pattern)
# ===================================================================

import json, re, time, datetime, difflib, traceback, os
from typing import Optional, Tuple, Any, Dict, List
from datetime import datetime, time, timedelta

import pandas as pd
from flask import Flask, render_template, request, jsonify, redirect, url_for
from json_repair import repair_json
import google.generativeai as genai
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    current_user,
    login_required,
)
from authlib.integrations.flask_client import OAuth

# ==================================
# === 1. יצירת אובייקטים גלובליים (ריקים) ===
# ==================================
# ניצור אותם כאן, אבל נאתחל אותם בתוך ה-Factory
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
# === 2. הגדרת מודלים של DB (גלובלי) ===
# ==================================
# זה בסדר להגדיר אותם כאן כי הם תלויים רק באובייקט db הריק
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

# --- פונקציית טעינת משתמש ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Models dictionary (נטען רק פעם אחת) ---
try:
    from car_models_dict import israeli_car_market_full_compilation
except Exception:
    israeli_car_market_full_compilation = { "Toyota": ["Corolla (2008-2025)"] }

# --- פונקציות עזר כלליות ---
def normalize_text(s: Any) -> str:
    if s is None: return ""
    s = re.sub(r"\(.*?\)", " ", str(s)).strip().lower()
    return re.sub(r"\s+", " ", s)

def mileage_adjustment(mileage_range: str) -> Tuple[int, Optional[str]]:
    m = normalize_text(mileage_range or "")
    if not m: return 0, None
    if "200" in m and "+" in m: return -15, "הציון הותאם מטה עקב קילומטראז׳ גבוה מאוד (200K+)."
    if "150" in m and "200" in m: return -10, "הציון הותאם מטה עקב קילומטראז׳ גבוה (150–200 אלף ק״מ)."
    if "100" in m and "150" in m: return -5, "הציון הותאם מעט מטה עקב קילומטראז׳ בינוני-גבוה (100–150 אלף ק״מ)."
    return 0, None

# --- פונקציות מודל ---
def build_prompt(make, model, sub_model, year, fuel_type, transmission, mileage_range):
    extra = f" תת-דגם/תצורה: {sub_model}" if sub_model else ""
    # ... (קיצרתי את הפרומפט שלך, אבל הקוד המלא שלך צריך להיות כאן) ...
    return f"""
    אתה מומחה לאמינות רכבים...
    ... (הפרומפט המלא שלך כאן) ...
    רכב: {make} {model}{extra} {int(year)}
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

# ========================================
# ===== ★★★ 4. פונקציית ה-Factory ★★★ ======
# ========================================
def create_app():
    """
    יוצר ומגדיר את אפליקציית Flask.
    """
    app = Flask(__name__)
    
    # --- 4A. טעינת הגדרות (Secrets) ---
    # זה רץ רק בשלב ה-Deploy, לא ב-Build, ולכן יצליח
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') 
    
    if not app.config['SQLALCHEMY_DATABASE_URI']:
        print("WARNING: DATABASE_URL is not set. Using in-memory SQLite DB.")
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
    if not app.config['SECRET_KEY']:
        print("WARNING: SECRET_KEY is not set. Using a weak dev key.")
        app.config['SECRET_KEY'] = 'dev-secret'

    # --- 4B. אתחול ההרחבות עם האפליקציה ---
    db.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)

    login_manager.login_view = 'index' # הגדרה מחדש

    # --- 4C. הגדרת סודות נוספים ---
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    if not GEMINI_API_KEY:
        print("WARNING: חסר GEMINI_API_KEY")
    genai.configure(api_key=GEMINI_API_KEY)

    # --- 4D. רישום ספק ה-OAuth (גוגל) ---
    # חייב לקרות *אחרי* oauth.init_app(app)
    google = oauth.register(
        name='google',
        client_id=os.environ.get('GOOGLE_CLIENT_ID'),
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
        access_token_url='https://accounts.google.com/o/oauth2/token',
        access_token_params=None,
        authorize_url='https://accounts.google.com/o/oauth2/auth',
        authorize_params=None,
        api_base_url='https://www.googleapis.com/oauth2/v1/',
        userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
        client_kwargs={'scope': 'openid email profile'},
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration'
    )

    # --- 4E. רישום ה-Routes (נתיבים) ---
    # אנחנו מגדירים את הנתיבים *בתוך* ה-Factory
    
    @app.route('/')
    def index():
        return render_template('index.html', 
                               car_models_data=israeli_car_market_full_compilation, 
                               user=current_user)

    @app.route('/login')
    def login():
        domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '127.0.0.1:5001')
        redirect_uri = f"https://{domain}/auth"
        if '127.0.0.1' in redirect_uri:
            redirect_uri = f"http://{domain}/auth"
        print(f"DEBUG: Redirecting to Google with callback URI: {redirect_uri}")
        return google.authorize_redirect(redirect_uri)

    @app.route('/auth')
    def auth():
        try:
            token = google.authorize_access_token()
            userinfo = google.get('userinfo').json()
            user = User.query.filter_by(google_id=userinfo['id']).first()
            if not user:
                user = User(
                    google_id=userinfo['id'],
                    email=userinfo['email'],
                    name=userinfo['name']
                )
                db.session.add(user)
                db.session.commit()
            login_user(user)
            return redirect(url_for('index'))
        except Exception as e:
            print(f"!!! שגיאת Auth: {e}")
            traceback.print_exc()
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
            user_searches = SearchHistory.query.filter_by(user_id=current_user.id).order_by(SearchHistory.timestamp.desc()).all()
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
            print(f"!!! שגיאת דשבורד: {e}")
            return redirect(url_for('index'))

    @app.route('/analyze', methods=['POST'])
    @login_required
    def analyze_car():
        # --- שלב 0: קבלת נתונים ---
        try:
            data = request.json
            print(f"DEBUG (0/6): Received data from user {current_user.id}: {data}")
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

        # --- שלב 1: בדיקת מגבלת משתמש יומית ---
        try:
            print(f"DEBUG (1/6): Checking user quota for user {current_user.id}...")
            today_start = datetime.combine(datetime.today().date(), time.min)
            today_end = datetime.combine(datetime.today().date(), time.max)
            
            user_searches_today = SearchHistory.query.filter(
                SearchHistory.user_id == current_user.id,
                SearchHistory.timestamp >= today_start,
                SearchHistory.timestamp <= today_end
            ).count()

            if user_searches_today >= USER_DAILY_LIMIT:
                print(f"!!! שגיאה (שלב 1): משתמש {current_user.id} חרג מהמגבלה.")
                return jsonify({"error": f"שגיאת מגבלה (שלב 1): ניצלת את {USER_DAILY_LIMIT} החיפושים היומיים שלך. נסה שוב מחר."}), 429
            
            print(f"DEBUG (1/6): User quota OK ({user_searches_today}/{USER_DAILY_LIMIT}).")
        except Exception as e:
            print(f"!!! שגיאה (שלב 1): נכשל בבדיקת מגבלת משתמש.")
            traceback.print_exc()
            return jsonify({"error": f"שגיאת שרת (שלב 1): נכשל בבדיקת המגבלה שלך. שגיאה: {str(e)}"}), 500

        # --- שלב 2: חיפוש במטמון ב-DB ---
        try:
            print("DEBUG (2/6): Fetching cache from DB...")
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
                print("DEBUG (3/6): Cache hit. Skipping model call.")
                cached_result = json.loads(cached_result_db.result_json)
                cached_result['source_tag'] = f"מקור: מטמון DB (נשמר ב-{cached_result_db.timestamp.strftime('%Y-%m-%d')})"
                return jsonify(cached_result)

            print("DEBUG (3/6): Cache miss. Proceeding to API call.")
        except Exception as e:
            print(f"!!! שגיאה (שלב 2): נכשל בחיפוש במטמון ב-DB. {e}")
            pass # לא עוצרים

        # --- שלב 4: פנייה ל-Gemini ---
        global_searches_today = 0
        try:
            today_start = datetime.combine(datetime.today().date(), time.min)
            today_end = datetime.combine(datetime.today().date(), time.max)
            global_searches_today = SearchHistory.query.filter(
                SearchHistory.timestamp >= today_start,
                SearchHistory.timestamp <= today_end
            ).count()
            
            if global_searches_today >= GLOBAL_DAILY_LIMIT:
                print(f"!!! שגיאה (שלב 4): המגבלה הגלובלית הושגה.")
                return jsonify({"error": f"שגיאת שרת (שלב 4): המגבלה הגלובלית הושגה ({global_searches_today}/{GLOBAL_DAILY_LIMIT}). נסה שוב מאוחר יותר."}), 503

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
            return jsonify({"error": f"שגיאת AI (שלב 4): {str(e)}"}), 500

        # --- שלב 5: החלת לוגיקת ק"מ ---
        print("DEBUG (5/6): Applying mileage logic...")
        model_output, note = apply_mileage_logic(model_output, final_mileage)

        # --- שלב 6: שמירה ב-DB ---
        try:
            print(f"DEBUG (6/6): Saving new result to DB for user {current_user.id}...")
            new_log = SearchHistory(
                user_id = current_user.id,
                make = final_make, model = final_model, year = final_year,
                mileage_range = final_mileage, fuel_type = final_fuel,
                transmission = final_trans,
                result_json = json.dumps(model_output, ensure_ascii=False)
            )
            db.session.add(new_log)
            db.session.commit()
            print("DEBUG (6/6): Save complete.")
        except Exception as e:
            print(f"!!! אזהרה (שלב 6): השמירה ל-DB נכשלה. {e}")
            db.session.rollback()

        # --- סיום: החזרת תשובה ---
        model_output['source_tag'] = f"מקור: ניתוח AI חדש (חיפוש {user_searches_today + 1}/{USER_DAILY_LIMIT})"
        model_output['mileage_note'] = note
        model_output['km_warn'] = False
        return jsonify(model_output)

    # --- 4F. רישום פקודת ה-CLI ---
    @app.cli.command("init-db")
    def init_db_command():
        """יוצר את טבלאות בסיס הנתונים."""
        with app.app_context():
            db.create_all()
        print("Initialized the database tables.")

    # --- 4G. החזרת האפליקציה ---
    return app


# ========================================
# ===== ★★★ 5. נקודת כניסה ★★★ ======
# ========================================
# הפקודה הזו יוצרת את האפליקציה כדי שה-CLI של Flask יוכל למצוא אותה
app = create_app()

if __name__ == '__main__':
    # הרצה מקומית בלבד
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=True, port=port)
