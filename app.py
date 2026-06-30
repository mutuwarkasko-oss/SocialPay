"""
SocialPay Web App v9.0
- SQLite database (replaces all JSON files)
- Auto-delete submissions after approval (admin can delete any submission)
- Multi-level referrals (L1 + L2)
- PalmPay-style design
- Sign-up reward, daily login, spin & win
- Admin super_admin role system
- PWA support, Telegram integration
- v6 security: werkzeug password hashing (backward-compat), CSRF tokens,
               hardened session config, proper error handlers, env-based secret
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort
import sqlite3, os, hashlib, secrets, random, string, json, time as _time_module
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

_HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__,
            template_folder=os.path.join(_HERE, "templates"),
            static_folder=os.path.join(_HERE, "static"))

# ── Security: secret key MUST come from env in production ──────────────────
_fallback_key = secrets.token_hex(32)   # random per-process; fine for dev
app.secret_key = os.environ.get("SECRET_KEY", _fallback_key)

app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)   # was 10 years
app.config["SESSION_COOKIE_SECURE"]   = os.environ.get("FLASK_ENV") == "production"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

APP_NAME = "SocialPay"
VERSION  = "9.0"

TG_CHANNEL = "https://t.me/socialpaychannel"
TG_GROUP   = "https://t.me/socialearningpay"
TG_SUPPORT = "https://t.me/socialpaysupport"
TG_SUPPORT_USERNAME = "@socialpaysupport"

# ── Admin credentials: prefer env vars, fall back to defaults ──────────────
ADMIN_EMAIL    = os.environ.get("ADMIN_EMAIL",    "socialpay.app.ng@gmail.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "@ Ahmerdee4622")
ADMIN_NAME     = "SocialPay Admin"

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
VOLUME_DIR = "/data"
LOCAL_DIR  = os.path.join(BASE_DIR, "data")

if os.path.exists(VOLUME_DIR) and os.access(VOLUME_DIR, os.W_OK):
    DATA_DIR = VOLUME_DIR
else:
    DATA_DIR = LOCAL_DIR

os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "socialpay.db")

# ============================================================
# DATABASE
# ============================================================
def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db

def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        role TEXT DEFAULT 'user',
        banned INTEGER DEFAULT 0,
        verified INTEGER DEFAULT 1,
        created TEXT,
        last_login TEXT,
        referral_code TEXT,
        referred_by TEXT,
        lang TEXT DEFAULT 'en',
        signup_reward_given INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS wallets (
        user_id TEXT PRIMARY KEY,
        naira REAL DEFAULT 0,
        dollar REAL DEFAULT 0,
        completed_tasks INTEGER DEFAULT 0,
        pending_tasks INTEGER DEFAULT 0,
        referral_count INTEGER DEFAULT 0,
        referral_count_l2 INTEGER DEFAULT 0,
        referral_bonus_earned REAL DEFAULT 0,
        total_earned REAL DEFAULT 0,
        total_withdrawn REAL DEFAULT 0,
        created TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT,
        platform TEXT,
        task_type TEXT,
        link TEXT,
        reward REAL DEFAULT 0,
        currency TEXT DEFAULT 'naira',
        max_users INTEGER DEFAULT 100,
        status TEXT DEFAULT 'active',
        auto_approve INTEGER DEFAULT 0,
        completed_count INTEGER DEFAULT 0,
        expires_at TEXT,
        created TEXT,
        created_by TEXT
    );
    CREATE TABLE IF NOT EXISTS task_completions (
        task_id TEXT,
        user_id TEXT,
        PRIMARY KEY(task_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS submissions (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        task_id TEXT,
        proof TEXT,
        screenshot TEXT,
        status TEXT DEFAULT 'pending',
        reward REAL DEFAULT 0,
        currency TEXT DEFAULT 'naira',
        submitted_at TEXT,
        reviewed_at TEXT,
        note TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS withdrawals (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        amount REAL,
        fee REAL,
        net REAL,
        currency TEXT DEFAULT 'naira',
        bank_info TEXT,
        status TEXT DEFAULT 'pending',
        requested_at TEXT,
        processed_at TEXT,
        note TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS transfers (
        id TEXT PRIMARY KEY,
        sender_id TEXT,
        receiver_id TEXT,
        amount REAL,
        status TEXT DEFAULT 'completed',
        time TEXT,
        reversed_at TEXT,
        reversed_by TEXT
    );
    CREATE TABLE IF NOT EXISTS exchanges (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        from_currency TEXT,
        from_amount REAL,
        to_currency TEXT,
        to_amount REAL,
        rate REAL,
        time TEXT
    );
    CREATE TABLE IF NOT EXISTS pins (
        user_id TEXT PRIMARY KEY,
        pin_hash TEXT,
        created TEXT
    );
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id TEXT,
        referred_id TEXT,
        level INTEGER DEFAULT 1,
        time TEXT,
        bonus_paid INTEGER DEFAULT 0,
        tasks_done INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        message TEXT,
        type TEXT DEFAULT 'info',
        time TEXT,
        read INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    CREATE TABLE IF NOT EXISTS audit_logs (
        id TEXT PRIMARY KEY,
        action TEXT,
        user_id TEXT,
        detail TEXT,
        amount REAL DEFAULT 0,
        time TEXT
    );
    CREATE TABLE IF NOT EXISTS support_tickets (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        user_name TEXT,
        user_email TEXT,
        subject TEXT,
        message TEXT,
        category TEXT DEFAULT 'general',
        status TEXT DEFAULT 'open',
        created TEXT
    );
    CREATE TABLE IF NOT EXISTS support_replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id TEXT,
        from_role TEXT,
        name TEXT,
        message TEXT,
        time TEXT
    );
    CREATE TABLE IF NOT EXISTS transactions (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        type TEXT,
        amount REAL,
        currency TEXT,
        description TEXT,
        ref_id TEXT,
        time TEXT,
        status TEXT DEFAULT 'completed'
    );
    CREATE TABLE IF NOT EXISTS daily_logins (
        user_id TEXT PRIMARY KEY,
        last_date TEXT,
        total_days INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS spins (
        user_id TEXT PRIMARY KEY,
        last_spin TEXT,
        total_spins INTEGER DEFAULT 0,
        total_spent REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS bank_details (
        user_id TEXT PRIMARY KEY,
        bank_name TEXT,
        account_number TEXT,
        account_name TEXT,
        type TEXT DEFAULT 'bank',
        updated TEXT
    );
    CREATE TABLE IF NOT EXISTS login_attempts (
        email TEXT PRIMARY KEY,
        count INTEGER DEFAULT 0,
        locked_until TEXT
    );
    CREATE TABLE IF NOT EXISTS user_tracking (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        ip_address TEXT,
        country TEXT,
        city TEXT,
        device_info TEXT,
        time TEXT
    );
    CREATE TABLE IF NOT EXISTS admin_messages (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        sender_id TEXT,
        message TEXT,
        image TEXT DEFAULT '',
        time TEXT,
        read INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS achievements (
        user_id TEXT,
        badge TEXT,
        earned_at TEXT,
        PRIMARY KEY(user_id, badge)
    );
    CREATE TABLE IF NOT EXISTS streak_bonuses (
        user_id TEXT PRIMARY KEY,
        current_streak INTEGER DEFAULT 0,
        last_claimed_date TEXT,
        total_bonus_earned REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS jackpot_pool (
        id INTEGER PRIMARY KEY CHECK(id=1),
        amount REAL DEFAULT 0,
        last_winner TEXT,
        last_win_time TEXT
    );
    CREATE TABLE IF NOT EXISTS ip_blacklist (
        ip TEXT PRIMARY KEY,
        reason TEXT,
        added_by TEXT,
        added_at TEXT
    );
    CREATE TABLE IF NOT EXISTS scheduled_tasks (
        id TEXT PRIMARY KEY,
        task_data TEXT,
        publish_at TEXT,
        published INTEGER DEFAULT 0,
        created_by TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS goals (
        user_id TEXT PRIMARY KEY,
        target REAL DEFAULT 0,
        currency TEXT DEFAULT 'naira'
    );
    CREATE TABLE IF NOT EXISTS chat_messages (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        sender_role TEXT,
        message TEXT,
        time TEXT,
        read INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS push_subscriptions (
        user_id TEXT,
        endpoint TEXT,
        p256dh TEXT,
        auth TEXT,
        created TEXT,
        PRIMARY KEY(user_id, endpoint)
    );
    CREATE TABLE IF NOT EXISTS vapid_keys (
        id INTEGER PRIMARY KEY CHECK(id=1),
        private_key TEXT,
        public_key TEXT,
        created TEXT
    );
    CREATE TABLE IF NOT EXISTS analytics_daily (
        date TEXT PRIMARY KEY,
        new_users INTEGER DEFAULT 0,
        total_earned REAL DEFAULT 0,
        total_withdrawn REAL DEFAULT 0,
        spins_done INTEGER DEFAULT 0,
        tasks_approved INTEGER DEFAULT 0,
        transfers_done INTEGER DEFAULT 0
    );
    """)
    # v8 migrations
    for migration in [
        "ALTER TABLE notifications ADD COLUMN image TEXT DEFAULT ''",
        "ALTER TABLE spins ADD COLUMN pending_prize REAL DEFAULT 0",
        "ALTER TABLE spins ADD COLUMN pending_prize_label TEXT DEFAULT ''",
    ]:
        try:
            db.execute(migration)
            db.commit()
        except: pass
    db.commit()
    db.close()

# ============================================================
# TRANSLATIONS
# ============================================================
TRANSLATIONS = {
    "en": {
        "app_name":"SocialPay","tagline":"Earn Money via Social Media Tasks","login":"Login",
        "register":"Register","email":"Email Address","password":"Password",
        "full_name":"Full Name","confirm_password":"Confirm Password",
        "referral_code":"Referral Code (Optional)","create_account":"Create Account",
        "login_now":"Login Now","welcome_back":"Welcome back","total_balance":"Total Balance",
        "tasks":"Tasks","balance":"Balance","transfer":"Transfer","referrals":"Referrals",
        "withdraw":"Withdraw","exchange":"Exchange","profile":"Profile","history":"History",
        "notifications":"Notifications","logout":"Logout","available_tasks":"Available Tasks",
        "my_earnings":"My Earnings","completed_tasks":"Completed Tasks","pending_tasks":"Pending",
        "send_proof":"Submit Proof","proof_placeholder":"Link, username, screenshot URL...",
        "submit":"Submit for Review","withdraw_money":"Withdraw Money",
        "exchange_currency":"Exchange Currency","send_money":"Send Money",
        "receiver_id":"Receiver's User ID","amount":"Amount","pin":"4-digit PIN",
        "send_now":"Send Now","cancel":"Cancel","save":"Save","set_pin":"Set PIN",
        "change_pin":"Change PIN","bank_details":"Bank / Payment Details",
        "bank_name":"Bank Name","account_number":"Account Number","account_name":"Account Name",
        "payment_type":"Payment Type","referral_link":"Your Referral Link","copy":"Copy",
        "share_whatsapp":"WhatsApp","share_telegram":"Telegram",
        "how_referral_works":"How Referrals Work","reward":"Reward","status":"Status",
        "pending":"Pending","approved":"Approved","rejected":"Rejected",
        "no_tasks":"No Tasks Available","no_tasks_desc":"Check back soon! Admin will add new tasks.",
        "no_notifications":"No Notifications","admin_panel":"Admin Panel",
        "total_users":"Total Users","active_tasks":"Active Tasks",
        "pending_approvals":"Pending Approvals","pending_withdrawals":"Pending Withdrawals",
        "fill_all_fields":"Please fill all required fields",
        "password_short":"Password must be at least 8 characters",
        "task_submitted":"Task submitted! Awaiting admin review.",
        "already_submitted":"You already submitted this task",
        "insufficient_balance":"Insufficient balance","withdraw_min":"Minimum withdrawal is",
        "pin_required":"You need to set a PIN first","pin_wrong":"Wrong PIN",
        "pin_set":"PIN set successfully!","pin_4digits":"PIN must be exactly 4 digits",
        "profile_updated":"Profile updated!","bank_saved":"Bank details saved!",
        "balance_adjusted":"Balance adjusted!","user_banned":"User has been banned",
        "user_unbanned":"User has been unbanned","pin_reset":"PIN has been reset",
        "message_sent":"Message sent!","task_created":"Task created!","task_deleted":"Task deleted!",
        "submission_approved":"Submission approved! Payment added.",
        "submission_rejected":"Submission rejected.","withdrawal_approved":"Withdrawal approved!",
        "withdrawal_rejected":"Withdrawal rejected. Funds refunded.",
        "transfer_reversed":"Transfer reversed!","broadcast":"Broadcast","broadcast_sent":"Broadcast sent!",
        "settings_saved":"Settings saved!","money_sent":"Money sent successfully!",
        "exchanged":"Currency exchanged!","user_not_found":"User not found",
        "cannot_send_self":"Cannot send to yourself","admin_notice":"Admin Notice",
        "from_admin":"From Admin","referral_bonus_earned":"Referral bonus earned!",
        "withdrawal_request":"Withdrawal request submitted!","wrong_email_or_password":"Wrong email or password","approve":"Approve","reject":"Reject","reverse":"Reverse","transfers_log":"Transfers Log","refunded":"refunded",
        "account_banned":"Your account has been banned. Contact support.",
        "email_exists":"This email is already registered","my_id":"My User ID",
        "edit_profile":"Edit Profile","old_password":"Current Password","new_password":"New Password",
        "total_earned":"Total Earned","total_withdrawn":"Total Withdrawn",
        "referral_earned":"Referral Bonus Earned","select_language":"Language",
        "forgot_password":"Forgot Password",
        "bank_duplicate":"This bank account is already linked to another user",
        "bank_contact_support":"Please contact support to change bank details",
        "transfer_disabled":"Transfers are currently disabled",
        "transfer_min":"Minimum transfer amount is","transfer_max":"Maximum transfer amount is",
        "transfer_daily_limit":"Daily transfer limit reached",
        "too_many_attempts":"Too many login attempts. Try again in 15 minutes.",
        "new_message_alert":"You have a new message. Please check.",
        "approve":"Approve","reject":"Reject","reverse":"Reverse","transfers_log":"Transfers Log","refunded":"refunded",
    },
    "ha": {
        "app_name":"SocialPay","tagline":"Samu Kuɗi ta Hanyar Ayyukan Social Media",
        "login":"Shiga","register":"Ƙirƙiri Account","email":"Adireshin Email","password":"Password",
        "full_name":"Cikakken Suna","confirm_password":"Tabbatar da Password",
        "referral_code":"Lambar Kiran Aboki (zaɓi)","create_account":"Ƙirƙiri Account Yanzu",
        "login_now":"Shiga Yanzu","welcome_back":"Barka da dawowa","total_balance":"Jimillar Kuɗi",
        "tasks":"Ayyuka","balance":"Kuɗi","transfer":"Aika","referrals":"Kiraye",
        "withdraw":"Cire","exchange":"Canza","profile":"Profile","history":"Tarihi",
        "notifications":"Sanarwa","logout":"Fita","available_tasks":"Ayyukan da Samu",
        "my_earnings":"Kuɗaɗena","completed_tasks":"Ayyuka Kammala","pending_tasks":"Jira",
        "send_proof":"Aika Shaida","proof_placeholder":"Link, username, ko hanyar screenshot...",
        "submit":"Aika don Bincike","withdraw_money":"Fitar da Kuɗi",
        "exchange_currency":"Canza Kuɗi","send_money":"Aika Kuɗi","receiver_id":"ID na Mai Karɓa",
        "amount":"Adadi","pin":"PIN haruffa 4","send_now":"Aika Yanzu","cancel":"Soke","save":"Ajiye",
        "set_pin":"Saita PIN","change_pin":"Canza PIN","bank_details":"Bayanin Banku / Kuɗi",
        "bank_name":"Sunan Banku","account_number":"Lambar Akwatin Kuɗi","account_name":"Suna a Banku",
        "payment_type":"Nau'in Kuɗi","referral_link":"Hanyar Kiran Ku","copy":"Kwafa",
        "share_whatsapp":"WhatsApp","share_telegram":"Telegram",
        "how_referral_works":"Yadda Ake Samun Lada","reward":"Lada","status":"Yanayi",
        "pending":"Jira","approved":"An Amince","rejected":"An Ƙi","no_tasks":"Babu Ayyuka a Yanzu",
        "no_tasks_desc":"Duba baya! Admin zai ƙara ayyuka sabon.","no_notifications":"Babu Sanarwa",
        "fill_all_fields":"Cika duk filayen da ake bukata",
        "password_short":"Password ya zama akalla haruffa 8",
        "task_submitted":"Aiki an aika! Ana jiran amincewa admin.",
        "already_submitted":"Kun riga kun aika wannan aiki","insufficient_balance":"Kudinka ba ya isawa",
        "withdraw_min":"Mafi ƙarancin ficewa shine","pin_required":"Kana buƙatar saita PIN da farko",
        "pin_wrong":"PIN ba daidai ba","pin_set":"PIN an saita cikin nasara!",
        "pin_4digits":"PIN dole ne ya zama lamba 4","profile_updated":"Profile an sabunta!",
        "bank_saved":"Bayanin banku an ajiye!","balance_adjusted":"Balance an gyara!",
        "user_banned":"User an hana shi","user_unbanned":"An sake bude account",
        "pin_reset":"PIN an share","message_sent":"Saƙo an aika!","task_created":"Aiki an ƙirƙira!",
        "task_deleted":"Aiki an goge!","submission_approved":"An amince! Kuɗi an ƙara.",
        "submission_rejected":"An ƙi buƙatar.","withdrawal_approved":"Ficewa an amince!",
        "withdrawal_rejected":"Ficewa an ƙi. Kuɗi an mayar.","transfer_reversed":"Transfer an mayar!",
        "broadcast":"Watsa Sanarwa","broadcast_sent":"Sanarwa an aika!","settings_saved":"Settings an ajiye!",
        "money_sent":"Kuɗi an aika cikin nasara!","exchanged":"An canza kuɗi!",
        "user_not_found":"User ba ya wanzu","cannot_send_self":"Ba za ka iya aika wa kanka ba",
        "admin_notice":"Sanarwa daga Admin","from_admin":"Daga Admin",
        "referral_bonus_earned":"Lada kira an samu!","withdrawal_request":"Buƙatar ficewa an aika!",
        "wrong_email_or_password":"Email ko password ba daidai ba",
        "account_banned":"An hana account dinku. Tuntuɓi support.",
        "email_exists":"Email din nan an riga an yi rajistar da shi","my_id":"ID na",
        "edit_profile":"Gyara Profile","old_password":"Tsohon Password","new_password":"Sabon Password",
        "total_earned":"Jimlar Samun","total_withdrawn":"Jimlar Ficewa",
        "referral_earned":"Lada Kira da Aka Samu","select_language":"Harshe",
        "forgot_password":"Manta Password",
        "bank_duplicate":"Wannan asusun banku yana da alaqa da wani mai amfani",
        "bank_contact_support":"Da fatan a tuntuɓi tallafi don canza bayanin banku",
        "transfer_disabled":"An kashe aika kudi a yanzu","transfer_min":"Mafi karancin aika shine",
        "transfer_max":"Mafi yawan aika shine","transfer_daily_limit":"An kai iyakar aika na yau",
        "too_many_attempts":"Yawan yunƙurin shiga. Gwada daga baya.",
        "new_message_alert":"Kuna da sako sabo. Da fatan ku duba.",
        "approve":"Amince","reject":"Ki","reverse":"Mayar","transfers_log":"Tarihin Aika","refunded":"an mayar",
    },
    "ar": {
        "app_name":"سوشيال باي","tagline":"اكسب المال عبر مهام وسائل التواصل الاجتماعي",
        "login":"تسجيل الدخول","register":"إنشاء حساب","email":"البريد الإلكتروني",
        "password":"كلمة المرور","full_name":"الاسم الكامل","confirm_password":"تأكيد كلمة المرور",
        "referral_code":"رمز الإحالة (اختياري)","create_account":"إنشاء الحساب",
        "login_now":"تسجيل الدخول الآن","welcome_back":"مرحباً بعودتك","total_balance":"إجمالي الرصيد",
        "tasks":"المهام","balance":"الرصيد","transfer":"تحويل","referrals":"الإحالات",
        "withdraw":"سحب","exchange":"تبادل","profile":"الملف الشخصي","history":"التاريخ",
        "notifications":"الإشعارات","logout":"تسجيل الخروج","available_tasks":"المهام المتاحة",
        "my_earnings":"أرباحي","completed_tasks":"المهام المكتملة","pending_tasks":"قيد الانتظار",
        "send_proof":"إرسال الدليل","proof_placeholder":"رابط، اسم مستخدم...",
        "submit":"إرسال للمراجعة","withdraw_money":"سحب الأموال","exchange_currency":"تبادل العملات",
        "send_money":"إرسال المال","receiver_id":"معرّف المستلم","amount":"المبلغ",
        "pin":"رمز PIN المكون من 4 أرقام","send_now":"إرسال الآن","cancel":"إلغاء","save":"حفظ",
        "set_pin":"تعيين PIN","change_pin":"تغيير PIN","bank_details":"تفاصيل البنك / الدفع",
        "bank_name":"اسم البنك","account_number":"رقم الحساب","account_name":"اسم صاحب الحساب",
        "payment_type":"نوع الدفع","referral_link":"رابط الإحالة الخاص بك","copy":"نسخ",
        "share_whatsapp":"واتساب","share_telegram":"تيليغرام","how_referral_works":"كيف تعمل الإحالات",
        "reward":"المكافأة","status":"الحالة","pending":"قيد الانتظار","approved":"مقبول","rejected":"مرفوض",
        "no_tasks":"لا توجد مهام متاحة","no_tasks_desc":"تحقق لاحقاً!","no_notifications":"لا توجد إشعارات",
        "fill_all_fields":"يرجى ملء جميع الحقول المطلوبة",
        "password_short":"يجب أن تكون كلمة المرور 8 أحرف على الأقل",
        "task_submitted":"تم إرسال المهمة! في انتظار مراجعة المسؤول.",
        "already_submitted":"لقد أرسلت هذه المهمة بالفعل","insufficient_balance":"رصيد غير كافٍ",
        "withdraw_min":"الحد الأدنى للسحب هو","pin_required":"تحتاج إلى تعيين PIN أولاً",
        "pin_wrong":"PIN خاطئ","pin_set":"تم تعيين PIN بنجاح!",
        "pin_4digits":"يجب أن يكون PIN مكوناً من 4 أرقام بالضبط",
        "profile_updated":"تم تحديث الملف الشخصي!","bank_saved":"تم حفظ تفاصيل البنك!",
        "balance_adjusted":"تم تعديل الرصيد!","user_banned":"تم حظر المستخدم",
        "user_unbanned":"تم رفع الحظر عن المستخدم","pin_reset":"تم إعادة تعيين PIN",
        "message_sent":"تم إرسال الرسالة!","task_created":"تم إنشاء المهمة!","task_deleted":"تم حذف المهمة!",
        "submission_approved":"تمت الموافقة! تم إضافة الدفع.","submission_rejected":"تم رفض الطلب.",
        "withdrawal_approved":"تمت الموافقة على السحب!","withdrawal_rejected":"تم رفض السحب.",
        "transfer_reversed":"تم عكس التحويل!","broadcast":"بث","broadcast_sent":"تم إرسال الرسالة الجماعية!",
        "settings_saved":"تم حفظ الإعدادات!","money_sent":"تم إرسال المال بنجاح!",
        "exchanged":"تم تبادل العملة!","user_not_found":"المستخدم غير موجود",
        "cannot_send_self":"لا يمكنك الإرسال لنفسك","admin_notice":"إشعار من الإدارة",
        "from_admin":"من الإدارة","referral_bonus_earned":"تم كسب مكافأة الإحالة!",
        "withdrawal_request":"تم تقديم طلب السحب!","wrong_email_or_password":"البريد الإلكتروني أو كلمة المرور خاطئة","approve":"موافقة","reject":"رفض","reverse":"عكس","transfers_log":"سجل التحويلات","refunded":"مُسترد",
        "account_banned":"تم حظر حسابك. تواصل مع الدعم.","email_exists":"هذا البريد الإلكتروني مسجل بالفعل",
        "my_id":"معرّف المستخدم","edit_profile":"تعديل الملف الشخصي",
        "old_password":"كلمة المرور الحالية","new_password":"كلمة مرور جديدة",
        "total_earned":"إجمالي الأرباح","total_withdrawn":"إجمالي المسحوب",
        "referral_earned":"مكافأة الإحالة المكتسبة","select_language":"اللغة",
        "forgot_password":"نسيت كلمة المرور",
        "bank_duplicate":"حساب البنك مرتبط بمستخدم آخر",
        "bank_contact_support":"تواصل مع الدعم لتغيير بيانات البنك",
        "transfer_disabled":"التحويلات معطّلة","transfer_min":"الحد الأدنى للتحويل",
        "transfer_max":"الحد الأقصى للتحويل","transfer_daily_limit":"تم الوصول لحد التحويل اليومي",
        "too_many_attempts":"محاولات كثيرة. حاول لاحقاً.",
        "new_message_alert":"لديك رسالة جديدة.",
        "approve":"موافقة","reject":"رفض","reverse":"عكس","transfers_log":"سجل التحويلات","refunded":"مُسترد",
    }
}

