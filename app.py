from flask import Flask, request, jsonify
import requests
import concurrent.futures
import time
import datetime
import os
import json
import random
import string
import threading

# ===== إعدادات الخادم =====
app = Flask(__name__)

# ===== إعدادات الملفات =====
PROXY_FILE = "proxy.txt"
ACCOUNTS_FILE = "accounts.json"
CHECK_INTERVAL = 300  # 5 دقائق لتحديث البروكسيات
MAX_WORKERS = 50
MAX_ACCOUNTS = 100  # الحد الأقصى لعدد الحسابات
API_KEY = "your_secret_api_key_here"  # غيّر هذا إلى مفتاح سري

# ===== النموذج المستخدم =====
MODEL = "mistralai/mistral-medium-3"

# ===== قفل للملفات =====
proxy_lock = threading.Lock()
account_lock = threading.Lock()

# ===== دوال البروكسي =====
def log(msg):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")

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
            print(f"    ✅ يعمل: {proxy}")
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

def proxy_loop():
    """حلقة البروكسي المستمرة 24/7"""
    log("بدء التشغيل المستمر للبروكسي 24/7...")
    while True:
        try:
            run_cycle()
        except Exception as e:
            log(f"⚠️ خطأ غير متوقع: {e}")
        log(f"انتظار {CHECK_INTERVAL} ثانية قبل الدورة القادمة...\n")
        time.sleep(CHECK_INTERVAL)

# ===== دوال إنشاء الحسابات =====
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
            headers={'content-type': 'application/json'},
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
    except Exception as e:
        return None

def create_accounts_loop():
    """حلقة إنشاء الحسابات - تحافظ على 100 حساب بالضبط"""
    log("🔄 بدء تشغيل حلقة إنشاء الحسابات (الحد الأقصى: 100)...")
    
    while True:
        try:
            accounts = load_accounts()
            current_count = len(accounts)
            log(f"📁 عدد الحسابات الحالية: {current_count}")
            
            if current_count < MAX_ACCOUNTS:
                # حساب عدد الحسابات المطلوب إنشاؤها للوصول إلى 100
                needed = MAX_ACCOUNTS - current_count
                log(f"📝 سيتم إنشاء {needed} حساب للوصول إلى الحد الأقصى")
                
                # إنشاء 4 حسابات فقط لكل بروكسي ناجح
                accounts_to_create = min(needed, 4)  # 4 حسابات كحد أقصى لكل دورة
                
                for i in range(accounts_to_create):
                    proxy = get_random_proxy_from_file()
                    if proxy:
                        log(f"🌐 باستخدام بروكسي: {proxy}")
                    else:
                        log("⚠️ لا يوجد بروكسي، جاري المحاولة بدون...")
                    
                    log(f"📝 إنشاء حساب {i+1}/{accounts_to_create}...")
                    account = create_single_account(proxy)
                    
                    if account:
                        accounts.append(account)
                        save_accounts(accounts)
                        log(f"✅ تم إنشاء الحساب: {account['email']}")
                        log(f"📁 إجمالي الحسابات الآن: {len(accounts)}")
                    else:
                        log(f"❌ فشل إنشاء الحساب - سيتم تغيير البروكسي تلقائياً")
                    
                    time.sleep(random.randint(3, 7))
            else:
                log("✅ تم الوصول إلى الحد الأقصى (100 حساب)")
            
            # فحص الحسابات وحذف المنتهية
            accounts = load_accounts()
            active_accounts = []
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
                        active_accounts.append(account)
                    elif response.status_code in [401, 429]:
                        log(f"⚠️ حساب منتهي: {account['email']}")
                except:
                    continue
            
            if len(active_accounts) != len(accounts):
                save_accounts(active_accounts)
                log(f"🗑️ تم حذف {len(accounts) - len(active_accounts)} حساب منتهي")
            
        except Exception as e:
            log(f"⚠️ خطأ في إنشاء الحسابات: {e}")
        
        log(f"⏳ انتظار 5 دقائق قبل الدورة القادمة...")
        time.sleep(300)

# ===== دوال التحدث مع الذكاء الاصطناعي =====
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

# ===== واجهة برمجة التطبيقات (API) =====
@app.route('/chat', methods=['POST'])
def chat():
    """استقبال طلبات المحادثة"""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "Invalid request, JSON expected"}), 400
    
    # التحقق من المفتاح
    api_key = data.get('api_key')
    if api_key != API_KEY:
        return jsonify({"error": "Invalid API key"}), 401
    
    question = data.get('message')
    if not question:
        return jsonify({"error": "Message is required"}), 400
    
    # الحصول على حساب نشط
    account = get_active_account()
    if not account:
        return jsonify({"error": "No active accounts available"}), 503
    
    # الحصول على الرد
    reply = chat_with_rewind(question, account, None)
    
    if reply == "TOKEN_EXPIRED":
        # حذف الحساب المنتهي
        accounts = load_accounts()
        accounts = [acc for acc in accounts if acc.get('email') != account.get('email')]
        save_accounts(accounts)
        return jsonify({"error": "Token expired, please try again"}), 401
    
    return jsonify({
        "response": reply,
        "account": account.get('email'),
        "status": "success"
    })

@app.route('/status', methods=['GET'])
def status():
    """عرض حالة النظام"""
    accounts = load_accounts()
    proxies = load_existing()
    
    return jsonify({
        "accounts": len(accounts),
        "proxies": len(proxies),
        "max_accounts": MAX_ACCOUNTS,
        "model": MODEL,
        "status": "running"
    })

@app.route('/health', methods=['GET'])
def health():
    """فحص صحة الخادم"""
    return jsonify({"status": "healthy"}), 200

# ===== تشغيل الخادم والخيوط الخلفية =====
def start_background_threads():
    """تشغيل الخيوط الخلفية"""
    proxy_thread = threading.Thread(target=proxy_loop, daemon=True)
    proxy_thread.start()
    log("✅ خيط البروكسي يعمل...")
    
    account_thread = threading.Thread(target=create_accounts_loop, daemon=True)
    account_thread.start()
    log("✅ خيط إنشاء الحسابات يعمل...")

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 تشغيل خادم الذكاء الاصطناعي")
    print("=" * 60)
    print("🔄 جلب بروكسيات وفحصها...")
    print("🔄 إنشاء حسابات (الحد الأقصى: 100)...")
    print("🧠 النموذج: Mistral Medium 3.5")
    print("🌐 الخادم يعمل على المنفذ 10000")
    print("=" * 60)
    
    # تشغيل الخيوط الخلفية
    start_background_threads()
    
    # عرض الحالة
    accounts = load_accounts()
    proxies = load_existing()
    print(f"📁 عدد الحسابات: {len(accounts)}")
    print(f"🌐 عدد البروكسيات: {len(proxies)}")
    print("=" * 60)
    
    # تشغيل الخادم
    app.run(host='0.0.0.0', port=10000)
