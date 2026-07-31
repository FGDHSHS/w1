import requests
import concurrent.futures
import time
import datetime
import os
import json
import random
import string
import threading
from flask import Flask, request, jsonify

# ===== إعدادات الخادم =====
app = Flask(__name__)

API_KEY = os.environ.get("AI_KEY", "change-me-to-secure-key")

# ===== إعدادات البروكسي =====
PROXY_FILE = "proxy.txt"
CHECK_INTERVAL = 300
MAX_WORKERS = 50

# ===== إعدادات الحسابات =====
ACCOUNTS_FILE = "accounts.json"
MAX_ACCOUNTS = 100
ACCOUNTS_PER_PROXY = 4

# ===== النموذج المستخدم =====
MODEL = "mistralai/mistral-medium3"

# ===== أقفال للملفات =====
proxy_lock = threading.Lock()
account_lock = threading.Lock()

# ===== التحكم في الحلقات =====
running = True

# ===== سجل الأحداث (للعرض عبر API) =====
log_messages = []  # قائمة بأحدث الرسائل
MAX_LOG_ENTRIES = 50

def log(msg):
    """تسجيل رسالة مع وقت، وإضافتها إلى السجل للـ API"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{now}] {msg}"
    print(formatted)
    # إضافة للسجل المشترك
    log_messages.append(formatted)
    if len(log_messages) > MAX_LOG_ENTRIES:
        log_messages.pop(0)

# ===== دوال البروكسي (بدون تغيير) =====
def get_proxies():
    url = "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text"
    try:
        resp = requests.get(url, timeout=10)
        lines = [p.strip() for p in resp.text.strip().split("\n") if p.strip()]
        cleaned = [l.replace("http://", "").replace("https://", "") for l in lines]
        return cleaned
    except Exception as e:
        log(f"❌ فشل جلب القائمة: {e}")
        return []

def load_existing():
    if os.path.exists(PROXY_FILE):
        with open(PROXY_FILE, "r") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def test_proxy(proxy):
    try:
        r = requests.get(
            "https://httpbin.org/ip",
            proxies={"http": f"http://{proxy}", "https": f"http://{proxy}"},
            timeout=5
        )
        if r.status_code == 200:
            log(f"    ✅ يعمل: {proxy}")
            return proxy
    except Exception:
        return None
    return None

def check_list(proxies_list, label=""):
    working = []
    if not proxies_list:
        return working
    log(f"جاري فحص {len(proxies_list)} بروكسي ({label})...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = executor.map(test_proxy, proxies_list)
        for proxy, result in zip(proxies_list, results):
            if result:
                working.append(result)
    return working

def run_cycle():
    old_proxies = load_existing()
    log(f"البروكسيات المحفوظة سابقًا: {len(old_proxies)}")

    still_alive = set()
    if old_proxies:
        still_alive = set(check_list(list(old_proxies), label="قديمة"))
        dead = len(old_proxies) - len(still_alive)
        log(f"القديمة: {len(still_alive)} لسه شغالة، {dead} ماتت وتشال")

    new_list = get_proxies()
    new_working = set()
    if new_list:
        to_check = [p for p in new_list if p not in still_alive]
        new_working = set(check_list(to_check, label="جديدة"))

    final_set = still_alive | new_working

    with open(PROXY_FILE, "w") as f:
        for p in sorted(final_set):
            f.write(p + "\n")

    log(f"✅ الإجمالي المحفوظ: {len(final_set)} (قديم شغال: {len(still_alive)} | جديد: {len(new_working)})")
    log("قائمة البروكسيات الشغالة حاليًا:")
    for p in sorted(final_set):
        log(f"   • {p}")

def proxy_loop():
    log("بدء التشغيل المستمر للبروكسي 24/7...")
    while running:
        try:
            run_cycle()
        except Exception as e:
            log(f"⚠️ خطأ غير متوقع: {e}")

        log(f"انتظار {CHECK_INTERVAL} ثانية قبل الدورة القادمة...\n")
        time.sleep(CHECK_INTERVAL)

# ===== دوال إنشاء الحسابات (معدلة لضمان العدد 100 بالضبط) =====
def get_random_proxy_from_file():
    proxies = load_existing()
    if proxies:
        return random.choice(list(proxies))
    return None

def generate_random_email():
    random_string = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"{random_string}@gmail.com"

def generate_random_password():
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choices(chars, k=16))

def load_accounts():
    with account_lock:
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return []
        return []

def save_accounts(accounts):
    with account_lock:
        with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(accounts, f, indent=2, ensure_ascii=False)

def create_single_account(proxy=None):
    email = generate_random_email()
    password = generate_random_password()

    proxies = {'http': proxy, 'https': proxy} if proxy else None

    try:
        response = requests.post(
            'https://api.rewind.ai/v1/auth/signup',
            json={'email': email, 'password': password},
            headers={
                'content-type': 'application/json',
                'origin': 'https://rewind.ai',
                'referer': 'https://rewind.ai/'
            },
            proxies=proxies,
            timeout=30
        )

        if response.status_code in [200, 201]:
            login_response = requests.post(
                'https://api.rewind.ai/v1/auth/login',
                json={'email': email, 'password': password},
                headers={'content-type': 'application/json'},
                proxies=proxies,
                timeout=30
            )

            if login_response.status_code == 200:
                data = login_response.json()
                return {
                    'email': email,
                    'password': password,
                    'access_token': data.get('accessToken'),
                    'user_id': data.get('user', {}).get('id'),
                    'refresh_token': data.get('refreshToken'),
                    'proxy': proxy,
                    'created_at': datetime.datetime.now().isoformat()
                }
        return None
    except Exception:
        return None

def create_accounts_loop():
    log("🔄 بدء حلقة إدارة الحسابات (الحد الأقصى 100)...")

    while running:
        try:
            accounts = load_accounts()
            current_count = len(accounts)

            if current_count >= MAX_ACCOUNTS:
                time.sleep(30)
                continue

            needed = MAX_ACCOUNTS - current_count
            log(f"📊 عدد الحسابات الحالي: {current_count} | المطلوب إنشاء: {needed}")

            created_total = 0
            last_proxy = None

            while created_total < needed and running:
                if last_proxy is None:
                    proxy = get_random_proxy_from_file()
                    if proxy:
                        log(f"🌐 بروكسي جديد: {proxy}")
                        last_proxy = proxy
                    else:
                        log("⚠️ لا يوجد بروكسي، المحاولة بدون بروكسي...")
                        last_proxy = None
                    attempts_with_current_proxy = 0

                log(f"📝 محاولة إنشاء حساب ({created_total+1}/{needed})...")
                account = create_single_account(last_proxy)

                if account:
                    accounts.append(account)
                    save_accounts(accounts)
                    created_total += 1
                    attempts_with_current_proxy += 1
                    log(f"✅ تم إنشاء الحساب: {account['email']} | الإجمالي الآن: {len(accounts)}")

                    if attempts_with_current_proxy >= ACCOUNTS_PER_PROXY:
                        log(f"🔄 تم استخدام البروكسي {last_proxy} لإنشاء {ACCOUNTS_PER_PROXY} حسابات، التغيير لبروكسي آخر...")
                        last_proxy = None
                else:
                    log(f"❌ فشل إنشاء الحساب باستخدام البروكسي: {last_proxy} - تغيير البروكسي...")
                    last_proxy = None
                    time.sleep(random.randint(3, 7))

                time.sleep(random.randint(2, 5))

            if created_total == needed:
                log(f"🎉 تم الوصول إلى الحد الأقصى {MAX_ACCOUNTS} حساب بنجاح.")
            else:
                log(f"⚠️ تم إنشاء {created_total} من {needed} حساب. إعادة المحاولة لاحقًا.")

        except Exception as e:
            log(f"⚠️ خطأ في حلقة إنشاء الحسابات: {e}")
            time.sleep(30)

# ===== دوال التحدث مع الذكاء الاصطناعي (بدون تغيير) =====
def get_active_account():
    accounts = load_accounts()
    if not accounts:
        return None

    for account in accounts:
        try:
            response = requests.post(
                'https://api.rewind.ai/v1/chat/completions/',
                json={
                    "messages": [{"role": "user", "content": "test"}],
                    "model": MODEL,
                    "stream": False
                },
                headers={
                    'authorization': f'Bearer {account["access_token"]}',
                    'content-type': 'application/json',
                    'x-user-id': account['user_id']
                },
                timeout=10
            )

            if response.status_code == 200:
                return account
            elif response.status_code in [401, 429]:
                accounts.remove(account)
                save_accounts(accounts)
        except:
            continue

    return None

def chat_with_rewind(question, account, history=None):
    if not account:
        return "❌ لا يوجد حساب صالح"

    messages = []
    if history:
        messages = history.copy()
    messages.append({"role": "user", "content": question})

    try:
        response = requests.post(
            'https://api.rewind.ai/v1/chat/completions/',
            json={
                "messages": messages,
                "model": MODEL,
                "stream": False
            },
            headers={
                'authorization': f'Bearer {account["access_token"]}',
                'content-type': 'application/json',
                'x-user-id': account['user_id']
            },
            timeout=60
        )

        if response.status_code in [401, 429]:
            return "TOKEN_EXPIRED"

        if response.status_code != 200:
            return f"❌ خطأ: {response.status_code}"

        try:
            data = response.json()
            reply = data.get('choices', [{}])[0].get('message', {}).get('content', '')
            return reply if reply else "❌ لم يتم الحصول على رد"
        except:
            return f"❌ خطأ في التحليل: {response.text[:200]}"

    except Exception as e:
        return f"❌ خطأ: {str(e)}"

# ===== API Routes =====
@app.route('/')
def home():
    return jsonify({"status": "API is running", "model": MODEL})

@app.route('/chat', methods=['POST'])
def chat_api():
    api_key = request.headers.get('X-API-KEY')
    if not api_key or api_key != API_KEY:
        return jsonify({"error": "Invalid or missing API key"}), 403

    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({"error": "Missing 'message' in request body"}), 400

    question = data['message']
    history = data.get('history', [])

    account = get_active_account()
    if not account:
        return jsonify({"error": "No active accounts available"}), 503

    reply = chat_with_rewind(question, account, history)

    if reply == "TOKEN_EXPIRED":
        accounts = load_accounts()
        accounts = [acc for acc in accounts if acc.get('email') != account.get('email')]
        save_accounts(accounts)

        account = get_active_account()
        if account:
            reply = chat_with_rewind(question, account, history)
        else:
            return jsonify({"error": "All accounts expired"}), 503

    return jsonify({
        "reply": reply,
        "model": MODEL
    })

@app.route('/status')
def status_api():
    api_key = request.headers.get('X-API-KEY')
    if not api_key or api_key != API_KEY:
        return jsonify({"error": "Invalid or missing API key"}), 403

    accounts = load_accounts()
    proxies = load_existing()
    return jsonify({
        "accounts_count": len(accounts),
        "proxies_count": len(proxies),
        "max_accounts": MAX_ACCOUNTS,
        "model": MODEL,
        "status": "running"
    })

@app.route('/logs')
def logs_api():
    """إرجاع آخر رسائل السجل (للإطلاع على إنشاء الحسابات والبروكسيات)"""
    api_key = request.headers.get('X-API-KEY')
    if not api_key or api_key != API_KEY:
        return jsonify({"error": "Invalid or missing API key"}), 403
    return jsonify({"logs": log_messages})

# ===== تشغيل الخيوط الخلفية =====
def start_background_threads():
    proxy_thread = threading.Thread(target=proxy_loop, daemon=True)
    proxy_thread.start()
    log("✅ خيط البروكسي يعمل...")

    account_thread = threading.Thread(target=create_accounts_loop, daemon=True)
    account_thread.start()
    log("✅ خيط إنشاء الحسابات يعمل (الحد الأقصى 100)...")

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 تشغيل خادم الذكاء الاصطناعي - API 24/7")
    print("=" * 60)
    print(f"🧠 النموذج: {MODEL}")
    print(f"🔑 مفتاح API: {API_KEY}")
    print(f"📁 الحد الأقصى للحسابات: {MAX_ACCOUNTS}")
    start_background_threads()
    print("🌐 الخادم يعمل على المنفذ 10000")
    print("=" * 60)

    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