def t(key, lang=None):
    if lang is None:
        lang = session.get("lang", "en")
    # Fix #16: strict language separation
    # Arabic: only Arabic translations
    # Hausa: Hausa with English fallback (never Arabic)
    # English: only English
    lang_dict = TRANSLATIONS.get(lang, {})
    en_dict = TRANSLATIONS.get("en", {})
    if lang == "ar":
        return lang_dict.get(key, en_dict.get(key, key))
    elif lang == "ha":
        return lang_dict.get(key, en_dict.get(key, key))
    else:
        return en_dict.get(key, key)

app.jinja_env.globals["t"] = t
app.jinja_env.globals["session"] = session

# ============================================================
# UTILITIES
# ============================================================
def now_str(): return datetime.now().isoformat()
def short_id(): return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

# ── Password hashing (v6) ───────────────────────────────────────────────────
# New hashes use werkzeug pbkdf2:sha256.
# Existing v5 hashes (salt$hexdigest) are still verified so no forced reset.
def hash_pw(pw):
    """Hash password using werkzeug's secure pbkdf2:sha256."""
    return generate_password_hash(pw, method="pbkdf2:sha256:260000")

def verify_pw(pw, stored):
    """
    Verify password against stored hash.
    Supports both werkzeug format (new) and legacy salt$hex format (v5).
    """
    if not stored:
        return False
    try:
        if stored.startswith("pbkdf2:") or stored.startswith("scrypt:"):
            # werkzeug format
            return check_password_hash(stored, pw)
        # Legacy v5 format: salt$hexdigest
        parts = stored.split("$", 1)
        if len(parts) == 2:
            salt, sh = parts
            h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100000)
            return h.hex() == sh
        return False
    except Exception:
        return False

# ── CSRF helpers ────────────────────────────────────────────────────────────
def generate_csrf_token():
    """Generate and store a CSRF token in the session."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]

def validate_csrf():
    """
    Validate CSRF token on state-changing POST requests.
    Token can be sent as form field '_csrf_token' or header 'X-CSRF-Token'.
    JSON/AJAX requests that send the token via header are accepted.
    Returns True if valid, False otherwise.
    """
    expected = session.get("csrf_token")
    if not expected:
        return False
    received = (request.form.get("_csrf_token") or
                request.headers.get("X-CSRF-Token") or
                (request.json or {}).get("_csrf_token", "") if request.is_json else "")
    return secrets.compare_digest(expected, received) if received else False

# Expose generate_csrf_token to all templates
app.jinja_env.globals["csrf_token"] = generate_csrf_token

def get_app_name():
    """Get current app name from settings (falls back to APP_NAME constant)."""
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key='site_name'").fetchone()
    db.close()
    return row["value"] if row and row["value"] else APP_NAME

app.jinja_env.globals["get_app_name"] = get_app_name
app.jinja_env.filters["fromjson"] = json.loads

def get_settings():
    defaults = {
        "referral_bonus": "30", "referral_bonus_l2": "15",
        "referral_tasks_needed": "10", "withdrawal_fee_percent": "5",
        "min_withdrawal": "500", "max_withdrawal": "100000",
        "exchange_rate": "1500", "site_name": "SocialPay",
        "maintenance": "0", "announcement": "",
        "signup_reward_enabled": "1", "signup_reward_amount": "50",
        "daily_login_enabled": "1", "daily_login_reward": "10",
        "spin_enabled": "1", "spin_cost": "50",
        "spin_prizes": "10,50,100,200,500,1000",
        "spin_daily_limit": "0",
        "transfers_enabled": "1",
        "transfer_min": "0",
        "transfer_max": "1000000",
        "transfer_daily_limit": "0",
        "login_attempt_limit": "5",
        "telegram_support_username": "socialpaysupport",
        "streak_bonus_7": "100",
        "streak_bonus_14": "250",
        "streak_bonus_30": "500",
        "jackpot_enabled": "1",
        "jackpot_contribution_pct": "5",
        "jackpot_trigger_streak": "7",
        "dark_mode_enabled": "1",
        "onboarding_enabled": "1",
        "in_app_chat_enabled": "1",
        "withdrawal_auto_approve_threshold": "0",
        "rate_limit_spin": "10",
        "rate_limit_transfer": "20",
        "rate_limit_withdraw": "5",
    }
    db = get_db()
    rows = db.execute("SELECT key, value FROM settings").fetchall()
    db.close()
    for r in rows:
        defaults[r["key"]] = r["value"]
    # Parse types
    result = {}
    for k, v in defaults.items():
        try:
            if k in ["maintenance","signup_reward_enabled","daily_login_enabled","spin_enabled","transfers_enabled","jackpot_enabled","dark_mode_enabled","onboarding_enabled","in_app_chat_enabled"]:
                result[k] = bool(int(v))
            elif k == "spin_prizes":
                result[k] = [int(x.strip()) for x in str(v).split(",") if x.strip()]
            elif k in ["referral_bonus","referral_bonus_l2","withdrawal_fee_percent","min_withdrawal",
                       "max_withdrawal","exchange_rate","signup_reward_amount","daily_login_reward",
                       "transfer_min","transfer_max","streak_bonus_7","streak_bonus_14","streak_bonus_30",
                       "jackpot_contribution_pct","withdrawal_auto_approve_threshold"]:
                result[k] = float(v)
            elif k in ["referral_tasks_needed","spin_cost","spin_daily_limit","transfer_daily_limit","login_attempt_limit","jackpot_trigger_streak","rate_limit_spin","rate_limit_transfer","rate_limit_withdraw"]:
                result[k] = int(float(v))
            else:
                result[k] = v
        except:
            result[k] = v
    return result

def save_setting(key, value):
    db = get_db()
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))
    db.commit()
    db.close()

def add_notif(user_id, message, ntype="info", image=""):
    db = get_db()
    nid = f"N_{short_id()}"
    db.execute("INSERT INTO notifications(id,user_id,message,type,time,read) VALUES(?,?,?,?,?,0)",
               (nid, user_id, message, ntype, now_str()))
    # Keep only last 50
    db.execute("""DELETE FROM notifications WHERE user_id=? AND id NOT IN
                  (SELECT id FROM notifications WHERE user_id=? ORDER BY time DESC LIMIT 50)""",
               (user_id, user_id))
    db.commit()
    db.close()

def log_audit(action, uid, detail="", amount=0):
    db = get_db()
    lid = f"L_{short_id()}"
    db.execute("INSERT INTO audit_logs(id,action,user_id,detail,amount,time) VALUES(?,?,?,?,?,?)",
               (lid, action, uid, detail, amount, now_str()))
    db.commit()
    db.close()

def add_transaction(uid, txtype, amount, currency, description, ref_id=""):
    db = get_db()
    txid = f"TX_{short_id()}"
    db.execute("INSERT INTO transactions(id,user_id,type,amount,currency,description,ref_id,time,status) VALUES(?,?,?,?,?,?,?,?,?)",
               (txid, uid, txtype, amount, currency, description, ref_id, now_str(), "completed"))
    db.commit()
    db.close()

def get_wallet(uid):
    db = get_db()
    w = db.execute("SELECT * FROM wallets WHERE user_id=?", (uid,)).fetchone()
    if not w:
        db.execute("INSERT OR IGNORE INTO wallets(user_id,naira,dollar,completed_tasks,pending_tasks,referral_count,referral_count_l2,referral_bonus_earned,total_earned,total_withdrawn,created) VALUES(?,0,0,0,0,0,0,0,0,0,?)",
                   (uid, now_str()))
        db.commit()
        w = db.execute("SELECT * FROM wallets WHERE user_id=?", (uid,)).fetchone()
    db.close()
    return dict(w) if w else {}

def upd_wallet(uid, field, amount, absolute=False):
    db = get_db()
    if absolute:
        db.execute(f"UPDATE wallets SET {field}=? WHERE user_id=?", (amount, uid))
    else:
        db.execute(f"UPDATE wallets SET {field}=MAX(0,{field}+?) WHERE user_id=?", (amount, uid))
    if db.execute("SELECT changes()").fetchone()[0] == 0:
        get_wallet(uid)
        db.execute(f"UPDATE wallets SET {field}=MAX(0,{field}+?) WHERE user_id=?", (amount, uid))
    db.commit()
    db.close()

def get_spin_prizes(settings=None):
    if settings is None:
        settings = get_settings()
    prizes_amounts = settings.get("spin_prizes", [10, 50, 100, 200, 500, 1000])
    prob_map = {0: 50, 1: 30, 2: 10, 3: 5, 4: 3, 5: 2}
    pool = []
    for i, amt in enumerate(prizes_amounts):
        prob = prob_map.get(i, 1)
        pool.append({"label": f"₦{amt:,}", "amount": amt, "prob": prob})
    pool.append({"label": "Try Again", "amount": 0, "prob": 2})
    return pool

# ── v9: Analytics helper ────────────────────────────────────
def record_analytics(field, amount=1):
    """Increment a daily analytics counter."""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        db = get_db()
        db.execute(f"""INSERT INTO analytics_daily(date,{field}) VALUES(?,?)
                       ON CONFLICT(date) DO UPDATE SET {field}={field}+excluded.{field}""",
                   (today, amount))
        db.commit()
        db.close()
    except: pass

# ── v9: Achievement helper ───────────────────────────────────
BADGES = {
    "first_task":    {"label":"🏅 First Task",        "desc":"Completed your first task"},
    "tasks_10":      {"label":"⭐ Rising Star",        "desc":"Completed 10 tasks"},
    "tasks_50":      {"label":"🌟 Pro Earner",         "desc":"Completed 50 tasks"},
    "tasks_100":     {"label":"💎 Diamond Earner",     "desc":"Completed 100 tasks"},
    "referral_5":    {"label":"👥 Connector",          "desc":"Referred 5 friends"},
    "referral_20":   {"label":"🔗 Network Builder",    "desc":"Referred 20 friends"},
    "streak_7":      {"label":"🔥 Week Warrior",       "desc":"7-day login streak"},
    "streak_30":     {"label":"🚀 Monthly Champion",   "desc":"30-day login streak"},
    "withdraw_1":    {"label":"💸 First Withdrawal",   "desc":"Made your first withdrawal"},
    "earner_1000":   {"label":"💰 ₦1K Club",           "desc":"Earned over ₦1,000"},
    "earner_10000":  {"label":"🏆 ₦10K Club",          "desc":"Earned over ₦10,000"},
    "earner_100000": {"label":"👑 ₦100K Club",         "desc":"Earned over ₦100,000"},
}

def award_badge(uid, badge_key):
    """Award a badge if not already earned."""
    try:
        db = get_db()
        exists = db.execute("SELECT 1 FROM achievements WHERE user_id=? AND badge=?", (uid, badge_key)).fetchone()
        if not exists:
            db.execute("INSERT INTO achievements(user_id,badge,earned_at) VALUES(?,?,?)",
                       (uid, badge_key, now_str()))
            db.commit()
            badge = BADGES.get(badge_key, {})
            db.close()
            add_notif(uid, f"🎖️ New Badge: {badge.get('label',badge_key)} — {badge.get('desc','')}", "success")
            return True
        db.close()
    except: pass
    return False

def check_achievements(uid):
    """Check and award all applicable badges for a user."""
    try:
        wallet = get_wallet(uid)
        completed = wallet.get("completed_tasks", 0)
        refs = wallet.get("referral_count", 0) + wallet.get("referral_count_l2", 0)
        earned = wallet.get("total_earned", 0)
        if completed >= 1:   award_badge(uid, "first_task")
        if completed >= 10:  award_badge(uid, "tasks_10")
        if completed >= 50:  award_badge(uid, "tasks_50")
        if completed >= 100: award_badge(uid, "tasks_100")
        if refs >= 5:        award_badge(uid, "referral_5")
        if refs >= 20:       award_badge(uid, "referral_20")
        if earned >= 1000:   award_badge(uid, "earner_1000")
        if earned >= 10000:  award_badge(uid, "earner_10000")
        if earned >= 100000: award_badge(uid, "earner_100000")
        # Withdrawal badge
        db = get_db()
        has_wd = db.execute("SELECT 1 FROM withdrawals WHERE user_id=? AND status='approved'", (uid,)).fetchone()
        db.close()
        if has_wd: award_badge(uid, "withdraw_1")
    except: pass

# ── v9: Streak bonus helper ──────────────────────────────────
def check_streak_bonus(uid):
    """Award bonus for 7/14/30 day streaks."""
    try:
        settings = get_settings()
        db = get_db()
        dl = db.execute("SELECT * FROM daily_logins WHERE user_id=?", (uid,)).fetchone()
        streak_row = db.execute("SELECT * FROM streak_bonuses WHERE user_id=?", (uid,)).fetchone()
        db.close()
        if not dl: return
        days = dl["total_days"]
        today = datetime.now().strftime("%Y-%m-%d")
        last = streak_row["last_claimed_date"] if streak_row else ""
        if last == today: return
        bonus = 0
        badge = None
        if days % 30 == 0 and days >= 30:
            bonus = float(settings.get("streak_bonus_30", 500))
            badge = "streak_30"
        elif days % 14 == 0 and days >= 14:
            bonus = float(settings.get("streak_bonus_14", 250))
            badge = None
        elif days % 7 == 0 and days >= 7:
            bonus = float(settings.get("streak_bonus_7", 100))
            badge = "streak_7"
        if bonus > 0:
            upd_wallet(uid, "naira", bonus)
            upd_wallet(uid, "total_earned", bonus)
            add_transaction(uid, "credit", bonus, "naira", f"Streak bonus — Day {days}")
            add_notif(uid, f"🔥 Streak Bonus! {days}-day streak → +₦{bonus:,.0f}", "success")
            if badge: award_badge(uid, badge)
            db2 = get_db()
            db2.execute("INSERT OR REPLACE INTO streak_bonuses(user_id,current_streak,last_claimed_date,total_bonus_earned) VALUES(?,?,?,COALESCE((SELECT total_bonus_earned FROM streak_bonuses WHERE user_id=?),0)+?)",
                        (uid, days, today, uid, bonus))
            db2.commit(); db2.close()
        record_analytics("new_users", 0)  # keep table alive
    except: pass

# ── v9: IP blacklist check ───────────────────────────────────
def is_ip_blacklisted():
    try:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        db = get_db()
        row = db.execute("SELECT 1 FROM ip_blacklist WHERE ip=?", (ip,)).fetchone()
        db.close()
        return row is not None
    except: return False

# ── v9: Simple rate limiter (in-memory) ─────────────────────



_rate_store = {}
def rate_limited(key, limit, window=60):
    """Returns True if over limit."""
    now = _time_module.time()
    entries = _rate_store.get(key, [])
    entries = [t for t in entries if now - t < window]
    entries.append(now)
    _rate_store[key] = entries
    return len(entries) > limit

# ── v8: Login attempt helpers ────────────────────────────────
def check_login_attempts(email, limit):
    if limit <= 0: return True
    db = get_db()
    row = db.execute("SELECT * FROM login_attempts WHERE email=?", (email,)).fetchone()
    db.close()
    if not row: return True
    if row["locked_until"]:
        try:
            if datetime.now() < datetime.fromisoformat(row["locked_until"]):
                return False
        except: pass
    return row["count"] < limit

def record_failed_attempt(email, limit):
    db = get_db()
    row = db.execute("SELECT * FROM login_attempts WHERE email=?", (email,)).fetchone()
    now = datetime.now()
    if row:
        new_count = row["count"] + 1
        locked = (now + timedelta(minutes=15)).isoformat() if limit > 0 and new_count >= limit else None
        db.execute("INSERT OR REPLACE INTO login_attempts(email,count,locked_until) VALUES(?,?,?)", (email, new_count, locked))
    else:
        db.execute("INSERT INTO login_attempts(email,count,locked_until) VALUES(?,1,NULL)", (email,))
    db.commit()
    db.close()

def clear_login_attempts(email):
    db = get_db()
    db.execute("DELETE FROM login_attempts WHERE email=?", (email,))
    db.commit()
    db.close()

# ── v8: User tracking ────────────────────────────────────────
import json as _json
def track_user(uid):
    try:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        ua = request.headers.get("User-Agent", "")
        country, city = "", ""
        try:
            import urllib.request as _ureq
            with _ureq.urlopen(f"http://ip-api.com/json/{ip}?fields=country,city", timeout=2) as resp:
                geo = json.loads(resp.read().decode())
                country = geo.get("country", "")
                city = geo.get("city", "")
        except: pass
        db = get_db()
        db.execute("INSERT INTO user_tracking(user_id,ip_address,country,city,device_info,time) VALUES(?,?,?,?,?,?)",
                   (uid, ip, country, city, ua[:300], now_str()))
        db.commit()
        db.close()
    except: pass

def get_unread_admin_messages(uid):
    try:
        db = get_db()
        c = db.execute("SELECT COUNT(*) as c FROM admin_messages WHERE user_id=? AND read=0", (uid,)).fetchone()
        db.close()
        return c["c"] if c else 0
    except: return 0

app.jinja_env.globals["get_unread_admin_messages"] = get_unread_admin_messages


# ============================================================
# PUSH NOTIFICATIONS (Web Push / VAPID)
# ============================================================
def get_or_create_vapid_keys():
    """Generate or retrieve VAPID key pair from DB."""
    db = get_db()
    row = db.execute("SELECT * FROM vapid_keys WHERE id=1").fetchone()
    db.close()
    if row:
        return row["private_key"], row["public_key"]
    # Generate new keys
    try:
        from py_vapid import Vapid
        vapid = Vapid()
        vapid.generate_keys()
        priv = vapid.private_pem().decode() if hasattr(vapid.private_pem(), 'decode') else vapid.private_pem()
        pub = vapid.public_key.get_encoded(compressed=False)
        import base64
        pub_b64 = base64.urlsafe_b64encode(pub).rstrip(b'=').decode()
        db2 = get_db()
        db2.execute("INSERT OR REPLACE INTO vapid_keys(id,private_key,public_key,created) VALUES(1,?,?,?)",
                    (priv, pub_b64, now_str()))
        db2.commit(); db2.close()
        return priv, pub_b64
    except Exception as e:
        # Fallback: use env or generate random placeholder
        priv = os.environ.get("VAPID_PRIVATE_KEY", "")
        pub = os.environ.get("VAPID_PUBLIC_KEY", "")
        return priv, pub

def send_push_notification(user_id, title, body, url="/dashboard"):
    """Send Web Push notification to all subscriptions of a user."""
    try:
        from pywebpush import webpush, WebPushException
        import json as _j
        priv_key, pub_key = get_or_create_vapid_keys()
        if not priv_key:
            return False
        db = get_db()
        subs = db.execute("SELECT * FROM push_subscriptions WHERE user_id=?", (user_id,)).fetchall()
        db.close()
        payload = _j.dumps({"title": title, "body": body, "url": url})
        failed_endpoints = []
        for sub in subs:
            try:
                subscription_info = {
                    "endpoint": sub["endpoint"],
                    "keys": {
                        "p256dh": sub["p256dh"],
                        "auth": sub["auth"]
                    }
                }
                webpush(
                    subscription_info=subscription_info,
                    data=payload,
                    vapid_private_key=priv_key,
                    vapid_claims={"sub": f"mailto:{ADMIN_EMAIL}"}
                )
            except WebPushException as ex:
                if ex.response and ex.response.status_code in [404, 410]:
                    failed_endpoints.append(sub["endpoint"])
            except Exception:
                pass
        # Remove dead subscriptions
        if failed_endpoints:
            db3 = get_db()
            for ep in failed_endpoints:
                db3.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (ep,))
            db3.commit(); db3.close()
        return True
    except ImportError:
        return False  # pywebpush not installed
    except Exception:
        return False

def broadcast_push_to_all(title, body, url="/dashboard"):
    """Send push notifications to all users with subscriptions."""
    try:
        db = get_db()
        user_ids = [r["user_id"] for r in db.execute("SELECT DISTINCT user_id FROM push_subscriptions").fetchall()]
        db.close()
        for uid in user_ids:
            try:
                send_push_notification(uid, title, body, url)
            except Exception:
                pass
    except Exception:
        pass

# ============================================================
# AUTH DECORATORS
# ============================================================
def login_required(f):
    @wraps(f)
    def deco(*args, **kwargs):
        if "user_id" not in session:
            # Return JSON for AJAX/fetch requests, redirect for normal page loads
            if request.method == "POST" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "message": "Session expired. Please log in again.", "redirect": url_for("login")}), 401
            return redirect(url_for("login"))
        # Check banned
        db = get_db()
        u = db.execute("SELECT banned, is_admin FROM users WHERE id=?", (session["user_id"],)).fetchone()
        db.close()
        if u and u["banned"] and not u["is_admin"]:
            if request.method == "POST":
                return jsonify({"success": False, "message": "Your account has been banned."}), 403
            return render_template("banned.html", lang=session.get("lang","en"))
        # Check maintenance (skip for admin)
        if u and not u["is_admin"]:
            s = get_settings()
            if s.get("maintenance"):
                if request.method == "POST":
                    return jsonify({"success": False, "message": "App is under maintenance. Please try again later."}), 503
                return render_template("maintenance.html", lang=session.get("lang","en"))
        return f(*args, **kwargs)
    return deco

def admin_required(f):
    @wraps(f)
    def deco(*args, **kwargs):
        if "user_id" not in session: return redirect(url_for("login"))
        db = get_db()
        u = db.execute("SELECT is_admin FROM users WHERE id=?", (session["user_id"],)).fetchone()
        db.close()
        if not u or not u["is_admin"]:
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return deco

# ============================================================
# ENSURE ADMIN
# ============================================================
def ensure_admin():
    db = get_db()
    admin = db.execute("SELECT id FROM users WHERE email=? AND is_admin=1",
                       (ADMIN_EMAIL.lower(),)).fetchone()
    if not admin:
        aid = "SP00000001"
        pw_hash = hash_pw(ADMIN_PASSWORD)
        db.execute("""INSERT OR IGNORE INTO users(id,name,email,password,is_admin,role,banned,verified,created,last_login,referral_code,referred_by,lang,signup_reward_given)
                      VALUES(?,?,?,?,1,'super_admin',0,1,?,?,?,NULL,'en',1)""",
                   (aid, ADMIN_NAME, ADMIN_EMAIL.lower(), pw_hash, now_str(), now_str(), aid))
        db.execute("INSERT OR IGNORE INTO wallets(user_id,created) VALUES(?,?)", (aid, now_str()))
        db.commit()
        print(f"[SETUP] Admin created: {ADMIN_EMAIL}")
    db.close()

@app.before_request
def keep_session_alive():
    session.permanent = True
    session.modified = True
    # Auto-generate CSRF token for every session
    generate_csrf_token()

# ============================================================
# ROUTES
# ============================================================
@app.route("/set_lang/<lang>")
def set_lang(lang):
    if lang in ["en", "ar", "ha"]:
        session["lang"] = lang
        if "user_id" in session:
            db = get_db()
            db.execute("UPDATE users SET lang=? WHERE id=?", (lang, session["user_id"]))
            db.commit()
            db.close()
    return redirect(request.referrer or url_for("index"))

@app.route("/r/<refcode>")
def referral_url(refcode):
    return redirect(url_for("register") + f"?ref={refcode}")

@app.route("/")
def index():
    if "user_id" in session:
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("dashboard"))
    # On mobile browser (not already installed as PWA), show install/download page
    ua = request.headers.get("User-Agent", "")
    is_mobile = any(x in ua for x in ["Android", "iPhone", "iPad", "iPod", "Mobile"])
    # If PWA display-mode is standalone it goes to /dashboard directly via JS in download.html
    if is_mobile:
        return redirect(url_for("download_app"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        lang = session.get("lang", "en")
        if not email or not password:
            return jsonify({"success": False, "message": t("fill_all_fields", lang)})
        db = get_db()
        u = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        db.close()
        settings_l = get_settings()
        limit = settings_l.get("login_attempt_limit", 5)
        if is_ip_blacklisted():
            return jsonify({"success": False, "message": t("account_banned", lang)})
        if not check_login_attempts(email, limit):
            return jsonify({"success": False, "message": t("too_many_attempts", lang)})
        if not u:
            record_failed_attempt(email, limit)
            return jsonify({"success": False, "message": t("wrong_email_or_password", lang)})
        if not verify_pw(password, u["password"]):
            record_failed_attempt(email, limit)
            return jsonify({"success": False, "message": t("wrong_email_or_password", lang)})
        if u["banned"]:
            return jsonify({"success": False, "message": t("account_banned", lang)})
        clear_login_attempts(email)
        session.permanent = True
        lang = u["lang"] or "en"
        session["lang"] = lang
        session["user_id"] = u["id"]
        session["user_name"] = u["name"]
        session["is_admin"] = bool(u["is_admin"])
        session["role"] = u["role"]
        db = get_db()
        db.execute("UPDATE users SET last_login=? WHERE id=?", (now_str(), u["id"]))
        db.commit()
        db.close()
        log_audit("login", u["id"])
        _check_daily_login(u["id"])
        track_user(u["id"])
        record_analytics("new_users", 0)  # keep record alive
        redir = url_for("admin_dashboard") if u["is_admin"] else url_for("dashboard")
        return jsonify({"success": True, "redirect": redir})
    lang = session.get("lang", "en")
    return render_template("login.html", lang=lang)

def _check_daily_login(uid):
    """Mark user as eligible for daily login reward (does NOT auto-credit)."""
    settings = get_settings()
    if not settings.get("daily_login_enabled"): return
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    dl = db.execute("SELECT * FROM daily_logins WHERE user_id=?", (uid,)).fetchone()
    # Skip if already fully claimed today OR already marked pending today
    if dl and (dl["last_date"] == today or dl["last_date"] == f"PENDING_{today}"):
        db.close(); return
    # Mark as eligible but don't credit yet - user must manually claim
    total_days = (dl["total_days"] + 1) if dl else 1
    db.execute("INSERT OR REPLACE INTO daily_logins(user_id,last_date,total_days) VALUES(?,?,?)",
               (uid, f"PENDING_{today}", total_days))
    db.commit()
    db.close()

@app.route("/claim_daily", methods=["POST"])
@login_required
def claim_daily():
    uid = session["user_id"]
    lang = session.get("lang","en")
    settings = get_settings()
    if not settings.get("daily_login_enabled"):
        return jsonify({"success": False, "message": "Daily reward is disabled."})
    today = datetime.now().strftime("%Y-%m-%d")
    db = get_db()
    dl = db.execute("SELECT * FROM daily_logins WHERE user_id=?", (uid,)).fetchone()
    db.close()
    if not dl or dl["last_date"] != f"PENDING_{today}":
        return jsonify({"success": False, "message": "No reward to claim today, or already claimed."})
    reward = float(settings.get("daily_login_reward", 10))
    total_days = dl["total_days"]
    db = get_db()
    db.execute("UPDATE daily_logins SET last_date=? WHERE user_id=?", (today, uid))
    db.commit(); db.close()
    upd_wallet(uid, "naira", reward)
    upd_wallet(uid, "total_earned", reward)
    add_transaction(uid, "credit", reward, "naira", f"Daily login reward Day {total_days}")
    add_notif(uid, f"🎁 Daily login reward claimed: +₦{reward:.0f}", "success")
    check_streak_bonus(uid)
    award_badge(uid, "streak_7") if total_days >= 7 else None
    award_badge(uid, "streak_30") if total_days >= 30 else None
    return jsonify({"success": True, "message": f"🎁 +₦{reward:.0f} Daily Reward Claimed!", "reward": reward})

@app.route("/register", methods=["GET", "POST"])
def register():
    lang = session.get("lang", "en")
    if "user_id" in session:
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard")) if request.method=="GET" else jsonify({"success":False,"message":"Already logged in"})
        return redirect(url_for("dashboard")) if request.method=="GET" else jsonify({"success":False,"message":"Already logged in"})
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        name = request.form.get("name","").strip()[:100]
        ref_code = request.form.get("ref","").strip()
        if not email or not password or not name:
            return jsonify({"success":False,"message":t("fill_all_fields",lang)})
        if len(password) < 8:
            return jsonify({"success":False,"message":t("password_short",lang)})
        if "@" not in email:
            return jsonify({"success":False,"message":t("fill_all_fields",lang)})
        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            db.close()
            return jsonify({"success":False,"message":t("email_exists",lang)})
        uid = f"SP{short_id()}"
        db.execute("""INSERT INTO users(id,name,email,password,is_admin,role,banned,verified,created,last_login,referral_code,referred_by,lang,signup_reward_given)
                      VALUES(?,?,?,?,0,'user',0,1,?,?,?,NULL,?,0)""",
                   (uid, name, email, hash_pw(password), now_str(), now_str(), uid, lang))
        db.execute("INSERT INTO wallets(user_id,created) VALUES(?,?)", (uid, now_str()))
        # Multi-level referrals
        if ref_code and ref_code != uid:
            referrer = db.execute("SELECT id,referred_by FROM users WHERE referral_code=? OR id=?",
                                  (ref_code, ref_code)).fetchone()
            if referrer:
                ref_uid = referrer["id"]
                db.execute("UPDATE users SET referred_by=? WHERE id=?", (ref_uid, uid))
                db.execute("INSERT INTO referrals(referrer_id,referred_id,level,time,bonus_paid,tasks_done) VALUES(?,?,1,?,0,0)",
                           (ref_uid, uid, now_str()))
                db.execute("UPDATE wallets SET referral_count=referral_count+1 WHERE user_id=?", (ref_uid,))
                # L2
                l2_id = referrer["referred_by"]
                if l2_id:
                    db.execute("INSERT INTO referrals(referrer_id,referred_id,level,time,bonus_paid,tasks_done) VALUES(?,?,2,?,0,0)",
                               (l2_id, uid, now_str()))
                    db.execute("UPDATE wallets SET referral_count_l2=referral_count_l2+1 WHERE user_id=?", (l2_id,))
        db.commit()
        db.close()
        # Sign-up reward
        settings = get_settings()
        if settings.get("signup_reward_enabled"):
            reward = float(settings.get("signup_reward_amount", 50))
            upd_wallet(uid, "naira", reward)
            upd_wallet(uid, "total_earned", reward)
            add_transaction(uid, "credit", reward, "naira", "Sign-up welcome bonus")
            add_notif(uid, f"🎉 Welcome bonus: +₦{reward:.0f}", "success")
        session.permanent = True
        session["user_id"] = uid; session["user_name"] = name
        session["is_admin"] = False; session["role"] = "user"
        add_notif(uid, f"🎉 Welcome to {APP_NAME}! Start earning today.", "success")
        log_audit("register", uid)
        track_user(uid)
        record_analytics("new_users")
        return jsonify({"success":True,"redirect":url_for("dashboard"),"message":f"Account created for {name}"})
    return render_template("login.html", lang=lang, tab="register")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    uid = session["user_id"]
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if user and user["is_admin"]:
        db.close()
        return redirect(url_for("admin_dashboard"))
    wallet = get_wallet(uid)
    unread = db.execute("SELECT COUNT(*) as c FROM notifications WHERE user_id=? AND read=0", (uid,)).fetchone()["c"]
    try:
        unread_msgs = db.execute("SELECT COUNT(*) as c FROM admin_messages WHERE user_id=? AND read=0", (uid,)).fetchone()["c"]
    except:
        unread_msgs = 0
    bank_dash = db.execute("SELECT * FROM bank_details WHERE user_id=?", (uid,)).fetchone()
    goal_row = None
    try:
        goal_row = db.execute("SELECT * FROM goals WHERE user_id=?", (uid,)).fetchone()
    except: pass
    pending_wd = db.execute("SELECT COUNT(*) as c FROM withdrawals WHERE user_id=? AND status='pending'", (uid,)).fetchone()["c"]
    dl = db.execute("SELECT * FROM daily_logins WHERE user_id=?", (uid,)).fetchone()
    today = datetime.now().strftime("%Y-%m-%d")
    # daily_claimed = fully claimed today; daily_eligible = pending claim available
    daily_claimed = dl and dl["last_date"] == today
    daily_eligible = dl and dl["last_date"] == f"PENDING_{today}"
    daily_days = dl["total_days"] if dl else 0
    # Top earners for display (masked names)
    top_earners = db.execute("""SELECT u.name, w.total_earned FROM wallets w
                                JOIN users u ON w.user_id=u.id
                                WHERE u.is_admin=0 AND w.total_earned>0
                                ORDER BY w.total_earned DESC LIMIT 10""").fetchall()
    db.close()
    settings = get_settings()
    spin_cost = int(settings.get("spin_cost", 50))
    SPIN_PRIZES = get_spin_prizes(settings)
    spin_prizes_js = [{"label": p["label"], "amount": p["amount"]} for p in SPIN_PRIZES]
    lang = session.get("lang", "en")
    app_name = get_app_name()
    # Mask names: show first 3 chars + ***
    def mask_name(n):
        return (n[:3] + "***") if len(n) > 3 else (n[0] + "**")
    earners = [{"name": mask_name(r["name"]), "earned": r["total_earned"]} for r in top_earners]
    return render_template("dashboard.html", user=dict(user), wallet=wallet,
                            unread=unread, unread_msgs=unread_msgs, pending_wd=pending_wd,
                            announcement=settings.get("announcement",""), lang=lang,
                            bank=dict(bank_dash) if bank_dash else {},
                            daily_claimed=daily_claimed, daily_eligible=daily_eligible,
                            daily_days=daily_days,
                            settings=settings, spin_cost=spin_cost, spin_prizes_js=spin_prizes_js,
                            tg_channel=TG_CHANNEL, tg_group=TG_GROUP, tg_support=TG_SUPPORT,
                            app_name=app_name, earners=earners,
                            goal=dict(goal_row) if goal_row else None)

@app.route("/tasks")
@login_required
def tasks_page():
    uid = session["user_id"]
    db = get_db()
    now = now_str()
    rows = db.execute("""SELECT t.*, (SELECT COUNT(*) FROM task_completions WHERE task_id=t.id) as completed_count2
                         FROM tasks t WHERE t.status='active' AND (t.expires_at IS NULL OR t.expires_at > ?)
                         AND t.id NOT IN (SELECT task_id FROM submissions WHERE user_id=? AND status!='rejected')
                         AND (t.max_users > (SELECT COUNT(*) FROM task_completions WHERE task_id=t.id))""",
                      (now, uid)).fetchall()
    db.close()
    available = []
    now_dt = datetime.now()
    for r in rows:
        tc = dict(r)
        if tc.get("expires_at"):
            delta = datetime.fromisoformat(tc["expires_at"]) - now_dt
            tc["time_left"] = int(delta.total_seconds())
            tc["completed_by"] = []
        else:
            tc["time_left"] = None
            tc["completed_by"] = []
        available.append(tc)
    lang = session.get("lang","en")
    return render_template("tasks.html", tasks=available, lang=lang)

@app.route("/upload_screenshot", methods=["POST"])
@login_required
def upload_screenshot():
    """Handle screenshot upload with auto compression."""
    import base64, io
    try:
        data = request.get_json(force=True) or {}
        img_data = data.get("image","")
        if not img_data:
            return jsonify({"success": False, "message": "No image provided"})
        # Strip data URI prefix
        if "," in img_data:
            header, b64 = img_data.split(",", 1)
        else:
            b64 = img_data
        raw = base64.b64decode(b64)
        # Try PIL compression
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(raw))
            # Convert to RGB if needed
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            # Resize if too large (max 1200px wide)
            if img.width > 1200:
                ratio = 1200 / img.width
                new_h = int(img.height * ratio)
                img = img.resize((1200, new_h), Image.LANCZOS)
            # Save compressed
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75, optimize=True)
            compressed = buf.getvalue()
            # Only use compressed if it's smaller
            if len(compressed) < len(raw):
                raw = compressed
                b64 = base64.b64encode(raw).decode()
                img_data = "data:image/jpeg;base64," + b64
        except Exception:
            pass  # PIL not available or error — use original
        # Check final size (max 2MB as data URI)
        if len(img_data) > 2 * 1024 * 1024:
            return jsonify({"success": False, "message": "Image too large even after compression. Please use a smaller screenshot."})
        return jsonify({"success": True, "image": img_data})
    except Exception as e:
        return jsonify({"success": False, "message": f"Upload error: {str(e)}"})

@app.route("/submit_task", methods=["POST"])
@login_required
def submit_task():
    uid = session["user_id"]
    task_id = request.form.get("task_id")
    proof = request.form.get("proof","").strip()
    lang = session.get("lang","en")
    screenshot = request.form.get("screenshot","")
    # Fix #7: only screenshot is valid proof (text proof removed)
    if not task_id or not screenshot:
        return jsonify({"success":False,"message":"Please upload a screenshot as proof."})
    proof = proof or "Screenshot submitted"
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        db.close()
        return jsonify({"success":False,"message":"Task not found"})
    existing = db.execute("SELECT id FROM submissions WHERE user_id=? AND task_id=? AND status!='rejected'",
                          (uid, task_id)).fetchone()
    if existing:
        db.close()
        return jsonify({"success":False,"message":t("already_submitted",lang)})
    # Fix #15: if max_users==1, only one user can complete it; others blocked unless first is rejected
    if task["max_users"] == 1:
        approved_or_pending = db.execute(
            "SELECT id FROM submissions WHERE task_id=? AND status IN ('pending','approved')", (task_id,)
        ).fetchone()
        if approved_or_pending:
            db.close()
            return jsonify({"success":False,"message":"This task is already taken. You can submit only if the first submission is rejected."})
    sid = f"SUB_{short_id()}"
    ss = screenshot if (screenshot and len(screenshot) <= 2*1024*1024) else ""
    if task["auto_approve"]:
        db.execute("""INSERT INTO submissions(id,user_id,task_id,proof,screenshot,status,reward,currency,submitted_at,reviewed_at,note)
                      VALUES(?,?,?,?,?,'approved',?,?,?,?,?)""",
                   (sid, uid, task_id, proof[:1000], ss, task["reward"], task["currency"], now_str(), now_str(), "Auto approved"))
        db.execute("INSERT OR IGNORE INTO task_completions(task_id,user_id) VALUES(?,?)", (task_id, uid))
        db.execute("UPDATE tasks SET completed_count=completed_count+1 WHERE id=?", (task_id,))
        db.commit()
        db.close()
        upd_wallet(uid, task["currency"], task["reward"])
        upd_wallet(uid, "completed_tasks", 1)
        upd_wallet(uid, "total_earned", task["reward"])
        add_transaction(uid, "credit", task["reward"], task["currency"], f"Task auto-approved: {task['title']}", sid)
        _check_referral_bonus(uid, lang)
        sym = "₦" if task["currency"]=="naira" else "$"
        add_notif(uid, f"✅ Auto approved! +{sym}{task['reward']:,.0f}", "success")
        check_achievements(uid)
        record_analytics("tasks_approved")
        record_analytics("total_earned", task["reward"])
        db2 = get_db()
        db2.execute("UPDATE submissions SET screenshot='' WHERE id=?", (sid,))
        db2.commit()
        db2.close()
        return jsonify({"success":True,"message":f"Task approved! +{sym}{task['reward']:,.0f}"})
    db.execute("""INSERT INTO submissions(id,user_id,task_id,proof,screenshot,status,reward,currency,submitted_at,reviewed_at,note)
                  VALUES(?,?,?,?,?,'pending',?,?,?,NULL,'')""",
               (sid, uid, task_id, proof[:1000], ss, task["reward"], task["currency"], now_str()))
    db.commit()
    db.close()
    upd_wallet(uid, "pending_tasks", 1)
    add_notif(uid, f"✅ {t('task_submitted',lang)}", "info")
    log_audit("task_submitted", uid, task_id, task["reward"])
    return jsonify({"success":True,"message":t("task_submitted",lang)})

def _check_referral_bonus(uid, lang="en"):
    settings = get_settings()
    db = get_db()
    user = db.execute("SELECT referred_by FROM users WHERE id=?", (uid,)).fetchone()
    if not user or not user["referred_by"]:
        db.close(); return
    ref_by = user["referred_by"]
    ref_rec = db.execute("SELECT * FROM referrals WHERE referrer_id=? AND referred_id=? AND level=1 AND bonus_paid=0",
                         (ref_by, uid)).fetchone()
    if ref_rec:
        new_done = ref_rec["tasks_done"] + 1
        db.execute("UPDATE referrals SET tasks_done=? WHERE id=?", (new_done, ref_rec["id"]))
        if new_done >= settings["referral_tasks_needed"]:
            db.execute("UPDATE referrals SET bonus_paid=1 WHERE id=?", (ref_rec["id"],))
            bonus = float(settings["referral_bonus"])
            db.commit()
            db.close()
            upd_wallet(ref_by, "naira", bonus)
            upd_wallet(ref_by, "referral_bonus_earned", bonus)
            upd_wallet(ref_by, "total_earned", bonus)
            add_transaction(ref_by, "credit", bonus, "naira", "L1 referral bonus")
            add_notif(ref_by, f"🎁 L1 Referral bonus! +₦{bonus:.0f}", "success")
        else:
            db.commit()
            db.close()
    else:
        db.close()
    # L2
    db2 = get_db()
    ref_by_user = db2.execute("SELECT referred_by FROM users WHERE id=?", (ref_by,)).fetchone()
    if ref_by_user and ref_by_user["referred_by"]:
        l2_id = ref_by_user["referred_by"]
        ref_rec2 = db2.execute("SELECT * FROM referrals WHERE referrer_id=? AND referred_id=? AND level=2 AND bonus_paid=0",
                               (l2_id, uid)).fetchone()
        if ref_rec2:
            new_done2 = ref_rec2["tasks_done"] + 1
            db2.execute("UPDATE referrals SET tasks_done=? WHERE id=?", (new_done2, ref_rec2["id"]))
            if new_done2 >= settings["referral_tasks_needed"]:
                db2.execute("UPDATE referrals SET bonus_paid=1 WHERE id=?", (ref_rec2["id"],))
                bonus_l2 = float(settings.get("referral_bonus_l2", 15))
                db2.commit()
                db2.close()
                upd_wallet(l2_id, "naira", bonus_l2)
                upd_wallet(l2_id, "referral_bonus_earned", bonus_l2)
                upd_wallet(l2_id, "total_earned", bonus_l2)
                add_transaction(l2_id, "credit", bonus_l2, "naira", "L2 referral bonus")
                add_notif(l2_id, f"🎁 L2 Referral bonus! +₦{bonus_l2:.0f}", "success")
            else:
                db2.commit()
                db2.close()
        else:
            db2.close()
    else:
        db2.close()

@app.route("/balance")
@login_required
def balance_page():
    uid = session["user_id"]
    wallet = get_wallet(uid)
    db = get_db()
    tx_type = request.args.get("tx_type","")
    tx_date = request.args.get("tx_date","")
    tx_query = "SELECT * FROM transactions WHERE user_id=?"
    tx_params = [uid]
    if tx_type:
        tx_query += " AND type=?"
        tx_params.append(tx_type)
    if tx_date:
        tx_query += " AND time LIKE ?"
        tx_params.append(f"{tx_date}%")
    tx_query += " ORDER BY time DESC LIMIT 100"
    withdrawals = db.execute("SELECT * FROM withdrawals WHERE user_id=? ORDER BY requested_at DESC LIMIT 20", (uid,)).fetchall()
    transfers_sent = db.execute("SELECT t.*,u.name as rname FROM transfers t LEFT JOIN users u ON t.receiver_id=u.id WHERE t.sender_id=? ORDER BY t.time DESC LIMIT 10", (uid,)).fetchall()
    transfers_recv = db.execute("SELECT t.*,u.name as sname FROM transfers t LEFT JOIN users u ON t.sender_id=u.id WHERE t.receiver_id=? ORDER BY t.time DESC LIMIT 10", (uid,)).fetchall()
    transactions = db.execute(tx_query, tx_params).fetchall()
    db.close()
    settings = get_settings()
    lang = session.get("lang","en")
    return render_template("balance.html", wallet=wallet,
                            withdrawals=[dict(r) for r in withdrawals],
                            transfers_sent=[dict(r) for r in transfers_sent],
                            transfers_recv=[dict(r) for r in transfers_recv],
                            transactions=[dict(r) for r in transactions],
                            settings=settings, lang=lang,
                            tx_type=tx_type, tx_date=tx_date)

@app.route("/withdraw", methods=["POST"])
@login_required
def withdraw():
    uid = session["user_id"]
    lang = session.get("lang","en")
    try:
        amount = float(request.form.get("amount",0))
    except (ValueError, TypeError):
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    currency = request.form.get("currency","naira")
    pin = request.form.get("pin","")
    settings = get_settings()
    wallet = get_wallet(uid)
    # --- PIN check ---
    db = get_db()
    pin_rec = db.execute("SELECT pin_hash FROM pins WHERE user_id=?", (uid,)).fetchone()
    db.close()
    if not pin_rec:
        return jsonify({"success":False,"message":t("pin_required",lang)})
    if not verify_pw(pin, pin_rec["pin_hash"]):
        return jsonify({"success":False,"message":t("pin_wrong",lang)})
    # --- amount / balance checks ---
    if amount <= 0:
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    if amount < settings["min_withdrawal"]:
        return jsonify({"success":False,"message":f"{t('withdraw_min',lang)} ₦{settings['min_withdrawal']:,.0f}"})
    bal_key = "naira" if currency=="naira" else "dollar"
    if amount > wallet[bal_key]:
        return jsonify({"success":False,"message":t("insufficient_balance",lang)})
    # v8: auto-use saved bank details
    db2 = get_db()
    bank = db2.execute("SELECT * FROM bank_details WHERE user_id=?", (uid,)).fetchone()
    db2.close()
    if not bank or not bank["bank_name"]:
        return jsonify({"success":False,"message":"Please set your bank details in Profile first."})
    bank_info = f"{bank['type'].upper()} | {bank['bank_name']} | {bank['account_number']} | {bank['account_name']}"
    fee = amount*(settings["withdrawal_fee_percent"]/100); net = amount-fee
    wid = f"WD_{short_id()}"
    db = get_db()
    db.execute("INSERT INTO withdrawals(id,user_id,amount,fee,net,currency,bank_info,status,requested_at) VALUES(?,?,?,?,?,?,?,'pending',?)",
               (wid, uid, amount, fee, net, currency, bank_info[:500], now_str()))
    db.commit()
    db.close()
    upd_wallet(uid, bal_key, -amount)
    add_transaction(uid, "debit", amount, currency, f"Withdrawal request — Net: ₦{net:,.2f}", wid)
    add_notif(uid, f"💸 {t('withdrawal_request',lang)} ₦{amount:,.2f}", "info")
    log_audit("withdraw_request", uid, wid, amount)
    record_analytics("total_withdrawn", amount)
    return jsonify({"success":True,"message":f"{t('withdrawal_request',lang)} Net: ₦{net:,.2f}"})

@app.route("/exchange", methods=["POST"])
@login_required
def exchange():
    uid = session["user_id"]
    lang = session.get("lang","en")
    from_curr = request.form.get("from_currency")
    try:
        amount = float(request.form.get("amount",0))
    except (ValueError, TypeError):
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    if amount <= 0:
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    settings = get_settings()
    rate = settings["exchange_rate"]
    wallet = get_wallet(uid)
    if from_curr=="naira":
        if amount>wallet["naira"]: return jsonify({"success":False,"message":t("insufficient_balance",lang)})
        to_amount=amount/rate; to_curr="dollar"
    else:
        if amount>wallet["dollar"]: return jsonify({"success":False,"message":t("insufficient_balance",lang)})
        to_amount=amount*rate; to_curr="naira"
    eid = f"EX_{short_id()}"
    db = get_db()
    db.execute("INSERT INTO exchanges(id,user_id,from_currency,from_amount,to_currency,to_amount,rate,time) VALUES(?,?,?,?,?,?,?,?)",
               (eid, uid, from_curr, amount, to_curr, to_amount, rate, now_str()))
    db.commit()
    db.close()
    upd_wallet(uid, from_curr, -amount)
    upd_wallet(uid, to_curr, to_amount)
    sym = "$" if to_curr=="dollar" else "₦"
    add_transaction(uid, "credit", to_amount, to_curr, f"Exchange {from_curr}→{to_curr}", eid)
    return jsonify({"success":True,"message":f"{t('exchanged',lang)} {sym}{to_amount:,.4f}"})

@app.route("/transfer", methods=["POST"])
@login_required
def transfer():
    uid = session["user_id"]
    lang = session.get("lang","en")
    settings_t = get_settings()
    if not settings_t.get("transfers_enabled"):
        return jsonify({"success":False,"message":t("transfer_disabled",lang)})
    receiver_id = request.form.get("receiver_id","").strip()
    try:
        amount = float(request.form.get("amount",0))
    except (ValueError, TypeError):
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    pin = request.form.get("pin","")
    if receiver_id==uid: return jsonify({"success":False,"message":t("cannot_send_self",lang)})
    tr_min = float(settings_t.get("transfer_min",0))
    tr_max = float(settings_t.get("transfer_max",1000000))
    if tr_min > 0 and amount < tr_min:
        return jsonify({"success":False,"message":f"{t('transfer_min',lang)} ₦{tr_min:,.0f}"})
    if tr_max > 0 and amount > tr_max:
        return jsonify({"success":False,"message":f"{t('transfer_max',lang)} ₦{tr_max:,.0f}"})
    tr_daily = int(settings_t.get("transfer_daily_limit",0))
    if tr_daily > 0:
        today_str = datetime.now().strftime("%Y-%m-%d")
        db_chk = get_db()
        today_total = db_chk.execute(
            "SELECT COALESCE(SUM(amount),0) as s FROM transfers WHERE sender_id=? AND time LIKE ?",
            (uid, f"{today_str}%")
        ).fetchone()["s"]
        db_chk.close()
        if today_total + amount > tr_daily:
            return jsonify({"success":False,"message":f"{t('transfer_daily_limit',lang)}: ₦{tr_daily:,.0f}/day"})
    db = get_db()
    receiver = db.execute("SELECT id,name FROM users WHERE id=?", (receiver_id,)).fetchone()
    if not receiver:
        db.close()
        return jsonify({"success":False,"message":t("user_not_found",lang)})
    pin_rec = db.execute("SELECT pin_hash FROM pins WHERE user_id=?", (uid,)).fetchone()
    if not pin_rec:
        db.close()
        return jsonify({"success":False,"message":t("pin_required",lang)})
    if not verify_pw(pin, pin_rec["pin_hash"]):
        db.close()
        return jsonify({"success":False,"message":t("pin_wrong",lang)})
    sender = db.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
    db.close()
    wallet = get_wallet(uid)
    if amount>wallet["naira"]: return jsonify({"success":False,"message":t("insufficient_balance",lang)})
    trid = f"TR_{short_id()}"
    db = get_db()
    db.execute("INSERT INTO transfers(id,sender_id,receiver_id,amount,status,time) VALUES(?,?,?,?,'completed',?)",
               (trid, uid, receiver_id, amount, now_str()))
    db.commit()
    db.close()
    upd_wallet(uid, "naira", -amount)
    upd_wallet(receiver_id, "naira", amount)
    sname = sender["name"] if sender else "User"
    rname = receiver["name"]
    add_transaction(uid, "debit", amount, "naira", f"Transfer to {rname}", trid)
    add_transaction(receiver_id, "credit", amount, "naira", f"Transfer from {sname}", trid)
    add_notif(uid, f"💸 {t('money_sent',lang)} → {rname}: ₦{amount:,.2f}", "success")
    add_notif(receiver_id, f"💰 +₦{amount:,.2f} ← {sname}", "success")
    log_audit("transfer", uid, f"to:{receiver_id}", amount)
    record_analytics("transfers_done")
    check_achievements(uid)
    return jsonify({"success":True,"message":f"{t('money_sent',lang)} → {rname}"})

@app.route("/set_pin", methods=["POST"])
@login_required
def set_pin():
    uid = session["user_id"]
    lang = session.get("lang","en")
    pin = request.form.get("pin","")
    if len(pin)!=4 or not pin.isdigit(): return jsonify({"success":False,"message":t("pin_4digits",lang)})
    db = get_db()
    db.execute("INSERT OR REPLACE INTO pins(user_id,pin_hash,created) VALUES(?,?,?)",
               (uid, hash_pw(pin), now_str()))
    db.commit()
    db.close()
    return jsonify({"success":True,"message":t("pin_set",lang)})

@app.route("/referrals")
@login_required
def referrals_page():
    uid = session["user_id"]
    db = get_db()
    l1_refs = db.execute("""SELECT r.*,u.name FROM referrals r LEFT JOIN users u ON r.referred_id=u.id
                            WHERE r.referrer_id=? AND r.level=1 ORDER BY r.time DESC""", (uid,)).fetchall()
    l2_refs = db.execute("""SELECT r.*,u.name FROM referrals r LEFT JOIN users u ON r.referred_id=u.id
                            WHERE r.referrer_id=? AND r.level=2 ORDER BY r.time DESC""", (uid,)).fetchall()
    leaderboard = db.execute("""SELECT u.name,u.id, w.referral_count+w.referral_count_l2 as total
                                FROM wallets w JOIN users u ON w.user_id=u.id
                                WHERE u.is_admin=0 AND (w.referral_count+w.referral_count_l2)>0
                                ORDER BY total DESC LIMIT 10""").fetchall()
    db.close()
    wallet = get_wallet(uid)
    settings = get_settings()
    ref_link = f"{request.host_url}r/{uid}"
    lang = session.get("lang","en")
    def enrich(refs):
        return [{"name": r["name"] or "Unknown", "time": r["time"][:10] if r["time"] else "",
                 "tasks_done": r["tasks_done"], "bonus_paid": bool(r["bonus_paid"]),
                 "tasks_needed": settings["referral_tasks_needed"], "level": r["level"]} for r in refs]
    lb_data = [{"name": r["name"], "count": r["total"], "is_me": r["id"]==uid} for r in leaderboard]
    return render_template("referrals.html", ref_link=ref_link,
                            referrals=enrich(l1_refs), referrals_l2=enrich(l2_refs),
                            wallet=wallet, settings=settings, leaderboard=lb_data, lang=lang)

@app.route("/profile", methods=["GET","POST"])
@login_required
def profile():
    uid = session["user_id"]
    lang = session.get("lang","en")
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if request.method=="POST":
        name = request.form.get("name","").strip()[:100]
        old_pw = request.form.get("old_password","")
        new_pw = request.form.get("new_password","")
        if name:
            db.execute("UPDATE users SET name=? WHERE id=?", (name, uid))
            session["user_name"] = name
        if old_pw and new_pw:
            if not verify_pw(old_pw, user["password"]):
                db.close()
                return jsonify({"success":False,"message":t("wrong_email_or_password",lang)})
            if len(new_pw)<8:
                db.close()
                return jsonify({"success":False,"message":t("password_short",lang)})
            db.execute("UPDATE users SET password=? WHERE id=?", (hash_pw(new_pw), uid))
        db.commit()
        db.close()
        return jsonify({"success":True,"message":t("profile_updated",lang)})
    bank = db.execute("SELECT * FROM bank_details WHERE user_id=?", (uid,)).fetchone()
    has_pin = db.execute("SELECT user_id FROM pins WHERE user_id=?", (uid,)).fetchone() is not None
    dl = db.execute("SELECT total_days FROM daily_logins WHERE user_id=?", (uid,)).fetchone()
    db.close()
    wallet = get_wallet(uid)
    daily_days = dl["total_days"] if dl else 0
    settings_p = get_settings()
    tg_support_user = settings_p.get("telegram_support_username", "socialpaysupport").lstrip("@")
    return render_template("profile.html", user=dict(user), bank=dict(bank) if bank else {},
                            has_pin=has_pin, wallet=wallet, daily_days=daily_days, lang=lang,
                            tg_support_user=tg_support_user, user_id=uid)

@app.route("/save_bank", methods=["POST"])
@login_required
def save_bank():
    uid = session["user_id"]
    lang = session.get("lang","en")
    db = get_db()
    acc_num = request.form.get("account_number","").strip()[:20]
    if acc_num:
        dup = db.execute("SELECT user_id FROM bank_details WHERE account_number=?", (acc_num,)).fetchone()
        if dup and dup["user_id"] != uid:
            db.close()
            return jsonify({"success":False,"message":t("bank_duplicate",lang)})
    db.execute("""INSERT OR REPLACE INTO bank_details(user_id,bank_name,account_number,account_name,type,updated)
                  VALUES(?,?,?,?,?,?)""",
               (uid, request.form.get("bank_name","")[:100], acc_num,
                request.form.get("account_name","")[:100],
                request.form.get("type","bank"), now_str()))
    db.commit()
    db.close()
    return jsonify({"success":True,"message":t("bank_saved",lang)})

@app.route("/notifications")
@login_required
def notif_page():
    uid = session["user_id"]
    db = get_db()
    notifs = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY time DESC", (uid,)).fetchall()
    db.execute("UPDATE notifications SET read=1 WHERE user_id=?", (uid,))
    try:
        admin_msgs = db.execute("SELECT * FROM admin_messages WHERE user_id=? ORDER BY time DESC LIMIT 20", (uid,)).fetchall()
        db.execute("UPDATE admin_messages SET read=1 WHERE user_id=?", (uid,))
    except:
        admin_msgs = []
    db.commit()
    db.close()
    lang = session.get("lang","en")
    return render_template("notifications.html", notifications=[dict(n) for n in notifs],
                            admin_messages=[dict(m) for m in admin_msgs], lang=lang)

@app.route("/my_submissions")
@login_required
def my_submissions():
    uid = session["user_id"]
    db = get_db()
    subs = db.execute("""SELECT s.*,t.title as task_title,t.platform as task_platform
                         FROM submissions s LEFT JOIN tasks t ON s.task_id=t.id
                         WHERE s.user_id=? ORDER BY s.submitted_at DESC""", (uid,)).fetchall()
    db.close()
    lang = session.get("lang","en")
    return render_template("my_submissions.html", submissions=[dict(s) for s in subs], lang=lang)

# ============================================================
# SPIN & WIN
# ============================================================
@app.route("/spin", methods=["POST"])
@login_required
def spin():
    uid = session["user_id"]
    lang = session.get("lang","en")
    settings = get_settings()
    if not settings.get("spin_enabled"):
        return jsonify({"success":False,"message":"Spin is disabled by admin."})
    spin_cost = int(settings.get("spin_cost", 50))
    spin_daily_limit = int(settings.get("spin_daily_limit", 0))
    # Check daily spin limit if set
    if spin_daily_limit > 0:
        db = get_db()
        today = datetime.now().strftime("%Y-%m-%d")
        sp_today = db.execute("SELECT * FROM spins WHERE user_id=?", (uid,)).fetchone()
        db.close()
        if sp_today and sp_today["last_spin"] and sp_today["last_spin"][:10] == today:
            # Count today's spins via transactions
            db2 = get_db()
            today_spins = db2.execute(
                "SELECT COUNT(*) as c FROM transactions WHERE user_id=? AND description LIKE 'Spin%' AND time LIKE ?",
                (uid, f"{today}%")
            ).fetchone()["c"]
            db2.close()
            if today_spins >= spin_daily_limit:
                return jsonify({"success":False,"message":f"Daily spin limit reached ({spin_daily_limit} spins/day). Come back tomorrow!"})
    settings_rl = get_settings()
    rl_spin = int(settings_rl.get("rate_limit_spin", 10))
    if rate_limited(f"spin_{uid}", rl_spin, 3600):
        return jsonify({"success":False,"message":f"Too many spins. Max {rl_spin} per hour."})
    wallet = get_wallet(uid)
    if wallet.get("naira",0) < spin_cost:
        return jsonify({"success":False,"message":f"Insufficient balance. You need ₦{spin_cost:,} to spin."})
    # v8: Pre-calculate result BEFORE deducting - saved immediately so reward persists even if connection drops
    SPIN_PRIZES = get_spin_prizes(settings)
    pool = []
    for i,p in enumerate(SPIN_PRIZES): pool.extend([i]*p["prob"])
    idx = random.choice(pool)
    prize = SPIN_PRIZES[idx]
    upd_wallet(uid, "naira", -spin_cost)
    add_transaction(uid, "debit", spin_cost, "naira", "Spin & Win: Entry fee")
    db = get_db()
    sp = db.execute("SELECT * FROM spins WHERE user_id=?", (uid,)).fetchone()
    total_spins = (sp["total_spins"]+1) if sp else 1
    total_spent = (sp["total_spent"]+spin_cost) if sp else spin_cost
    try:
        db.execute("INSERT OR REPLACE INTO spins(user_id,last_spin,total_spins,total_spent,pending_prize,pending_prize_label) VALUES(?,?,?,?,?,?)",
                   (uid, now_str(), total_spins, total_spent, prize["amount"], prize["label"]))
    except:
        db.execute("INSERT OR REPLACE INTO spins(user_id,last_spin,total_spins,total_spent) VALUES(?,?,?,?)",
                   (uid, now_str(), total_spins, total_spent))
    db.commit()
    db.close()
    if prize["amount"] > 0:
        upd_wallet(uid, "naira", prize["amount"])
        upd_wallet(uid, "total_earned", prize["amount"])
        add_transaction(uid, "credit", prize["amount"], "naira", f"Spin & Win: {prize['label']}")
        add_notif(uid, f"🎰 You won {prize['label']}! (Cost: ₦{spin_cost:,})", "success")
        log_audit("spin_win", uid, prize["label"], prize["amount"])
        record_analytics("spins_done")
        # v9: Jackpot contribution
        settings_j = get_settings()
        if settings_j.get("jackpot_enabled"):
            contribution = spin_cost * (float(settings_j.get("jackpot_contribution_pct",5)) / 100)
            if contribution > 0:
                db_j = get_db()
                db_j.execute("INSERT OR IGNORE INTO jackpot_pool(id,amount) VALUES(1,0)")
                db_j.execute("UPDATE jackpot_pool SET amount=amount+? WHERE id=1", (contribution,))
                db_j.commit(); db_j.close()
    else:
        add_notif(uid, f"🎰 Try Again! You spent ₦{spin_cost:,} on spin.", "info")
        log_audit("spin_try_again", uid, "Try Again", 0)
    prizes_list = [{"label":p["label"],"amount":p["amount"]} for p in SPIN_PRIZES]
    return jsonify({"success":True,"prize":prize["label"],"amount":prize["amount"],"index":idx,"prizes":prizes_list,"spin_cost":spin_cost})

# ============================================================
# SUPPORT
# ============================================================
@app.route("/support", methods=["GET","POST"])
@login_required
def support():
    uid = session["user_id"]
    lang = session.get("lang","en")
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if request.method=="POST":
        subject = request.form.get("subject","").strip()[:200]
        message = request.form.get("message","").strip()[:2000]
        category = request.form.get("category","general")
        if not subject or not message:
            db.close()
            return jsonify({"success":False,"message":t("fill_all_fields",lang)})
        tid = f"TKT_{short_id()}"
        db.execute("""INSERT INTO support_tickets(id,user_id,user_name,user_email,subject,message,category,status,created)
                      VALUES(?,?,?,?,?,?,?,'open',?)""",
                   (tid, uid, user["name"], user["email"], subject, message, category, now_str()))
        db.commit()
        # Fix #12: Notify all admins about new ticket
        admins = db.execute("SELECT id FROM users WHERE is_admin=1").fetchall()
        db.close()
        for adm in admins:
            add_notif(adm["id"], f"🎫 New support ticket from {user['name']}: {subject}", "info")
        add_notif(uid, f"✅ Support ticket submitted: {subject}", "success")
        return jsonify({"success":True,"message":"✅ Ticket submitted! We will reply soon."})
    tickets = db.execute("""SELECT t.*, GROUP_CONCAT(r.from_role||'|'||r.name||'|'||r.message||'|'||r.time, '||SEP||') as replies_raw
                            FROM support_tickets t LEFT JOIN support_replies r ON t.id=r.ticket_id
                            WHERE t.user_id=? GROUP BY t.id ORDER BY t.created DESC""", (uid,)).fetchall()
    db.close()
    parsed_tickets = []
    for tk in tickets:
        td = dict(tk)
        if td.get("replies_raw"):
            replies = []
            for rr in td["replies_raw"].split("||SEP||"):
                parts = rr.split("|")
                if len(parts) >= 4:
                    replies.append({"from": parts[0], "name": parts[1], "message": parts[2], "time": parts[3]})
            td["replies"] = replies
        else:
            td["replies"] = []
        del td["replies_raw"]
        parsed_tickets.append(td)
    return render_template("support.html", tickets=parsed_tickets, user=dict(user), lang=lang, tg_support=TG_SUPPORT)

@app.route("/support/reply/<tid>", methods=["POST"])
@login_required
def support_reply(tid):
    uid = session["user_id"]
    lang = session.get("lang","en")
    message = request.form.get("message","").strip()[:1000]
    if not message: return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    db = get_db()
    tk = db.execute("SELECT user_id FROM support_tickets WHERE id=?", (tid,)).fetchone()
    if not tk or tk["user_id"] != uid:
        db.close()
        return jsonify({"success":False,"message":"Unauthorized"})
    db.execute("INSERT INTO support_replies(ticket_id,from_role,name,message,time) VALUES(?,'user',?,?,?)",
               (tid, session.get("user_name","User"), message, now_str()))
    db.commit()
    db.close()
    return jsonify({"success":True,"message":"Reply sent!"})

# ============================================================
# API
# ============================================================
@app.route("/api/user_lookup", methods=["POST"])
@login_required
def api_user_lookup():
    qid = request.json.get("user_id","").strip()
    db = get_db()
    u = db.execute("SELECT name,is_admin FROM users WHERE id=?", (qid,)).fetchone()
    db.close()
    if u and not u["is_admin"]:
        return jsonify({"found":True,"name":u["name"]})
    return jsonify({"found":False})

@app.route("/api/notif_count")
@login_required
def api_notif_count():
    db = get_db()
    c = db.execute("SELECT COUNT(*) as c FROM notifications WHERE user_id=? AND read=0",
                   (session["user_id"],)).fetchone()["c"]
    db.close()
    return jsonify({"count":c})

@app.route("/api/wallet")
@login_required
def api_wallet():
    w = get_wallet(session["user_id"])
    return jsonify({"naira":w["naira"],"dollar":w["dollar"],"total_earned":w.get("total_earned",0),"completed_tasks":w.get("completed_tasks",0)})

@app.route("/api/bank_info")
@login_required
def api_bank_info():
    uid = session["user_id"]
    db = get_db()
    bank = db.execute("SELECT * FROM bank_details WHERE user_id=?", (uid,)).fetchone()
    db.close()
    if bank and bank["bank_name"]:
        return jsonify({"has_bank":True,"bank_name":bank["bank_name"],"account_number":bank["account_number"],"account_name":bank["account_name"],"type":bank["type"]})
    return jsonify({"has_bank":False})

# ============================================================
# ADMIN ROUTES
# ============================================================
@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    total_users = db.execute("SELECT COUNT(*) as c FROM users WHERE is_admin=0").fetchone()["c"]
    active_tasks = db.execute("SELECT COUNT(*) as c FROM tasks WHERE status='active'").fetchone()["c"]
    pending_subs = db.execute("SELECT COUNT(*) as c FROM submissions WHERE status='pending'").fetchone()["c"]
    pending_wds = db.execute("SELECT COUNT(*) as c FROM withdrawals WHERE status='pending'").fetchone()["c"]
    total_naira = db.execute("SELECT COALESCE(SUM(naira),0) as s FROM wallets").fetchone()["s"]
    total_dollar = db.execute("SELECT COALESCE(SUM(dollar),0) as s FROM wallets").fetchone()["s"]
    recent = db.execute("SELECT u.*,w.naira FROM users u LEFT JOIN wallets w ON u.id=w.user_id WHERE u.is_admin=0 ORDER BY u.created DESC LIMIT 5").fetchall()
    my_role = db.execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()["role"]
    unread_tickets = db.execute("SELECT COUNT(*) as c FROM support_tickets WHERE status='open'").fetchone()["c"]
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/dashboard.html",
        total_users=total_users, active_tasks=active_tasks, pending_subs=pending_subs,
        pending_wds=pending_wds, total_naira=total_naira, total_dollar=total_dollar,
        recent_users=[dict(r) for r in recent], settings=get_settings(), lang=lang,
        my_role=my_role, unread_tickets=unread_tickets)

@app.route("/admin/users")
@admin_required
def admin_users():
    q = request.args.get("q","").lower()
    db = get_db()
    if q:
        users = db.execute("""SELECT u.*,w.naira,w.completed_tasks FROM users u
                              LEFT JOIN wallets w ON u.id=w.user_id
                              WHERE LOWER(u.name) LIKE ? OR LOWER(u.email) LIKE ? OR LOWER(u.id) LIKE ?
                              ORDER BY u.created DESC""",
                           (f"%{q}%",f"%{q}%",f"%{q}%")).fetchall()
    else:
        users = db.execute("""SELECT u.*,w.naira,w.completed_tasks FROM users u
                              LEFT JOIN wallets w ON u.id=w.user_id ORDER BY u.created DESC""").fetchall()
    my_role = db.execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()["role"]
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/users.html", users=[dict(u) for u in users], q=q, lang=lang, my_role=my_role)

@app.route("/admin/user/<uid>")
@admin_required
def admin_user_detail(uid):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        db.close()
        return redirect(url_for("admin_users"))
    wallet = db.execute("SELECT * FROM wallets WHERE user_id=?", (uid,)).fetchone()
    subs = db.execute("SELECT s.*,t.title as task_title FROM submissions s LEFT JOIN tasks t ON s.task_id=t.id WHERE s.user_id=? ORDER BY s.submitted_at DESC LIMIT 10", (uid,)).fetchall()
    wds = db.execute("SELECT * FROM withdrawals WHERE user_id=? ORDER BY requested_at DESC LIMIT 10", (uid,)).fetchall()
    trs = db.execute("SELECT * FROM transfers WHERE sender_id=? OR receiver_id=? ORDER BY time DESC LIMIT 10", (uid, uid)).fetchall()
    txs = db.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY time DESC LIMIT 20", (uid,)).fetchall()
    bank = db.execute("SELECT * FROM bank_details WHERE user_id=?", (uid,)).fetchone()
    has_pin = db.execute("SELECT user_id FROM pins WHERE user_id=?", (uid,)).fetchone() is not None
    my_role = db.execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()["role"]
    pin_row = None
    if my_role == "super_admin":
        pin_row = db.execute("SELECT pin_hash FROM pins WHERE user_id=?", (uid,)).fetchone()
    try:
        tracking = db.execute("SELECT * FROM user_tracking WHERE user_id=? ORDER BY time DESC LIMIT 5", (uid,)).fetchall()
    except:
        tracking = []
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/user_detail.html", user=dict(user), user_id=uid,
        wallet=dict(wallet) if wallet else {}, submissions=[dict(s) for s in subs],
        withdrawals=[dict(w) for w in wds], transfers=[dict(t) for t in trs],
        transactions=[dict(t) for t in txs], bank=dict(bank) if bank else {},
        has_pin=has_pin, lang=lang, my_role=my_role,
        pin_row=dict(pin_row) if pin_row else None,
        tracking=[dict(t) for t in tracking])

@app.route("/admin/user/action", methods=["POST"])
@admin_required
def admin_user_action():
    action = request.form.get("action")
    uid = request.form.get("user_id")
    admin_id = session["user_id"]
    lang = session.get("lang","en")
    db = get_db()
    my_role = db.execute("SELECT role FROM users WHERE id=?", (admin_id,)).fetchone()["role"]
    user = db.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        db.close()
        return jsonify({"success":False,"message":t("user_not_found",lang)})
    if action=="ban":
        db.execute("UPDATE users SET banned=1 WHERE id=?", (uid,))
        db.commit(); db.close()
        add_notif(uid, f"⛔ {t('account_banned',lang)}", "error")
        log_audit("ban", admin_id, uid)
        return jsonify({"success":True,"message":t("user_banned",lang)})
    elif action=="unban":
        db.execute("UPDATE users SET banned=0 WHERE id=?", (uid,))
        db.commit(); db.close()
        add_notif(uid, "✅ Account restored.", "success")
        log_audit("unban", admin_id, uid)
        return jsonify({"success":True,"message":t("user_unbanned",lang)})
    elif action=="adjust_balance":
        currency = request.form.get("currency","naira")
        amount = float(request.form.get("amount",0))
        mode = request.form.get("mode","add")
        db.commit(); db.close()
        if mode=="add": upd_wallet(uid, currency, amount); add_transaction(uid,"credit",amount,currency,"Admin balance adjustment")
        elif mode=="deduct": upd_wallet(uid, currency, -amount); add_transaction(uid,"debit",amount,currency,"Admin balance deduction")
        else: upd_wallet(uid, currency, amount, absolute=True)
        add_notif(uid, "💰 Balance updated by admin", "info")
        log_audit("adjust_balance", admin_id, f"{uid}:{currency}:{mode}", amount)
        return jsonify({"success":True,"message":t("balance_adjusted",lang)})
    elif action=="message":
        msg = request.form.get("message","").strip()[:500]
        img = request.form.get("image","") or ""
        db.commit(); db.close()
        if msg or img:
            mid = f"AM_{short_id()}"
            db2 = get_db()
            db2.execute("INSERT INTO admin_messages(id,user_id,sender_id,message,image,time,read) VALUES(?,?,?,?,?,?,0)",
                        (mid, uid, admin_id, msg, img[:200000] if img else "", now_str()))
            db2.commit(); db2.close()
            add_notif(uid, f"📩 {t('from_admin',lang)}: {msg[:80]}", "info", img[:200000] if img else "")
            send_push_notification(uid, f"📩 {get_app_name()}", msg[:120], "/notifications")
            log_audit("message_user", admin_id, uid)
            return jsonify({"success":True,"message":t("message_sent",lang)})
    elif action=="reset_pin":
        db.execute("DELETE FROM pins WHERE user_id=?", (uid,))
        db.commit(); db.close()
        add_notif(uid, f"🔐 {t('pin_reset',lang)}. Please set a new PIN.", "warning")
        log_audit("reset_pin", admin_id, uid)
        return jsonify({"success":True,"message":t("pin_reset",lang)})
    elif action=="edit_bank":
        acc_num = request.form.get("account_number","").strip()[:20]
        bank_name = request.form.get("bank_name","").strip()[:100]
        account_name = request.form.get("account_name","").strip()[:100]
        btype = request.form.get("type","bank")
        db.execute("INSERT OR REPLACE INTO bank_details(user_id,bank_name,account_number,account_name,type,updated) VALUES(?,?,?,?,?,?)",
                   (uid, bank_name, acc_num, account_name, btype, now_str()))
        db.commit(); db.close()
        log_audit("edit_bank", admin_id, uid)
        return jsonify({"success":True,"message":"Bank details updated!"})
    elif action=="delete_bank":
        db.execute("DELETE FROM bank_details WHERE user_id=?", (uid,))
        db.commit(); db.close()
        log_audit("delete_bank", admin_id, uid)
        return jsonify({"success":True,"message":"Bank details deleted!"})
    elif action=="make_admin":
        if my_role!="super_admin":
            db.close()
            return jsonify({"success":False,"message":"Only Super Admin can do this"})
        db.execute("UPDATE users SET is_admin=1,role='admin' WHERE id=?", (uid,))
        db.commit(); db.close()
        log_audit("make_admin", admin_id, uid)
        return jsonify({"success":True,"message":"Admin role granted!"})
    elif action=="remove_admin":
        if my_role!="super_admin":
            db.close()
            return jsonify({"success":False,"message":"Only Super Admin can do this"})
        u_role = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
        if u_role and u_role["role"]=="super_admin":
            db.close()
            return jsonify({"success":False,"message":"Cannot remove Super Admin"})
        db.execute("UPDATE users SET is_admin=0,role='user' WHERE id=?", (uid,))
        db.commit(); db.close()
        log_audit("remove_admin", admin_id, uid)
        return jsonify({"success":True,"message":"Admin role removed"})
    elif action=="delete_user":
        if my_role!="super_admin":
            db.close()
            return jsonify({"success":False,"message":"Only Super Admin can delete users"})
        for tbl in ["wallets","pins","bank_details","daily_logins","spins","notifications","admin_messages"]:
            db.execute(f"DELETE FROM {tbl} WHERE user_id=?", (uid,))
        db.execute("DELETE FROM submissions WHERE user_id=?", (uid,))
        db.execute("DELETE FROM withdrawals WHERE user_id=?", (uid,))
        db.execute("DELETE FROM transactions WHERE user_id=?", (uid,))
        db.execute("DELETE FROM referrals WHERE referrer_id=? OR referred_id=?", (uid, uid))
        db.execute("DELETE FROM users WHERE id=?", (uid,))
        db.commit(); db.close()
        log_audit("delete_user", admin_id, uid)
        return jsonify({"success":True,"message":"User deleted!", "redirect":url_for("admin_users")})
    db.close()
    return jsonify({"success":False,"message":"Unknown action"})

@app.route("/admin/tasks")
@admin_required
def admin_tasks():
    db = get_db()
    tasks = db.execute("SELECT * FROM tasks ORDER BY created DESC").fetchall()
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/tasks.html", tasks=[dict(t) for t in tasks], lang=lang)

@app.route("/admin/create_task", methods=["POST"])
@admin_required
def admin_create_task():
    lang = session.get("lang","en")
    title = request.form.get("title","").strip()[:200]
    if not title: return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    tid = f"TASK_{short_id()}"
    expires_hours = request.form.get("expires_hours","")
    expires_at = None
    if expires_hours:
        try: expires_at = (datetime.now()+timedelta(hours=float(expires_hours))).isoformat()
        except: pass
    try:
        reward = float(request.form.get("reward",0))
        max_users = int(request.form.get("max_users",100))
    except (ValueError, TypeError):
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    if reward <= 0:
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    db = get_db()
    db.execute("""INSERT INTO tasks(id,title,description,platform,task_type,link,reward,currency,max_users,status,auto_approve,completed_count,expires_at,created,created_by)
                  VALUES(?,?,?,?,?,?,?,?,?,'active',?,0,?,?,?)""",
               (tid, title, request.form.get("description","").strip()[:1000],
                request.form.get("platform","other"), request.form.get("task_type","other"),
                request.form.get("link","").strip()[:500], reward,
                request.form.get("currency","naira"), max_users,
                1 if request.form.get("auto_approve")=="1" else 0,
                expires_at, now_str(), session["user_id"]))
    db.commit()
    db.close()
    log_audit("create_task", session["user_id"], tid, reward)
    return jsonify({"success":True,"message":t("task_created",lang)})

@app.route("/admin/delete_task", methods=["POST"])
@admin_required
def admin_delete_task():
    lang = session.get("lang","en")
    tid = request.form.get("task_id")
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id=?", (tid,))
    db.execute("DELETE FROM task_completions WHERE task_id=?", (tid,))
    db.commit()
    db.close()
    log_audit("delete_task", session["user_id"], tid)
    return jsonify({"success":True,"message":t("task_deleted",lang)})

@app.route("/admin/submissions")
@admin_required
def admin_submissions():
    status = request.args.get("status","pending")
    db = get_db()
    subs = db.execute("""SELECT s.*,t.title as task_title,u.name as user_name,u.email as user_email
                         FROM submissions s LEFT JOIN tasks t ON s.task_id=t.id LEFT JOIN users u ON s.user_id=u.id
                         WHERE s.status=? ORDER BY s.submitted_at DESC""", (status,)).fetchall()
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/submissions.html", submissions=[dict(s) for s in subs], status=status, lang=lang)

@app.route("/admin/review_submission", methods=["POST"])
@admin_required
def admin_review_submission():
    sid = request.form.get("sub_id")
    action = request.form.get("action")
    note = request.form.get("note","").strip()[:300]
    admin_id = session["user_id"]
    lang = session.get("lang","en")
    db = get_db()
    sub = db.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
    if not sub:
        db.close()
        return jsonify({"success":False,"message":"Not found"})
    # GUARD: only pending submissions can be reviewed
    if sub["status"] != "pending":
        db.close()
        return jsonify({"success":False,"message":f"This submission is already '{sub['status']}'. Cannot review again."})
    uid = sub["user_id"]
    tid = sub["task_id"]
    if action=="approve":
        reward = sub["reward"]
        curr = sub["currency"]
        db.execute("UPDATE submissions SET status='approved',reviewed_at=?,note=? WHERE id=?",
                   (now_str(), note, sid))
        db.execute("INSERT OR IGNORE INTO task_completions(task_id,user_id) VALUES(?,?)", (tid, uid))
        db.execute("UPDATE tasks SET completed_count=completed_count+1 WHERE id=?", (tid,))
        db.commit()
        db.close()
        upd_wallet(uid, curr, reward)
        upd_wallet(uid, "completed_tasks", 1)
        upd_wallet(uid, "pending_tasks", -1)
        upd_wallet(uid, "total_earned", reward)
        add_transaction(uid, "credit", reward, curr, "Task approved", sid)
        _check_referral_bonus(uid, lang)
        sym = "₦" if curr=="naira" else "$"
        add_notif(uid, f"✅ {t('submission_approved',lang)} +{sym}{reward:,.2f}", "success")
        send_push_notification(uid, f"✅ {get_app_name()}", f"Task approved! +{sym}{reward:,.2f}", "/balance")
        log_audit("approve_sub", admin_id, sid, reward)
        check_achievements(uid)
        record_analytics("tasks_approved")
        record_analytics("total_earned", reward)
        db2 = get_db()
        db2.execute("UPDATE submissions SET screenshot='' WHERE id=?", (sid,))
        db2.commit()
        db2.close()
        return jsonify({"success":True,"message":t("submission_approved",lang)})
    elif action=="reject":
        db.execute("UPDATE submissions SET status='rejected',reviewed_at=?,note=? WHERE id=?",
                   (now_str(), note, sid))
        db.commit()
        db.close()
        upd_wallet(uid, "pending_tasks", -1)
        add_notif(uid, f"❌ {t('submission_rejected',lang)} — {note or 'Proof invalid'}", "error")
        log_audit("reject_sub", admin_id, sid)
        db2 = get_db()
        db2.execute("UPDATE submissions SET screenshot='' WHERE id=?", (sid,))
        db2.commit()
        db2.close()
        return jsonify({"success":True,"message":t("submission_rejected",lang)})
    db.close()
    return jsonify({"success":False,"message":"Unknown action"})

@app.route("/admin/delete_submission", methods=["POST"])
@admin_required
def admin_delete_submission():
    sid = request.form.get("sub_id")
    lang = session.get("lang","en")
    db = get_db()
    sub = db.execute("SELECT user_id FROM submissions WHERE id=?", (sid,)).fetchone()
    if sub:
        db.execute("DELETE FROM submissions WHERE id=?", (sid,))
        db.commit()
    db.close()
    log_audit("delete_submission", session["user_id"], sid)
    return jsonify({"success":True,"message":"Submission deleted!"})

@app.route("/admin/withdrawals")
@admin_required
def admin_withdrawals():
    status = request.args.get("status","pending")
    db = get_db()
    wds = db.execute("""SELECT w.*,u.name as user_name,u.email as user_email
                        FROM withdrawals w LEFT JOIN users u ON w.user_id=u.id
                        WHERE w.status=? ORDER BY w.requested_at DESC""", (status,)).fetchall()
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/withdrawals.html", withdrawals=[dict(w) for w in wds], status=status, lang=lang)

@app.route("/admin/process_withdrawal", methods=["POST"])
@admin_required
def admin_process_withdrawal():
    wid = request.form.get("wd_id")
    action = request.form.get("action")
    note = request.form.get("note","").strip()
    admin_id = session["user_id"]
    lang = session.get("lang","en")
    db = get_db()
    wd = db.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
    if not wd:
        db.close()
        return jsonify({"success":False,"message":"Not found"})
    # GUARD: only pending withdrawals can be approved or rejected
    if wd["status"] != "pending":
        db.close()
        return jsonify({"success":False,"message":f"This withdrawal is already '{wd['status']}'. Cannot process again."})
    uid = wd["user_id"]
    curr = wd["currency"]
    if action=="approve":
        db.execute("UPDATE withdrawals SET status='approved',processed_at=?,note=? WHERE id=?",
                   (now_str(), note, wid))
        db.commit(); db.close()
        # naira was already deducted when user requested — just record total_withdrawn
        upd_wallet(uid, "total_withdrawn", wd["amount"])
        add_transaction(uid, "debit", wd["net"], curr, f"Withdrawal approved — Net: ₦{wd['net']:,.2f}", wid)
        add_notif(uid, f"✅ {t('withdrawal_approved',lang)} — Net: ₦{wd['net']:,.2f}", "success")
        log_audit("approve_wd", admin_id, wid, wd["amount"])
        return jsonify({"success":True,"message":t("withdrawal_approved",lang)})
    elif action=="reject":
        db.execute("UPDATE withdrawals SET status='rejected',processed_at=?,note=? WHERE id=?",
                   (now_str(), note, wid))
        db.commit(); db.close()
        # Refund full amount back to user balance
        upd_wallet(uid, curr, wd["amount"])
        add_transaction(uid, "credit", wd["amount"], curr, f"Withdrawal rejected — ₦{wd['amount']:,.2f} refunded", wid)
        add_notif(uid, f"❌ {t('withdrawal_rejected',lang)} — ₦{wd['amount']:,.2f} {t('refunded', lang) if lang else 'refunded'}. {note or ''}", "error")
        log_audit("reject_wd", admin_id, wid, wd["amount"])
        return jsonify({"success":True,"message":t("withdrawal_rejected",lang)})
    db.close()
    return jsonify({"success":False,"message":"Unknown action"})

@app.route("/admin/broadcast", methods=["GET","POST"])
@admin_required
def admin_broadcast():
    lang = session.get("lang","en")
    if request.method=="POST":
        msg = request.form.get("message","").strip()[:2000]
        ntype = request.form.get("type","info")
        img = request.form.get("image","") or ""
        if not msg and not img: return jsonify({"success":False,"message":t("fill_all_fields",lang)})
        db = get_db()
        users = db.execute("SELECT id FROM users WHERE is_admin=0").fetchall()
        db.close()
        count = 0
        for u in users:
            mid = f"AM_{short_id()}"
            db2 = get_db()
            db2.execute("INSERT INTO admin_messages(id,user_id,sender_id,message,image,time,read) VALUES(?,?,?,?,?,?,0)",
                        (mid, u["id"], session["user_id"], msg, img[:200000] if img else "", now_str()))
            db2.commit(); db2.close()
            add_notif(u["id"], f"📢 {t('admin_notice',lang)}: {msg[:100]}", ntype, img[:200000] if img else "")
            count += 1
        # Also send Web Push to all subscribers
        if msg:
            broadcast_push_to_all(
                title=f"📢 {get_app_name()}",
                body=msg[:120],
                url="/notifications"
            )
        log_audit("broadcast", session["user_id"], f"to {count} users")
        return jsonify({"success":True,"message":f"{t('broadcast_sent',lang)} ({count})"})
    return render_template("admin/broadcast.html", lang=lang)

@app.route("/admin/settings", methods=["GET","POST"])
@admin_required
def admin_settings():
    lang = session.get("lang","en")
    if request.method=="POST":
        s = get_settings()
        for k in ["referral_bonus","referral_bonus_l2","referral_tasks_needed","withdrawal_fee_percent",
                  "min_withdrawal","max_withdrawal","exchange_rate","signup_reward_amount","daily_login_reward"]:
            v = request.form.get(k)
            if v:
                try: save_setting(k, float(v))
                except: pass
        save_setting("site_name", request.form.get("site_name", s["site_name"])[:50])
        save_setting("maintenance", "1" if request.form.get("maintenance")=="1" else "0")
        save_setting("announcement", request.form.get("announcement","").strip()[:300])
        save_setting("signup_reward_enabled", "1" if request.form.get("signup_reward_enabled")=="1" else "0")
        save_setting("daily_login_enabled", "1" if request.form.get("daily_login_enabled")=="1" else "0")
        save_setting("spin_enabled", "1" if request.form.get("spin_enabled")=="1" else "0")
        save_setting("transfers_enabled", "1" if request.form.get("transfers_enabled")=="1" else "0")
        for k8 in ["transfer_min","transfer_max","transfer_daily_limit","login_attempt_limit"]:
            v8 = request.form.get(k8)
            if v8:
                try: save_setting(k8, float(v8))
                except: pass
        tg_u = request.form.get("telegram_support_username","").strip()
        if tg_u: save_setting("telegram_support_username", tg_u)
        save_setting("jackpot_enabled", "1" if request.form.get("jackpot_enabled")=="1" else "0")
        save_setting("in_app_chat_enabled", "1" if request.form.get("in_app_chat_enabled")=="1" else "0")
        save_setting("dark_mode_enabled", "1" if request.form.get("dark_mode_enabled")=="1" else "0")
        save_setting("onboarding_enabled", "1" if request.form.get("onboarding_enabled")=="1" else "0")
        for k9 in ["streak_bonus_7","streak_bonus_14","streak_bonus_30",
                   "jackpot_contribution_pct","jackpot_trigger_streak",
                   "withdrawal_auto_approve_threshold","rate_limit_spin","rate_limit_transfer","rate_limit_withdraw"]:
            v9 = request.form.get(k9)
            if v9:
                try: save_setting(k9, float(v9))
                except: pass
        sc = request.form.get("spin_cost")
        if sc:
            try: save_setting("spin_cost", int(float(sc)))
            except: pass
        # Fix #13: spin daily limit
        sdl = request.form.get("spin_daily_limit")
        if sdl:
            try: save_setting("spin_daily_limit", int(float(sdl)))
            except: pass
        raw_prizes = request.form.get("spin_prizes","")
        if raw_prizes.strip():
            try:
                parsed = [int(float(x.strip())) for x in raw_prizes.split(",") if x.strip()]
                if parsed: save_setting("spin_prizes", ",".join(str(p) for p in parsed[:8]))
            except: pass
        return jsonify({"success":True,"message":t("settings_saved",lang)})
    return render_template("admin/settings.html", settings=get_settings(), lang=lang)


@app.route("/admin/transfers")
@admin_required
def admin_transfers():
    db = get_db()
    trs = db.execute("""SELECT t.*,s.name as sender_name,r.name as receiver_name
                        FROM transfers t LEFT JOIN users s ON t.sender_id=s.id LEFT JOIN users r ON t.receiver_id=r.id
                        ORDER BY t.time DESC LIMIT 100""").fetchall()
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/transfers.html", transfers=[dict(t) for t in trs], lang=lang)

@app.route("/admin/reverse_transfer", methods=["POST"])
@admin_required
def admin_reverse_transfer():
    trid = request.form.get("tr_id")
    admin_id = session["user_id"]
    lang = session.get("lang","en")
    db = get_db()
    tr = db.execute("SELECT * FROM transfers WHERE id=?", (trid,)).fetchone()
    if not tr:
        db.close()
        return jsonify({"success":False,"message":"Not found"})
    if tr["status"]=="reversed":
        db.close()
        return jsonify({"success":False,"message":"Already reversed"})
    db.execute("UPDATE transfers SET status='reversed',reversed_at=?,reversed_by=? WHERE id=?",
               (now_str(), admin_id, trid))
    db.commit(); db.close()
    upd_wallet(tr["receiver_id"], "naira", -tr["amount"])
    upd_wallet(tr["sender_id"], "naira", tr["amount"])
    add_notif(tr["sender_id"], f"🔄 Transfer ₦{tr['amount']:,.2f} reversed → refunded", "info")
    add_notif(tr["receiver_id"], f"⚠️ Transfer ₦{tr['amount']:,.2f} reversed by admin", "warning")
    log_audit("reverse_transfer", admin_id, trid, tr["amount"])
    return jsonify({"success":True,"message":t("transfer_reversed",lang)})

@app.route("/admin/add_user", methods=["POST"])
@admin_required
def admin_add_user():
    lang = session.get("lang","en")
    email = request.form.get("email","").strip().lower()
    password = request.form.get("password","")
    name = request.form.get("name","").strip()[:100]
    if not email or not password or not name: return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    if len(password)<8: return jsonify({"success":False,"message":t("password_short",lang)})
    if "@" not in email: return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if existing:
        db.close()
        return jsonify({"success":False,"message":t("email_exists",lang)})
    is_admin_account = request.form.get("is_admin")=="1"
    my_role = db.execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()["role"]
    if is_admin_account and my_role!="super_admin":
        db.close()
        return jsonify({"success":False,"message":"Only Super Admin can create admin accounts"})
    uid = f"SP{short_id()}"
    db.execute("""INSERT INTO users(id,name,email,password,is_admin,role,banned,verified,created,last_login,referral_code,lang,signup_reward_given)
                  VALUES(?,?,?,?,?,?,0,1,?,?,?,'en',1)""",
               (uid, name, email, hash_pw(password),
                1 if is_admin_account else 0,
                "admin" if is_admin_account else "user",
                now_str(), now_str(), uid))
    db.execute("INSERT INTO wallets(user_id,created) VALUES(?,?)", (uid, now_str()))
    db.commit(); db.close()
    add_notif(uid, f"🎉 Welcome to {APP_NAME}!", "success")
    log_audit("admin_create_user", session["user_id"], uid)
    return jsonify({"success":True,"message":f"✅ Account created: {name} ({uid})","user_id":uid})

@app.route("/admin/support")
@admin_required
def admin_support():
    lang = session.get("lang","en")
    status_filter = request.args.get("status","open")
    db = get_db()
    tickets = db.execute("""SELECT t.*, GROUP_CONCAT(r.from_role||'|'||r.name||'|'||r.message||'|'||r.time, '||SEP||') as replies_raw
                            FROM support_tickets t LEFT JOIN support_replies r ON t.id=r.ticket_id
                            WHERE t.status=? GROUP BY t.id ORDER BY t.created DESC""", (status_filter,)).fetchall()
    db.close()
    parsed = []
    for tk in tickets:
        td = dict(tk)
        if td.get("replies_raw"):
            replies = []
            for rr in td["replies_raw"].split("||SEP||"):
                parts = rr.split("|")
                if len(parts) >= 4:
                    replies.append({"from": parts[0], "name": parts[1], "message": parts[2], "time": parts[3]})
            td["replies"] = replies
        else:
            td["replies"] = []
        del td["replies_raw"]
        parsed.append(td)
    return render_template("admin/support.html", tickets=parsed, status=status_filter, lang=lang)

@app.route("/admin/support/reply/<tid>", methods=["POST"])
@admin_required
def admin_support_reply(tid):
    lang = session.get("lang","en")
    message = request.form.get("message","").strip()[:1000]
    action = request.form.get("action","reply")
    db = get_db()
    tk = db.execute("SELECT * FROM support_tickets WHERE id=?", (tid,)).fetchone()
    if not tk:
        db.close()
        return jsonify({"success":False,"message":"Ticket not found"})
    if message:
        db.execute("INSERT INTO support_replies(ticket_id,from_role,name,message,time) VALUES(?,'admin',?,?,?)",
                   (tid, "SocialPay Support", message, now_str()))
        add_notif(tk["user_id"], f"💬 Admin replied to your ticket: {tk['subject']}", "info")
    if action=="close":
        db.execute("UPDATE support_tickets SET status='closed' WHERE id=?", (tid,))
    elif action=="open":
        db.execute("UPDATE support_tickets SET status='open' WHERE id=?", (tid,))
    db.commit(); db.close()
    return jsonify({"success":True,"message":"Done!"})


# ── Push Notification Routes ─────────────────────────────────
@app.route("/api/vapid_public_key")
def api_vapid_public_key():
    """Return public VAPID key for frontend subscription."""
    _, pub = get_or_create_vapid_keys()
    return jsonify({"public_key": pub})

@app.route("/api/save_push_sub", methods=["POST"])
@login_required
def api_save_push_sub():
    """Save/update push subscription for the logged-in user."""
    try:
        data = request.get_json(force=True) or {}
        endpoint = data.get("endpoint", "")
        p256dh = data.get("keys", {}).get("p256dh", "")
        auth = data.get("keys", {}).get("auth", "")
        if not endpoint or not p256dh or not auth:
            return jsonify({"success": False, "message": "Invalid subscription"})
        uid = session["user_id"]
        db = get_db()
        db.execute("""INSERT OR REPLACE INTO push_subscriptions(user_id,endpoint,p256dh,auth,created)
                      VALUES(?,?,?,?,?)""", (uid, endpoint, p256dh, auth, now_str()))
        db.commit(); db.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route("/api/remove_push_sub", methods=["POST"])
@login_required
def api_remove_push_sub():
    """Remove push subscription (user unsubscribed)."""
    try:
        data = request.get_json(force=True) or {}
        endpoint = data.get("endpoint", "")
        if endpoint:
            db = get_db()
            db.execute("DELETE FROM push_subscriptions WHERE user_id=? AND endpoint=?",
                       (session["user_id"], endpoint))
            db.commit(); db.close()
        return jsonify({"success": True})
    except Exception:
        return jsonify({"success": True})

# ============================================================
# ERROR HANDLERS
# ============================================================
@app.route("/admin/messages")
@admin_required
def admin_messages_page():
    lang = session.get("lang","en")
    db = get_db()
    users = db.execute("SELECT u.id,u.name,u.email FROM users u WHERE u.is_admin=0 ORDER BY u.name").fetchall()
    db.close()
    return render_template("admin/messages.html", users=[dict(u) for u in users], lang=lang)

@app.route("/admin/send_message", methods=["POST"])
@admin_required
def admin_send_message():
    lang = session.get("lang","en")
    user_id = request.form.get("user_id","").strip()
    msg = request.form.get("message","").strip()[:1000]
    img = request.form.get("image","") or ""
    if not user_id or (not msg and not img):
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    db = get_db()
    u = db.execute("SELECT id,name FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
    if not u:
        return jsonify({"success":False,"message":t("user_not_found",lang)})
    mid = f"AM_{short_id()}"
    db2 = get_db()
    db2.execute("INSERT INTO admin_messages(id,user_id,sender_id,message,image,time,read) VALUES(?,?,?,?,?,?,0)",
                (mid, user_id, session["user_id"], msg, img[:200000], now_str()))
    db2.commit(); db2.close()
    add_notif(user_id, f"📩 {t('from_admin',lang)}: {msg[:80]}", "info", img[:200000] if img else "")
    log_audit("send_message", session["user_id"], user_id)
    return jsonify({"success":True,"message":t("message_sent",lang)})

@app.route("/admin/tracking")
@admin_required
def admin_tracking():
    db = get_db()
    my_role = db.execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()["role"]
    if my_role != "super_admin":
        db.close()
        return redirect(url_for("admin_dashboard"))
    tracks = db.execute("""SELECT t.*,u.name,u.email FROM user_tracking t
                           LEFT JOIN users u ON t.user_id=u.id
                           ORDER BY t.time DESC LIMIT 200""").fetchall()
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/tracking.html", tracks=[dict(t) for t in tracks], lang=lang)

# ============================================================
# V9 NEW ROUTES
# ============================================================

# ── Analytics (Admin) ────────────────────────────────────────
@app.route("/admin/analytics")
@admin_required
def admin_analytics():
    db = get_db()
    # Last 30 days analytics
    rows = db.execute("""SELECT * FROM analytics_daily ORDER BY date DESC LIMIT 30""").fetchall()
    # Summary stats
    total_users = db.execute("SELECT COUNT(*) as c FROM users WHERE is_admin=0").fetchone()["c"]
    total_earned = db.execute("SELECT COALESCE(SUM(total_earned),0) as s FROM wallets").fetchone()["s"]
    total_withdrawn = db.execute("SELECT COALESCE(SUM(total_withdrawn),0) as s FROM wallets").fetchone()["s"]
    # New users last 7 days
    week_ago = (datetime.now()-timedelta(days=7)).isoformat()
    new_7d = db.execute("SELECT COUNT(*) as c FROM users WHERE created>? AND is_admin=0", (week_ago,)).fetchone()["c"]
    pending_wds = db.execute("SELECT COUNT(*) as c FROM withdrawals WHERE status='pending'").fetchone()["c"]
    pending_subs = db.execute("SELECT COUNT(*) as c FROM submissions WHERE status='pending'").fetchone()["c"]
    # Top earners
    top_earners = db.execute("""SELECT u.name,w.total_earned,w.completed_tasks FROM wallets w
                                JOIN users u ON w.user_id=u.id WHERE u.is_admin=0
                                ORDER BY w.total_earned DESC LIMIT 10""").fetchall()
    # Top referrers
    top_refs = db.execute("""SELECT u.name,w.referral_count+w.referral_count_l2 as total FROM wallets w
                             JOIN users u ON w.user_id=u.id WHERE u.is_admin=0
                             ORDER BY total DESC LIMIT 10""").fetchall()
    # Platform breakdown for tasks
    platforms = db.execute("""SELECT platform, COUNT(*) as cnt FROM submissions s
                               JOIN tasks t ON s.task_id=t.id
                               WHERE s.status='approved' GROUP BY platform ORDER BY cnt DESC""").fetchall()
    my_role = db.execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()["role"]
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/analytics.html",
        rows=[dict(r) for r in rows], total_users=total_users,
        total_earned=total_earned, total_withdrawn=total_withdrawn,
        new_7d=new_7d, pending_wds=pending_wds, pending_subs=pending_subs,
        top_earners=[dict(r) for r in top_earners],
        top_refs=[dict(r) for r in top_refs],
        platforms=[dict(r) for r in platforms],
        my_role=my_role, lang=lang)

# ── Achievements ─────────────────────────────────────────────
@app.route("/achievements")
@login_required
def achievements_page():
    uid = session["user_id"]
    db = get_db()
    earned = db.execute("SELECT * FROM achievements WHERE user_id=? ORDER BY earned_at DESC", (uid,)).fetchall()
    db.close()
    earned_keys = {r["badge"] for r in earned}
    all_badges = []
    for key, info in BADGES.items():
        all_badges.append({"key":key,"label":info["label"],"desc":info["desc"],
                           "earned": key in earned_keys,
                           "earned_at": next((r["earned_at"][:10] for r in earned if r["badge"]==key), None)})
    lang = session.get("lang","en")
    return render_template("achievements.html", badges=all_badges, earned_count=len(earned_keys), lang=lang)

# ── Goal setting ─────────────────────────────────────────────
@app.route("/set_goal", methods=["POST"])
@login_required
def set_goal():
    uid = session["user_id"]
    try:
        target = float(request.form.get("target",0))
    except: target = 0
    currency = request.form.get("currency","naira")
    if target <= 0: return jsonify({"success":False,"message":"Please enter a valid goal amount"})
    db = get_db()
    db.execute("INSERT OR REPLACE INTO goals(user_id,target,currency) VALUES(?,?,?)", (uid,target,currency))
    db.commit(); db.close()
    return jsonify({"success":True,"message":f"Goal set: ₦{target:,.0f}"})

# ── In-app chat ──────────────────────────────────────────────
@app.route("/chat")
@login_required
def chat_page():
    uid = session["user_id"]
    settings = get_settings()
    if not settings.get("in_app_chat_enabled"):
        return redirect(url_for("support"))
    db = get_db()
    msgs = db.execute("SELECT * FROM chat_messages WHERE user_id=? ORDER BY time ASC LIMIT 100", (uid,)).fetchall()
    db.execute("UPDATE chat_messages SET read=1 WHERE user_id=? AND sender_role='admin'", (uid,))
    db.commit(); db.close()
    lang = session.get("lang","en")
    return render_template("chat.html", messages=[dict(m) for m in msgs], lang=lang)

@app.route("/chat/send", methods=["POST"])
@login_required
def chat_send():
    uid = session["user_id"]
    msg = request.form.get("message","").strip()[:1000]
    if not msg: return jsonify({"success":False,"message":"Empty message"})
    if rate_limited(f"chat_{uid}", 20, 60):
        return jsonify({"success":False,"message":"Too many messages. Slow down."})
    db = get_db()
    mid = f"CH_{short_id()}"
    db.execute("INSERT INTO chat_messages(id,user_id,sender_role,message,time,read) VALUES(?,?,'user',?,?,1)",
               (mid, uid, msg, now_str()))
    db.commit()
    # Notify admins
    admins = db.execute("SELECT id FROM users WHERE is_admin=1").fetchall()
    db.close()
    for adm in admins:
        add_notif(adm["id"], f"💬 Chat from {session.get('user_name','User')}: {msg[:60]}", "info")
    return jsonify({"success":True,"message":"Sent!"})

@app.route("/admin/chat/<uid>", methods=["GET","POST"])
@admin_required
def admin_chat(uid):
    lang = session.get("lang","en")
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        db.close()
        return redirect(url_for("admin_users"))
    if request.method == "POST":
        msg = request.form.get("message","").strip()[:1000]
        if msg:
            mid = f"CH_{short_id()}"
            db.execute("INSERT INTO chat_messages(id,user_id,sender_role,message,time,read) VALUES(?,?,'admin',?,?,0)",
                       (mid, uid, msg, now_str()))
            db.commit(); db.close()
            add_notif(uid, f"💬 Admin replied in chat: {msg[:60]}", "info")
            return jsonify({"success":True,"message":"Sent!"})
        db.close()
        return jsonify({"success":False,"message":"Empty"})
    msgs = db.execute("SELECT * FROM chat_messages WHERE user_id=? ORDER BY time ASC", (uid,)).fetchall()
    db.execute("UPDATE chat_messages SET read=1 WHERE user_id=? AND sender_role='user'", (uid,))
    db.commit(); db.close()
    return render_template("admin/chat.html", user=dict(user), messages=[dict(m) for m in msgs],
                           user_id=uid, lang=lang)

# ── Scheduled tasks ──────────────────────────────────────────
@app.route("/admin/scheduled_tasks")
@admin_required
def admin_scheduled_tasks():
    db = get_db()
    tasks = db.execute("SELECT * FROM scheduled_tasks ORDER BY publish_at DESC").fetchall()
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/scheduled_tasks.html", tasks=[dict(t) for t in tasks], lang=lang)

@app.route("/admin/create_scheduled_task", methods=["POST"])
@admin_required
def admin_create_scheduled_task():
    lang = session.get("lang","en")
    title = request.form.get("title","").strip()[:200]
    if not title: return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    try:
        reward = float(request.form.get("reward",0))
        max_users = int(request.form.get("max_users",100))
        publish_at = request.form.get("publish_at","")
        if publish_at: datetime.fromisoformat(publish_at)  # validate
    except: return jsonify({"success":False,"message":"Invalid date/amount"})
    task_data = json.dumps({
        "title": title,
        "description": request.form.get("description","").strip()[:1000],
        "platform": request.form.get("platform","other"),
        "task_type": request.form.get("task_type","other"),
        "link": request.form.get("link","").strip()[:500],
        "reward": reward,
        "currency": request.form.get("currency","naira"),
        "max_users": max_users,
        "auto_approve": 1 if request.form.get("auto_approve")=="1" else 0,
        "expires_hours": request.form.get("expires_hours",""),
    })
    stid = f"SCHT_{short_id()}"
    db = get_db()
    db.execute("INSERT INTO scheduled_tasks(id,task_data,publish_at,published,created_by,created_at) VALUES(?,?,?,0,?,?)",
               (stid, task_data, publish_at, session["user_id"], now_str()))
    db.commit(); db.close()
    log_audit("create_scheduled_task", session["user_id"], stid, reward)
    return jsonify({"success":True,"message":f"Scheduled task created for {publish_at}"})

@app.route("/admin/delete_scheduled_task", methods=["POST"])
@admin_required
def admin_delete_scheduled_task():
    stid = request.form.get("task_id","")
    db = get_db()
    db.execute("DELETE FROM scheduled_tasks WHERE id=?", (stid,))
    db.commit(); db.close()
    return jsonify({"success":True,"message":"Deleted!"})

# ── IP Blacklist ─────────────────────────────────────────────
@app.route("/admin/ip_blacklist")
@admin_required
def admin_ip_blacklist():
    db = get_db()
    my_role = db.execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()["role"]
    if my_role != "super_admin":
        db.close()
        return redirect(url_for("admin_dashboard"))
    ips = db.execute("SELECT * FROM ip_blacklist ORDER BY added_at DESC").fetchall()
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/ip_blacklist.html", ips=[dict(i) for i in ips], lang=lang)

@app.route("/admin/ip_blacklist/add", methods=["POST"])
@admin_required
def admin_ip_blacklist_add():
    db = get_db()
    my_role = db.execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()["role"]
    db.close()
    if my_role != "super_admin":
        return jsonify({"success":False,"message":"Super Admin only"})
    ip = request.form.get("ip","").strip()
    reason = request.form.get("reason","").strip()[:200]
    if not ip: return jsonify({"success":False,"message":"Enter an IP address"})
    db = get_db()
    db.execute("INSERT OR REPLACE INTO ip_blacklist(ip,reason,added_by,added_at) VALUES(?,?,?,?)",
               (ip, reason, session["user_id"], now_str()))
    db.commit(); db.close()
    log_audit("blacklist_ip", session["user_id"], ip)
    return jsonify({"success":True,"message":f"IP {ip} blacklisted!"})

@app.route("/admin/ip_blacklist/remove", methods=["POST"])
@admin_required
def admin_ip_blacklist_remove():
    ip = request.form.get("ip","")
    db = get_db()
    db.execute("DELETE FROM ip_blacklist WHERE ip=?", (ip,))
    db.commit(); db.close()
    return jsonify({"success":True,"message":f"IP {ip} removed!"})

# ── Jackpot info API ─────────────────────────────────────────
@app.route("/api/jackpot")
@login_required
def api_jackpot():
    db = get_db()
    row = db.execute("SELECT * FROM jackpot_pool WHERE id=1").fetchone()
    db.close()
    settings = get_settings()
    return jsonify({
        "enabled": settings.get("jackpot_enabled", False),
        "amount": row["amount"] if row else 0,
        "last_winner": row["last_winner"] if row else None,
        "trigger_streak": settings.get("jackpot_trigger_streak", 7),
    })

# ── Leaderboard page ─────────────────────────────────────────
@app.route("/leaderboard")
@login_required
def leaderboard_page():
    uid = session["user_id"]
    db = get_db()
    top_earners = db.execute("""SELECT u.name,u.id,w.total_earned,w.completed_tasks
                                FROM wallets w JOIN users u ON w.user_id=u.id
                                WHERE u.is_admin=0 AND w.total_earned>0
                                ORDER BY w.total_earned DESC LIMIT 20""").fetchall()
    top_tasks = db.execute("""SELECT u.name,u.id,w.completed_tasks,w.total_earned
                              FROM wallets w JOIN users u ON w.user_id=u.id
                              WHERE u.is_admin=0 AND w.completed_tasks>0
                              ORDER BY w.completed_tasks DESC LIMIT 20""").fetchall()
    top_refs = db.execute("""SELECT u.name,u.id,w.referral_count+w.referral_count_l2 as total,w.referral_bonus_earned
                             FROM wallets w JOIN users u ON w.user_id=u.id
                             WHERE u.is_admin=0 AND (w.referral_count+w.referral_count_l2)>0
                             ORDER BY total DESC LIMIT 20""").fetchall()
    db.close()
    def mask(n):
        return (n[:3]+"***") if len(n)>3 else (n[0]+"**")
    lang = session.get("lang","en")
    return render_template("leaderboard.html",
        top_earners=[{"name":mask(r["name"]),"earned":r["total_earned"],"tasks":r["completed_tasks"],"is_me":r["id"]==uid} for r in top_earners],
        top_tasks=[{"name":mask(r["name"]),"tasks":r["completed_tasks"],"earned":r["total_earned"],"is_me":r["id"]==uid} for r in top_tasks],
        top_refs=[{"name":mask(r["name"]),"refs":r["total"],"bonus":r["referral_bonus_earned"],"is_me":r["id"]==uid} for r in top_refs],
        lang=lang)

# ── Bulk user actions ────────────────────────────────────────
@app.route("/admin/bulk_action", methods=["POST"])
@admin_required
def admin_bulk_action():
    lang = session.get("lang","en")
    action = request.form.get("action","")
    user_ids = request.form.getlist("user_ids[]")
    if not user_ids: return jsonify({"success":False,"message":"No users selected"})
    msg = request.form.get("message","").strip()[:500]
    amount = 0
    try: amount = float(request.form.get("amount",0))
    except: pass
    admin_id = session["user_id"]
    count = 0
    for uid in user_ids:
        if action == "broadcast_message" and msg:
            mid = f"AM_{short_id()}"
            db2 = get_db()
            db2.execute("INSERT INTO admin_messages(id,user_id,sender_id,message,image,time,read) VALUES(?,?,?,?,'',?,0)",
                        (mid, uid, admin_id, msg, now_str()))
            db2.commit(); db2.close()
            add_notif(uid, f"📩 {t('from_admin',lang)}: {msg[:80]}", "info")
            count += 1
        elif action == "adjust_balance" and amount != 0:
            mode = request.form.get("mode","add")
            if mode == "add": upd_wallet(uid, "naira", amount)
            elif mode == "deduct": upd_wallet(uid, "naira", -amount)
            add_notif(uid, "💰 Balance updated by admin", "info")
            count += 1
        elif action == "ban":
            db = get_db()
            db.execute("UPDATE users SET banned=1 WHERE id=?", (uid,))
            db.commit(); db.close()
            count += 1
    log_audit(f"bulk_{action}", admin_id, f"{count} users")
    return jsonify({"success":True,"message":f"Done! Applied to {count} users."})

# ── Referral tracking detail ─────────────────────────────────
@app.route("/referral_stats")
@login_required
def referral_stats():
    uid = session["user_id"]
    db = get_db()
    # Daily referral count (last 30 days)
    daily = db.execute("""SELECT substr(time,1,10) as day, COUNT(*) as cnt
                          FROM referrals WHERE referrer_id=? AND level=1
                          GROUP BY day ORDER BY day DESC LIMIT 30""", (uid,)).fetchall()
    this_week = (datetime.now()-timedelta(days=7)).isoformat()
    this_month = (datetime.now()-timedelta(days=30)).isoformat()
    week_refs = db.execute("SELECT COUNT(*) as c FROM referrals WHERE referrer_id=? AND level=1 AND time>?",
                           (uid, this_week)).fetchone()["c"]
    month_refs = db.execute("SELECT COUNT(*) as c FROM referrals WHERE referrer_id=? AND level=1 AND time>?",
                            (uid, this_month)).fetchone()["c"]
    db.close()
    return jsonify({
        "daily": [{"day":r["day"],"count":r["cnt"]} for r in daily],
        "week": week_refs,
        "month": month_refs,
    })

# ── Admin audit log filters ──────────────────────────────────
@app.route("/admin/logs")
@admin_required
def admin_logs():
    action_filter = request.args.get("action","")
    user_filter = request.args.get("user_id","")
    date_filter = request.args.get("date","")
    db = get_db()
    q = "SELECT * FROM audit_logs WHERE 1=1"
    params = []
    if action_filter:
        q += " AND action LIKE ?"
        params.append(f"%{action_filter}%")
    if user_filter:
        q += " AND user_id LIKE ?"
        params.append(f"%{user_filter}%")
    if date_filter:
        q += " AND time LIKE ?"
        params.append(f"{date_filter}%")
    q += " ORDER BY time DESC LIMIT 200"
    logs = db.execute(q, params).fetchall()
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/logs.html",
        logs=[dict(l) for l in logs],
        action_filter=action_filter, user_filter=user_filter, date_filter=date_filter, lang=lang)

# ── Scheduled task auto-publish (called on each request) ─────
@app.before_request
def auto_publish_scheduled_tasks():
    try:
        now = now_str()
        db = get_db()
        due = db.execute("SELECT * FROM scheduled_tasks WHERE published=0 AND publish_at<=?", (now,)).fetchall()
        db.close()
        if due:
            for row in due:
                try:
                    td = json.loads(row["task_data"])
                    tid = f"TASK_{short_id()}"
                    expires_at = None
                    if td.get("expires_hours"):
                        try: expires_at = (datetime.now()+timedelta(hours=float(td["expires_hours"]))).isoformat()
                        except: pass
                    db2 = get_db()
                    db2.execute("""INSERT OR IGNORE INTO tasks(id,title,description,platform,task_type,link,reward,currency,max_users,status,auto_approve,completed_count,expires_at,created,created_by)
                                   VALUES(?,?,?,?,?,?,?,?,?,'active',?,0,?,?,?)""",
                                (tid, td["title"], td.get("description",""),
                                 td.get("platform","other"), td.get("task_type","other"),
                                 td.get("link",""), td["reward"], td.get("currency","naira"),
                                 td.get("max_users",100), td.get("auto_approve",0),
                                 expires_at, now, row["created_by"]))
                    db2.execute("UPDATE scheduled_tasks SET published=1 WHERE id=?", (row["id"],))
                    db2.commit(); db2.close()
                    log_audit("auto_published_task", row["created_by"], tid, td["reward"])
                except: pass
    except: pass

# ── Offline page ─────────────────────────────────────────────
@app.route("/offline")
def offline_page():
    return render_template("offline.html")

# ── Download / Install App page ──────────────────────────────
@app.route("/download")
def download_app():
    """PWA install page — shown when user opens the app link in a browser."""
    lang = session.get("lang", "en")
    app_name = get_app_name()
    return render_template("download.html", lang=lang, app_name=app_name)

@app.route("/app")
def app_landing():
    """Short /app link always shows the install page."""
    return redirect(url_for("download_app"))

# ============================================================
# ERROR HANDLERS
# ============================================================
@app.errorhandler(400)
def bad_request(e):
    return jsonify({"success":False,"message":"Bad request. Please check your input."}), 400

@app.errorhandler(403)
def forbidden(e):
    return jsonify({"success":False,"message":"Access denied."}), 403

@app.errorhandler(404)
def not_found(e):
    return jsonify({"success":False,"message":"Page not found."}), 404

@app.errorhandler(413)
def too_large(e):
    return jsonify({"success":False,"message":"File too large. Max 16MB."}), 413

@app.errorhandler(429)
def too_many_requests(e):
    return jsonify({"success":False,"message":"Too many requests. Please slow down."}), 429

@app.errorhandler(500)
def server_error(e):
    return jsonify({"success":False,"message":"Server error. Please try again."}), 500

# Initialize
init_db()
ensure_admin()

if __name__=="__main__":
    port = int(os.environ.get("PORT",5000))
    print("="*55)
    print(f"  🚀 {APP_NAME} v{VERSION}")
    print(f"  🌐 URL: http://0.0.0.0:{port}")
    print(f"  👑 Admin: {ADMIN_EMAIL}")
    print(f"  🗄️  DB: {DB_PATH}")
    print("="*55)
    app.run(host="0.0.0.0", port=port, debug=False)
