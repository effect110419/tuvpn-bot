import sys
sys.path.insert(0, '/root')
sys.path.insert(0, '/root/tuvpn')
from server_installer import create_installation, start_installation_thread, REALITY_TARGET_CANDIDATES
from flask import Flask, request, jsonify, Response
import requests, json, uuid, base64
import asyncio, time, os
from collections import defaultdict, deque
from datetime import datetime, timedelta
from config import PANEL_URL, PANEL_USER, PANEL_PASS, INBOUND_ID, SERVER_IP, SUB_BASE_URL
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
import urllib3
import threading
urllib3.disable_warnings()

# === ШИФРОВАНИЕ ПАРОЛЕЙ ПАНЕЛЕЙ (П.6) ===
try:
    from cryptography.fernet import Fernet as _Fernet
    _PANEL_ENC_KEY = os.environ.get('PANEL_ENCRYPTION_KEY', '').strip()
    _fernet = _Fernet(_PANEL_ENC_KEY.encode()) if _PANEL_ENC_KEY else None
except Exception:
    _fernet = None

def decrypt_panel_password(raw: str) -> str:
    """Расшифровывает пароль панели если зашифрован (Fernet-формат)."""
    if _fernet and raw and raw.startswith('gAAAAA'):
        try:
            return _fernet.decrypt(raw.encode()).decode()
        except Exception:
            pass
    return raw

def encrypt_panel_password(raw: str) -> str:
    """Шифрует пароль панели для хранения в БД."""
    if _fernet and raw and not raw.startswith('gAAAAA'):
        return _fernet.encrypt(raw.encode()).decode()
    return raw

app = Flask(__name__)
# ─── CORS для админки ───
from flask import make_response

@app.after_request
def add_cors_headers(response):
    if request.path.startswith('/admin-api/'):
        origin = request.headers.get('Origin', '')
        # Allow конкретный origin (нужно для credentials/cookies)
        if origin:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Vary'] = 'Origin'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Cookie'
        response.headers['Access-Control-Max-Age'] = '3600'
    return response

@app.route('/admin-api/<path:path>', methods=['OPTIONS'])
def handle_admin_options(path):
    return make_response('', 204)

# === RATE LIMITING (П.3) ===
_rl_store: dict = defaultdict(deque)
_rl_lock = threading.Lock()

def _check_rate(ip: str, group: str, max_req: int, window: int) -> bool:
    """True — запрос разрешён. False — лимит превышен."""
    key = f"{ip}:{group}"
    now = time.monotonic()
    with _rl_lock:
        dq = _rl_store[key]
        while dq and dq[0] < now - window:
            dq.popleft()
        if len(dq) >= max_req:
            return False
        dq.append(now)
        return True

@app.before_request
def rate_limit():
    path = request.path
    ip = (request.headers.get('X-Real-IP') or
          request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or
          request.remote_addr or 'unknown')
    # Auth: 10 запросов/минуту
    if path.startswith('/admin-api/auth/'):
        if not _check_rate(ip, 'auth', 10, 60):
            return jsonify({"error": "rate_limited", "retry_after": 60}), 429
    # Подписка: 60 запросов/минуту с одного IP
    elif path.startswith('/sub/'):
        if not _check_rate(ip, 'sub', 60, 60):
            return jsonify({"error": "rate_limited"}), 429
    # Webhook ЮКассы: 30/мин
    elif path == '/yookassa/webhook':
        if not _check_rate(ip, 'wh', 30, 60):
            return jsonify({"error": "rate_limited"}), 429
    # Admin API: 180 запросов/минуту
    elif path.startswith('/admin-api/'):
        if not _check_rate(ip, 'adm', 180, 60):
            return jsonify({"error": "rate_limited", "retry_after": 60}), 429
# ─────────────────────────
PUBLIC_KEY = "9q2JxVMnpr1nvhK407R0ymy5k-W_tyE_iEvSLJTXWg8"
SHORT_ID = "d1a247d5a8"
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ====================== MULTI-SERVER HELPERS ======================
def get_active_servers():
    """Получить список активных серверов из Supabase (sort_order ASC)"""
    try:
        r = sb.table("servers").select("*").eq("is_active", True).order("sort_order").execute()
        return r.data or []
    except Exception as e:
        print(f"get_active_servers error: {e}")
        return []


def xui_session(server=None):
    """Логинится в 3X-UI и сохраняет CSRF-токен в session.headers для всех POST.

    Стратегия:
    1. GET / — получаем cookie + CSRF-токен из <meta name="csrf-token">
    2. POST /login с CSRF в заголовке + cookies
    3. Если успех — CSRF остаётся в session.headers, и все следующие POST его используют

    Совместимо со старой версией: если CSRF нет в HTML, идём напрямую с JSON.
    """
    import re as _re
    if server is None:
        servers = get_active_servers()
        if servers:
            server = servers[0]
        else:
            server = {
                "panel_url": PANEL_URL,
                "panel_login": PANEL_USER,
                "panel_password": PANEL_PASS,
                "inbound_id": INBOUND_ID,
                "country_name": "Finland",
            }
    session = requests.Session()
    session.verify = False
    url = server["panel_url"].rstrip("/")
    creds = {"username": server["panel_login"], "password": decrypt_panel_password(server["panel_password"])}

    # Получаем CSRF-токен (если новая версия) + cookies
    csrf = None
    try:
        get_resp = session.get(f"{url}/", timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        })
        if get_resp.status_code == 200:
            m = _re.search(r'name="csrf-token"\s+content="([^"]+)"', get_resp.text)
            if m:
                csrf = m.group(1)
                app.logger.info(f"xui_session({server.get('country_name')}): got CSRF token")
    except Exception as e:
        app.logger.warning(f"xui_session: GET / failed: {e}")

    # Базовые заголовки для всех запросов сессии
    base_headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Origin": url.split("/", 3)[0] + "//" + url.split("/", 3)[2],
        "Referer": f"{url}/",
    }
    if csrf:
        base_headers["X-CSRF-Token"] = csrf

    # Применяем базовые заголовки к сессии — они будут шириться на все POST
    session.headers.update(base_headers)

    # Логинимся
    try:
        if csrf:
            # Новая версия — form-data POST
            resp = session.post(f"{url}/login", data=creds, timeout=10)
        else:
            # Старая версия — JSON POST
            resp = session.post(f"{url}/login", json=creds, timeout=10)
        if resp.status_code == 200:
            try:
                body = resp.json()
                if body.get("success"):
                    return session, server
            except Exception:
                pass
        # Fallback: если первый способ упал, пробуем альтернативный
        if csrf:
            resp = session.post(f"{url}/login", json=creds, timeout=10)
        else:
            resp = session.post(f"{url}/login", data=creds, timeout=10)
        if resp.status_code == 200:
            try:
                body = resp.json()
                if body.get("success"):
                    return session, server
            except Exception:
                pass
        raise Exception(f"Login failed on {server.get('country_name', 'server')}: HTTP {resp.status_code}, body={resp.text[:200]}")
    except Exception as e:
        raise Exception(f"Login failed on {server.get('country_name', 'server')}: {e}")


def _v3_session(server):
    """Bearer-сессия для 3X-UI 3.x. Возвращает (session, url, inbound_id)."""
    session = requests.Session()
    session.verify = False
    token = (server.get("api_token") or "").strip()
    if not token:
        return None, None, None
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    url = server["panel_url"].rstrip("/")
    iid = int(server.get("inbound_id") or 1)
    return session, url, iid


def xui_v3_list_uuids(server):
    """Возвращает set UUID клиентов на сервере v3. None если не удалось."""
    session, url, iid = _v3_session(server)
    if not session:
        return None
    try:
        r = session.get(f"{url}/panel/api/inbounds/get/{iid}", timeout=15)
        if r.status_code != 200:
            return None
        obj = r.json().get("obj", {})
        st = obj.get("settings")
        st = json.loads(st) if isinstance(st, str) else (st or {})
        return set(c.get("id") for c in st.get("clients", []) if c.get("id"))
    except Exception:
        return None


def xui_v3_add_client(server, client_uuid, uid, devices, expire_ms, skip_check=False):
    """3.x: POST /panel/api/clients/add. Идемпотентно: проверяет дубликат."""
    session, url, iid = _v3_session(server)
    if not session:
        return False, "no api_token"
    if not skip_check:
        existing = xui_v3_list_uuids(server)
        if existing is not None and client_uuid in existing:
            return True, "already exists"
    payload = {
        "inboundIds": [iid],
        "client": {
            "id": client_uuid,
            "email": f"user_{uid}",
            "limitIp": devices,
            "totalGB": 0,
            "expiryTime": expire_ms,
            "enable": True,
            "flow": "xtls-rprx-vision",
        }
    }
    try:
        r = session.post(f"{url}/panel/api/clients/add", json=payload, timeout=15)
        try:
            jr = r.json()
        except Exception:
            return False, f"non-json {r.status_code}: {r.text[:100]}"
        if jr.get("success"):
            return True, "ok"
        msg = (jr.get("msg") or "").lower()
        if "already" in msg or "exists" in msg or "duplicate" in msg:
            return True, "already exists (by msg)"
        return False, jr.get("msg", f"http {r.status_code}")
    except Exception as e:
        return False, str(e)[:150]


def xui_v3_del_client(server, client_uuid):
    """3.x: удалить клиента — пробует несколько вариантов API."""
    session, url, iid = _v3_session(server)
    if not session:
        return False, "no api_token"
    payload = {"inboundIds": [iid]}
    for method, path in [
        ("DELETE", f"/panel/api/clients/{client_uuid}"),
        ("POST", f"/panel/api/clients/delete/{client_uuid}"),
        ("POST", f"/panel/api/inbounds/{iid}/delClient/{client_uuid}"),
    ]:
        try:
            r = session.request(method, f"{url}{path}", json=payload, timeout=15)
            try:
                jr = r.json()
                if jr.get("success"):
                    return True, "ok"
            except Exception:
                pass
        except Exception:
            continue
    return False, "no working del endpoint"


def xui_v3_update_client(server, client_uuid, uid, devices, expire_ms):
    """3.x: обновить клиента — del → add."""
    existing = xui_v3_list_uuids(server)
    if existing is None:
        return xui_v3_add_client(server, client_uuid, uid, devices, expire_ms)
    if client_uuid in existing:
        del_ok, del_msg = xui_v3_del_client(server, client_uuid)
        if not del_ok:
            print(f"[{server.get('country_name','?')}] v3 del failed ({del_msg}), trying add anyway")
        return xui_v3_add_client(server, client_uuid, uid, devices, expire_ms, skip_check=True)
    return xui_v3_add_client(server, client_uuid, uid, devices, expire_ms, skip_check=True)


def xui_add_client_on_server(server, client_uuid, uid, devices, expire_ms):
    """Создаёт клиента на одном сервере. True если успешно."""
    # v3 (Bearer-токен)
    if (server.get("api_token") or "").strip():
        ok, msg = xui_v3_add_client(server, client_uuid, uid, devices, expire_ms)
        if ok:
            print(f"[{server.get('country_name')}] addClient v3 {client_uuid[:8]} OK")
        else:
            print(f"[{server.get('country_name')}] addClient v3 {client_uuid[:8]} FAIL: {msg}")
        return ok
    # v2 (cookie-сессия)
    try:
        session, server = xui_session(server)
        ts = int(datetime.utcnow().timestamp())
        payload = {
            "id": int(server["inbound_id"]),
            "settings": json.dumps({"clients": [{
                "id": client_uuid,
                "email": f"user_{uid}_{ts}",
                "limitIp": devices,
                "totalGB": 0,
                "expiryTime": expire_ms,
                "enable": True,
                "flow": "xtls-rprx-vision",
            }]}),
        }
        url = server["panel_url"].rstrip("/")
        r = session.post(f"{url}/panel/api/inbounds/addClient", json=payload, timeout=15)
        result = r.json()
        if result.get("success"):
            print(f"[{server.get('country_name')}] addClient {client_uuid[:8]} OK")
            return True
        print(f"[{server.get('country_name')}] addClient failed: {result}")
    except Exception as e:
        print(f"[{server.get('country_name', '?')}] add_client error: {e}")
    return False


def xui_update_client_on_server(server, client_uuid, uid, devices, expire_ms):
    """Обновляет клиента на одном сервере. Если его нет — добавляет."""
    # v3 (Bearer-токен)
    if (server.get("api_token") or "").strip():
        ok, msg = xui_v3_update_client(server, client_uuid, uid, devices, expire_ms)
        if ok:
            print(f"[{server.get('country_name')}] updateClient v3 {client_uuid[:8]} OK")
        else:
            print(f"[{server.get('country_name')}] updateClient v3 {client_uuid[:8]} FAIL: {msg}")
        return ok
    # v2 (cookie-сессия)
    try:
        session, server = xui_session(server)
        ts = int(datetime.utcnow().timestamp())
        payload = {
            "id": int(server["inbound_id"]),
            "settings": json.dumps({"clients": [{
                "id": client_uuid,
                "email": f"user_{uid}_{ts}",
                "limitIp": devices,
                "totalGB": 0,
                "expiryTime": expire_ms,
                "enable": True,
                "flow": "xtls-rprx-vision",
            }]}),
        }
        url = server["panel_url"].rstrip("/")
        r = session.post(f"{url}/panel/api/inbounds/updateClient/{client_uuid}", json=payload, timeout=15)
        result = r.json()
        if result.get("success"):
            print(f"[{server.get('country_name')}] updateClient {client_uuid[:8]} OK")
            return True
        print(f"[{server.get('country_name')}] updateClient failed ({result.get('msg', '')}) — trying addClient")
        return xui_add_client_on_server(server, client_uuid, uid, devices, expire_ms)
    except Exception as e:
        print(f"[{server.get('country_name', '?')}] update_client error: {e}")
    return False


def xui_disable_client_on_server(server, client_uuid, enable=False):
    """Включает или выключает клиента на сервере (enable: True/False)."""
    try:
        session, srv = xui_session(server)
        url = srv["panel_url"].rstrip("/")
        r = session.get(f"{url}/xui/API/inbounds/list", timeout=10)
        data = r.json()
        for inbound in data.get("obj", []):
            if int(inbound.get("id", 0)) != int(srv["inbound_id"]):
                continue
            settings_raw = inbound.get("settings", "{}")
            settings = settings_raw if isinstance(settings_raw, dict) else json.loads(settings_raw)
            for c in settings.get("clients", []):
                if c.get("id") == client_uuid:
                    c["enable"] = enable
                    payload = {
                        "id": int(srv["inbound_id"]),
                        "settings": json.dumps({"clients": [c]}),
                    }
                    r2 = session.post(f"{url}/panel/api/inbounds/updateClient/{client_uuid}", json=payload, timeout=15)
                    result = r2.json()
                    return result.get("success", False)
        return False
    except Exception as e:
        print(f"[{server.get('country_name', '?')}] disable_client error: {e}")
        return False


def get_client_expire(client_uuid):
    """Получить дату истечения клиента в Unix timestamp (секунды).
    Берёт expiryTime с первого сервера где клиент найден."""
    servers = get_active_servers()
    if not servers:
        return 0
    for server in servers:
        try:
            session, _ = xui_session(server)
            url = server["panel_url"].rstrip("/")
            r = session.get(f"{url}/xui/API/inbounds/list", timeout=10)
            data = r.json()
            for inbound in data.get("obj", []):
                if int(inbound.get("id", 0)) != int(server["inbound_id"]):
                    continue
                settings_raw = inbound.get("settings", "{}")
                settings = settings_raw if isinstance(settings_raw, dict) else json.loads(settings_raw)
                for client in settings.get("clients", []):
                    if client.get("id") == client_uuid:
                        return client.get("expiryTime", 0) // 1000
        except Exception as e:
            print(f"get_client_expire on {server.get('country_name')}: {e}")
            continue
    return 0


def get_existing_client(uid):
    """Возвращает постоянный UUID пользователя и последнюю запись подписки.

    UUID берётся из users.client_uuid — задаётся один раз при первой выдаче
    и больше никогда не меняется, даже если подписка истекла и была возобновлена.
    sub_id — последняя запись в subscriptions (активная или нет) для UPDATE вместо INSERT.
    """
    try:
        # Постоянный canonical UUID хранится в users — не меняется после первой выдачи
        u = sb.table("users").select("client_uuid").eq("user_id", uid).limit(1).execute()
        canonical_uuid = (u.data[0].get("client_uuid") or None) if u.data else None

        # Последняя запись подписки (активная или нет) — чтобы UPDATE вместо INSERT
        r = (sb.table("subscriptions").select("*")
               .eq("user_id", uid)
               .order("created_at", desc=True)
               .limit(1).execute())

        if r.data:
            sub = r.data[0]
            # Фолбэк: если canonical_uuid ещё не задан — берём из sub_url
            if not canonical_uuid and "/sub/" in sub.get("sub_url", ""):
                canonical_uuid = sub["sub_url"].split("/sub/")[-1]
            return sub["id"], canonical_uuid, sub.get("devices", 1)

        return None, canonical_uuid, 1
    except Exception:
        pass
    return None, None, None


def detect_device_type(ua: str) -> str:
    """Парсит User-Agent и возвращает 'ios' / 'android' / 'pc' / 'unknown'."""
    if not ua:
        return "unknown"
    ua_low = ua.lower()
    if any(k in ua_low for k in ["iphone", "ipad", "ios", "darwin"]):
        return "ios"
    if "android" in ua_low:
        return "android"
    if any(k in ua_low for k in ["windows", "macintosh", "linux", "x11"]):
        return "pc"
    if "happ" in ua_low:
        return "ios"  # Happ Plus в основном iOS
    if "v2ray" in ua_low:
        return "android"
    return "unknown"


def make_device_name(ua: str, dtype: str, device_model: str = None) -> str:
    """Формирует читаемое имя устройства.
    Если есть реальная модель из заголовка Happ (x-device-model) — используем её.
    Иначе fallback на платформу + версию из UA.
    """
    icons = {"ios": "🍏", "android": "🤖", "pc": "💻", "unknown": "📱"}
    icon = icons.get(dtype, "📱")
    if device_model and device_model.strip():
        return f"{icon} {device_model.strip()}"
    # Fallback — старая логика
    labels = {"ios": "iPhone/iPad", "android": "Android", "pc": "ПК", "unknown": "Устройство"}
    name = f"{icon} {labels.get(dtype, 'Устройство')}"
    import re as _re
    m = _re.search(r"(iOS|Android|Windows|Mac OS X)[ /]?(\d+[\d._]*)", ua or "", _re.IGNORECASE)
    if m:
        name += f" · {m.group(1)} {m.group(2).replace('_', '.')}"
    return name


# === DEVICE TRACKING FIX 2026-05 ===
# Окно "активности" устройства: запись считается активной если last_seen в этом окне
DEVICE_ACTIVITY_WINDOW_DAYS = 7


def _is_preview_ua(ua: str) -> bool:
    """True если UA — это превью-бот/краулер (превью ссылки в чате, не реальный клиент)."""
    if not ua:
        return False
    low = ua.lower()
    preview_markers = (
        "telegrambot", "twitterbot", "vkshare", "facebookexternalhit",
        "whatsapp", "bot", "preview", "crawler", "spider",
    )
    vpn_markers = ("happ", "v2ray", "v2box", "streisand", "shadowrocket",
                   "nekobox", "hiddify", "sing-box", "clash")
    has_vpn = any(m in low for m in vpn_markers)
    if has_vpn:
        return False  # реальный VPN-клиент — не превью
    # голый Mozilla/браузер без VPN-клиента — это превью/браузерный заход
    if "mozilla" in low or any(m in low for m in preview_markers):
        return True
    return False


def _detect_platform(ua: str) -> str:
    """Извлекает платформу из UA в любом формате."""
    low = (ua or "").lower()
    if "ios" in low or "iphone" in low or "ipad" in low or "mac os" in low or "macos" in low:
        return "ios"
    if "android" in low:
        return "android"
    if "windows" in low or "win64" in low or "win32" in low or "nt 10" in low:
        return "win"
    if "linux" in low:
        return "linux"
    return "unknown"


def _detect_client(ua: str) -> str:
    """Извлекает имя клиента из UA."""
    low = (ua or "").lower()
    for c in ("happ", "v2raytun", "v2rayng", "v2box", "streisand",
              "shadowrocket", "nekobox", "hiddify", "sing-box", "clash"):
        if c in low:
            return c.replace("-", "")
    return "client"


def _normalize_ua(ua: str) -> str:
    """Стабильный идентификатор устройства: client/platform.
    Не зависит от версии приложения и внутреннего device-id, которые
    меняются при обновлении/переустановке. Один физический телефон с одним
    VPN-клиентом = один ключ.
    Примеры:
        Happ/3.20.4/Android/177...   -> happ/android
        Happ/4.10.1/ios/260...       -> happ/ios
        Happ/2.0 iPhone iOS 17.5     -> happ/ios
        v2raytun/android             -> v2raytun/android
        V2Box 9.8.9;IOS 26.4.2       -> v2box/ios
    """
    if not ua:
        return "unknown"
    client = _detect_client(ua)
    platform = _detect_platform(ua)
    return f"{client}/{platform}"


# === HWID DEVICE TRACKING 2026-05 ===
def track_device(client_uuid: str, client_ip: str, user_agent: str,
                 hwid: str = None, device_model: str = None,
                 device_os: str = None, os_version: str = None) -> dict:
    """
    Регистрирует/обновляет устройство при обращении к подписке.
    Возвращает {"allowed": bool, "reason": str, "device_id": int|None}.

    Логика 2026-05:
    1. Устройство идентифицируется по (client_uuid, normalized_user_agent).
       IP может меняться (мобильный интернет, Wi-Fi/4G переключения) — НЕ считаем это новым устройством.
    2. Подсчёт активных устройств — только тех, у кого last_seen в последние
       DEVICE_ACTIVITY_WINDOW_DAYS дней. Старые записи остаются в БД, но не
       блокируют новых подключений.
    3. Игнорируем запросы от Telegram-бота (превью ссылки в чате).
    4. На любую ошибку — разрешаем (lose mode), чтобы не сломать сервис юзерам.
    """
    try:
        # Игнорируем preview-запросы (превью ссылки в чате/соцсетях, не реальный клиент)
        if _is_preview_ua(user_agent):
            return {"allowed": True, "reason": "preview_ignored", "device_id": None}

        # Находим подписку
        sub_q = (
            sb.table("subscriptions")
            .select("*").eq("status", "active")
            .like("sub_url", f"%{client_uuid}")
            .limit(1).execute()
        )
        if not sub_q.data:
            return {"allowed": False, "reason": "subscription_not_found", "device_id": None}
        sub = sub_q.data[0]
        user_id = sub["user_id"]
        device_limit = sub.get("devices", 1)

        normalized_ua = _normalize_ua(user_agent)
        now_iso = datetime.utcnow().isoformat()

        # Идентификатор устройства: HWID (приоритет) → fallback на платформу (UA).
        # HWID стабилен (железо); платформа стабильна при обновлении приложения.
        device_key_ua_platform = normalized_ua  # = client/platform
        device_key = (hwid or "").strip() or normalized_ua

        all_devs_q = (
            sb.table("user_devices").select("*")
            .eq("user_id", user_id)
            .eq("client_uuid", client_uuid)
            .execute()
        )
        all_devs = all_devs_q.data or []

        def _dev_key(d):
            return (d.get("hwid") or "").strip() or _normalize_ua(d.get("user_agent") or "")

        existing_dev = None
        for d in all_devs:
            if _dev_key(d) == device_key:
                existing_dev = d
                break

        if existing_dev:
            # Знакомое устройство — обновляем (IP/модель/ОС могли уточниться)
            upd = {
                "ip_address": client_ip,
                "last_seen": now_iso,
                "is_active": True,
                "user_agent": (user_agent or "")[:500],
            }
            if hwid: upd["hwid"] = hwid[:100]
            if device_model: upd["device_model"] = device_model[:100]
            if device_os: upd["device_os"] = device_os[:50]
            if os_version: upd["os_version"] = os_version[:50]
            # Обновим красивое имя если модель появилась
            if device_model:
                dtype = detect_device_type(user_agent) if not device_os else (
                    "ios" if "ios" in (device_os or "").lower() else
                    "android" if "android" in (device_os or "").lower() else
                    detect_device_type(user_agent))
                upd["device_name"] = make_device_name(user_agent, dtype, device_model)
            sb.table("user_devices").update(upd).eq("id", existing_dev["id"]).execute()
            return {"allowed": True, "reason": "refreshed", "device_id": existing_dev["id"]}

        # РЕКОНСИЛЯЦИЯ: пришёл hwid, точного матча нет, но есть осиротевшая
        # запись БЕЗ hwid той же платформы — это то же устройство (Happ обновился
        # и начал слать hwid). Обновляем её, а не плодим дубль.
        if hwid:
            for d in all_devs:
                if (d.get("hwid") or "").strip():
                    continue
                if _normalize_ua(d.get("user_agent") or "") == device_key_ua_platform:
                    upd2 = {
                        "hwid": hwid[:100],
                        "ip_address": client_ip,
                        "last_seen": now_iso,
                        "is_active": True,
                        "user_agent": (user_agent or "")[:500],
                    }
                    if device_model: upd2["device_model"] = device_model[:100]
                    if device_os: upd2["device_os"] = device_os[:50]
                    if os_version: upd2["os_version"] = os_version[:50]
                    if device_model:
                        _dt2 = ("ios" if "ios" in (device_os or "").lower() else
                                "android" if "android" in (device_os or "").lower() else
                                detect_device_type(user_agent))
                        upd2["device_name"] = make_device_name(user_agent, _dt2, device_model)
                    sb.table("user_devices").update(upd2).eq("id", d["id"]).execute()
                    return {"allowed": True, "reason": "reconciled_hwid", "device_id": d["id"]}

        # Новое устройство — проверим лимит, считая только активных за окно
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=DEVICE_ACTIVITY_WINDOW_DAYS)).isoformat()

        active_recent_q = (
            sb.table("user_devices").select("user_agent,hwid")
            .eq("user_id", user_id)
            .eq("is_active", True)
            .gte("last_seen", cutoff)
            .execute()
        )
        # Уникальные устройства по device_key (HWID или нормализованный UA)
        unique_keys = set()
        for d in (active_recent_q.data or []):
            k = (d.get("hwid") or "").strip() or _normalize_ua(d.get("user_agent") or "")
            unique_keys.add(k)
        active_count = len(unique_keys)

        if active_count >= device_limit:
            app.logger.warning(
                f"Device limit exceeded: user={user_id} limit={device_limit} "
                f"unique_active={active_count} IP={client_ip} UA={normalized_ua}"
            )
            return {"allowed": False, "reason": "limit_exceeded", "device_id": None}

        # Добавляем новое устройство
        if device_os:
            dtype = ("ios" if "ios" in device_os.lower() else
                     "android" if "android" in device_os.lower() else
                     detect_device_type(user_agent))
        else:
            dtype = detect_device_type(user_agent)
        dname = make_device_name(user_agent, dtype, device_model)
        new_dev = sb.table("user_devices").insert({
            "user_id": user_id,
            "device_name": dname,
            "device_type": dtype,
            "device_info": (user_agent or "")[:200],
            "client_uuid": client_uuid,
            "ip_address": client_ip,
            "user_agent": (user_agent or "")[:500],
            "hwid": (hwid or None) and hwid[:100],
            "device_model": (device_model or None) and device_model[:100],
            "device_os": (device_os or None) and device_os[:50],
            "os_version": (os_version or None) and os_version[:50],
            "connected_at": now_iso,
            "last_seen": now_iso,
            "is_active": True,
        }).execute()
        dev_id = new_dev.data[0]["id"] if new_dev.data else None
        app.logger.info(f"New device tracked: user={user_id} IP={client_ip} type={dtype} UA={normalized_ua} id={dev_id}")
        return {"allowed": True, "reason": "added", "device_id": dev_id}
    except Exception as e:
        app.logger.error(f"track_device error: {e}")
        # Lose mode: при любой ошибке — разрешаем, чтобы не блокировать юзеров
        return {"allowed": True, "reason": "error_allow_anyway", "device_id": None}


@app.route('/sub/<client_uuid>')
def subscription(client_uuid):
    """Отдать подписку клиенту — JSON-массив конфигов для всех активных серверов.
    Также регистрирует устройство по IP и проверяет лимит."""
    import json as _json
    import subscription_generator

    # IP клиента (учитываем nginx прокси)
    client_ip = (request.headers.get('X-Real-IP') or
                 request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or
                 request.remote_addr or "unknown")
    user_agent = request.headers.get('User-Agent', '')
    # Заголовки Happ для идентификации устройства
    hwid = request.headers.get('X-Hwid', '') or request.headers.get('x-hwid', '')
    device_model = request.headers.get('X-Device-Model', '') or request.headers.get('x-device-model', '')
    device_os = request.headers.get('X-Device-Os', '') or request.headers.get('x-device-os', '')
    os_version = request.headers.get('X-Ver-Os', '') or request.headers.get('x-ver-os', '')

    # Внутренняя проверка аудита — не трекаем устройство, не проверяем лимит
    _INTERNAL_IPS = {"127.0.0.1", "188.214.107.107"}
    is_audit = (
        request.headers.get("X-Audit-Internal") == "1"
        and client_ip in _INTERNAL_IPS
    )

    if is_audit:
        # Просто убеждаемся что подписка существует, затем отдаём конфиги
        chk = (sb.table("subscriptions").select("user_id")
               .eq("status", "active").like("sub_url", f"%{client_uuid}").limit(1).execute())
        if not chk.data:
            return Response("Subscription not found", status=404)
    else:
        # Регистрация устройства / проверка лимита
        track_result = track_device(client_uuid, client_ip, user_agent,
                                    hwid=hwid, device_model=device_model,
                                    device_os=device_os, os_version=os_version)
        if not track_result["allowed"]:
            if track_result["reason"] == "limit_exceeded":
                app.logger.info(f"Subscription blocked (limit): {client_uuid} from {client_ip}")
                return Response("Device limit exceeded for this subscription", status=403)
            if track_result["reason"] == "subscription_not_found":
                # UUID от старой (истёкшей) подписки — ищем активную у того же пользователя
                old_sub_q = (sb.table("subscriptions").select("user_id")
                               .like("sub_url", f"%{client_uuid}").limit(1).execute())
                redirected = False
                if old_sub_q.data:
                    uid_owner = old_sub_q.data[0]["user_id"]
                    active_q = (sb.table("subscriptions").select("sub_url")
                                  .eq("user_id", uid_owner).eq("status", "active").limit(1).execute())
                    if active_q.data:
                        new_url = active_q.data[0].get("sub_url", "")
                        if "/sub/" in new_url:
                            new_uuid = new_url.split("/sub/")[-1]
                            app.logger.info(
                                f"sub redirect: old {client_uuid[:8]} → active {new_uuid[:8]} "
                                f"user={uid_owner}"
                            )
                            client_uuid = new_uuid
                            # повторно трекаем с новым UUID
                            track_result = track_device(client_uuid, client_ip, user_agent,
                                                        hwid=hwid, device_model=device_model,
                                                        device_os=device_os, os_version=os_version)
                            if not track_result["allowed"]:
                                if track_result["reason"] == "limit_exceeded":
                                    return Response("Device limit exceeded for this subscription", status=403)
                                return Response("Subscription not found", status=404)
                            redirected = True
                if not redirected:
                    return Response("Subscription not found", status=404)

    # Получаем активные серверы
    try:
        srv = sb.table("servers").select("*").eq("is_active", True).order("sort_order").execute()
        servers = srv.data or []
    except Exception as e:
        app.logger.error(f"Servers fetch error: {e}")
        servers = []
    if not servers:
        return Response("No active servers", status=503)

    expire_ts = get_client_expire(client_uuid)
    common_headers = {
        "profile-title": "TuVPN",
        "profile-update-interval": "6",
        "support-url": "https://t.me/MaxArtVPN_bot",
        "subscription-userinfo": f"upload=0; download=0; total=0; expire={expire_ts}",
    }

    # Happ определяется по своим кастомным заголовкам — только он присылает X-Hwid.
    # Happ ожидает полный JSON Xray-конфиг с правилами маршрутизации.
    # Все остальные клиенты (Изи VPN, Shadowrocket, V2RayNG и т.д.) используют
    # стандартный формат: base64-строка из vless:// URI.
    is_happ = bool(hwid)
    if is_happ:
        announcement_b64 = "4pqg77iPINCd0LUg0YDQsNCx0L7RgtCw0LXRgj8g0J3QsNC20LzQuCDwn5SEINC4INCy0YvQsdC10YDQuCDQtNGA0YPQs9GD0Y4g0LvQvtC60LDRhtC40Y4uIPCfk4Ug0J/RgNC+0LTQu9C10LLQsNC5INC30LDRgNCw0L3QtdC1IOKAlCBUZWxlZ3JhbSDQt9Cw0LzQtdC00LvRj9GO0YIh"
        configs = subscription_generator.build_subscription(servers, client_uuid)
        body = _json.dumps(configs, ensure_ascii=False, separators=(",", ":"))
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            **common_headers,
            "announce": "base64:" + announcement_b64,
        }
        return Response(body, headers=headers)

    body = subscription_generator.build_vless_subscription(servers, client_uuid)
    headers = {"Content-Type": "text/plain; charset=utf-8", **common_headers}
    return Response(body, headers=headers)




# === SERVER SYNC (backfill clients) ===
def get_server_by_id(server_id: int):
    """Получить сервер из Supabase по id (возвращает dict или None)."""
    try:
        r = sb.table("servers").select("*").eq("id", server_id).limit(1).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        print(f"get_server_by_id error: {e}")
        return None


def backfill_server_clients(server: dict) -> dict:
    """
    Раскатать все активные подписки на указанный сервер.
    Использует xui_update_client_on_server (он же делает fallback на add).
    Возвращает {"total": N, "ok": K, "failed": F, "failures": [...]}.
    """
    code = server.get("code") or server.get("country_name") or f"id={server.get('id')}"
    print(f"[sync] Backfill начат для {code}")

    # Все активные подписки
    try:
        subs_r = sb.table("subscriptions").select("user_id,devices,sub_url,expires_at").eq("status", "active").execute()
        subs = subs_r.data or []
    except Exception as e:
        return {"total": 0, "ok": 0, "failed": 0, "failures": [], "error": f"db: {e}"}

    total = len(subs)
    ok = 0
    failed = 0
    failures = []
    now = datetime.utcnow()

    for sub in subs:
        try:
            url = sub.get("sub_url") or ""
            if "/sub/" not in url:
                failed += 1
                failures.append({"user_id": sub.get("user_id"), "error": "no uuid in sub_url"})
                continue
            client_uuid = url.split("/sub/")[-1].strip()
            uid = int(sub["user_id"])
            devices = int(sub.get("devices") or 1)

            # expires_at → ms
            exp_raw = sub.get("expires_at")
            try:
                exp_dt = datetime.fromisoformat(exp_raw.replace("Z", "+00:00")).replace(tzinfo=None) if exp_raw else (now + timedelta(days=30))
            except Exception:
                exp_dt = now + timedelta(days=30)
            if exp_dt <= now:
                # уже истекла — пропустим, не имеет смысла раскатывать
                failed += 1
                failures.append({"user_id": uid, "error": "subscription expired"})
                continue
            expire_ms = int(exp_dt.timestamp() * 1000)

            success = xui_update_client_on_server(server, client_uuid, uid, devices, expire_ms)
            if success:
                ok += 1
            else:
                failed += 1
                failures.append({"user_id": uid, "uuid": client_uuid[:8], "error": "xui rejected"})
        except Exception as e:
            failed += 1
            failures.append({"user_id": sub.get("user_id"), "error": str(e)})

    print(f"[sync] Backfill {code}: {ok}/{total} OK, {failed} failed")
    return {"total": total, "ok": ok, "failed": failed, "failures": failures[:20]}


@app.route('/admin-api/servers/<int:server_id>/sync', methods=['POST', 'OPTIONS'])
def admin_sync_server(server_id):
    """Синхронизировать один сервер (раскатать все активные подписки на нём)."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    server = get_server_by_id(server_id)
    if not server:
        return jsonify({"success": False, "error": "server not found"}), 404
    if not server.get("is_active"):
        return jsonify({"success": False, "error": "server is not active"}), 400
    try:
        result = backfill_server_clients(server)
        return jsonify({"success": True, "server_id": server_id, "code": server.get("code"), **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/servers/sync_all', methods=['POST', 'OPTIONS'])
def admin_sync_all_servers():
    """Синхронизировать все активные серверы."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    servers = get_active_servers()
    if not servers:
        return jsonify({"success": False, "error": "no active servers"}), 400
    per_server = []
    for s in servers:
        try:
            res = backfill_server_clients(s)
            per_server.append({
                "server_id": s["id"],
                "code": s.get("code"),
                "country_name": s.get("country_name"),
                **res,
            })
        except Exception as e:
            per_server.append({
                "server_id": s["id"],
                "code": s.get("code"),
                "error": str(e),
            })
    return jsonify({"success": True, "servers": per_server})


# === END SERVER SYNC ===

def issue_subscription(uid: int, devices: int, days: int) -> dict:
    """Выдать/продлить подписку на всех активных серверах.
    UUID пользователя неизменен с первой выдачи — хранится в users.client_uuid.
    При истечении/отзыве и повторной выдаче UUID тот же, sub_url не меняется.
    Применяет накопленные bonus_days.
    """
    try:
        # Учитываем bonus_days
        bonus_days = 0
        try:
            u_row = sb.table("users").select("bonus_days").eq("user_id", uid).limit(1).execute()
            bonus_days = (u_row.data[0].get("bonus_days") or 0) if u_row.data else 0
        except Exception:
            pass
        total_days = days + bonus_days

        # Получаем постоянный UUID и последнюю запись подписки (активную или нет)
        sub_id, existing_uuid, _ = get_existing_client(uid)
        now = datetime.utcnow()

        if existing_uuid:
            # Всегда реиспользуем UUID — UUID пользователя не меняется никогда
            client_uuid = existing_uuid
            # База для расчёта: текущая expires_at если активна, иначе now
            try:
                if sub_id:
                    cur_row = (sb.table("subscriptions")
                                 .select("expires_at,status").eq("id", sub_id).limit(1).execute())
                    if cur_row.data:
                        cur_exp_raw = cur_row.data[0]["expires_at"]
                        is_active = cur_row.data[0]["status"] == "active"
                        cur_exp = (datetime.fromisoformat(cur_exp_raw.replace("Z", "+00:00")).replace(tzinfo=None)
                                   if cur_exp_raw else now)
                        # Продлеваем от текущей даты истечения только если подписка ещё активна
                        base = cur_exp if (is_active and cur_exp > now) else now
                    else:
                        base = now
                else:
                    base = now
            except Exception:
                base = now
            new_expires = base + timedelta(days=total_days)
            action = "extended"
        else:
            # Первая выдача — генерируем UUID один раз
            client_uuid = str(uuid.uuid4())
            new_expires = now + timedelta(days=total_days)
            action = "created"

        expire_ms = int(new_expires.timestamp() * 1000)

        # Применяем на всех активных серверах
        servers = get_active_servers()
        if not servers:
            return {"success": False, "error": "no active servers in DB"}

        success_count = 0
        failed_servers = []
        for server in servers:
            # При наличии existing_uuid обновляем (xui_update умеет add-if-missing)
            if existing_uuid:
                ok = xui_update_client_on_server(server, client_uuid, uid, devices, expire_ms)
            else:
                ok = xui_add_client_on_server(server, client_uuid, uid, devices, expire_ms)
            if ok:
                success_count += 1
            else:
                failed_servers.append(server.get("code") or server.get("country_name") or "?")

        if success_count == 0:
            return {"success": False, "error": "failed on all servers"}

        # Уведомляем суперадмина о частичном сбое (П.4)
        if failed_servers:
            try:
                fail_list = ", ".join(failed_servers)
                notify_user(SUPERADMIN_ID,
                    f"⚠️ <b>Подписка выдана частично!</b>\n\n"
                    f"👤 user_id: <code>{uid}</code>\n"
                    f"✅ {success_count}/{len(servers)} серверов\n"
                    f"❌ Сбой на: <b>{fail_list}</b>\n\n"
                    f"Что делать: откройте диагностику пользователя в панели и нажмите «🔧 Починить» напротив сбойных серверов.")
            except Exception:
                pass

        # Сохраняем в Supabase
        sub_url = f"{SUB_BASE_URL}/sub/{client_uuid}"
        sub_data = {
            "user_id": uid,
            "devices": devices,
            "status": "active",
            "sub_url": sub_url,
            "expires_at": new_expires.isoformat(),
            "notified_3d": False,
            "notified_1d": False,
            "notified_expired": False,
        }
        if sub_id:
            # Обновляем существующую запись (даже если была inactive) — не создаём дубли
            sb.table("subscriptions").update(sub_data).eq("id", sub_id).execute()
        else:
            # Первая выдача — создаём запись
            sub_data["started_at"] = now.isoformat()
            sb.table("subscriptions").insert(sub_data).execute()

        # users.client_uuid устанавливается ОДИН раз при первой выдаче, больше не меняется
        if not existing_uuid:
            sb.table("users").update({"client_uuid": client_uuid}).eq("user_id", uid).execute()

        # Списываем bonus_days если применили
        if bonus_days > 0:
            try:
                sb.table("users").update({"bonus_days": 0}).eq("user_id", uid).execute()
                print(f"Применены {bonus_days} бонусных дней для user_id={uid}")
            except Exception:
                pass

        print(f"✅ {action} user_id={uid} uuid={client_uuid[:8]} on {success_count}/{len(servers)} servers, expires {new_expires}")
        return {
            "success": True,
            "uuid": client_uuid,
            "sub_url": sub_url,
            "action": action,
            "servers": success_count,
        }
    except Exception as e:
        print(f"❌ Ошибка issue_subscription: {e}")
        return {"success": False, "error": str(e)}

def apply_referral_bonus(user_id: int, days: int, reason: str):
    """Начислить реферальный бонус (multi-server версия)"""
    try:
        print(f"🔄 Начисление реф. бонуса {days} дней для {user_id} ({reason})")
        
        servers = get_active_servers()
        if not servers:
            servers = [{"panel_url": PANEL_URL, "panel_login": PANEL_USER, "panel_password": PANEL_PASS, "country_name": "Finland"}]
        
        existing = sb.table("subscriptions").select("*").eq("user_id", user_id).eq("status", "active").execute()
        
        if existing.data:
            sub = existing.data[0]
            new_expires = datetime.fromisoformat(sub["expires_at"].replace("Z", "+00:00")) + timedelta(days=days)
            expires_str = new_expires.isoformat().replace("+00:00", "Z")
            
            client_uuid = sub["sub_url"].split("/sub/")[-1] if "/sub/" in sub.get("sub_url", "") else str(uuid.uuid4())
            
            expire_ms = int(new_expires.timestamp() * 1000)
            devices_count = sub.get("devices", 1)
            for server in servers:
                xui_update_client_on_server(server, client_uuid, user_id, devices_count, expire_ms)
            
            sb.table("subscriptions").update({"expires_at": expires_str, "notified_3d": False, "notified_1d": False, "notified_expired": False}).eq("id", sub["id"]).execute()
        else:
            issue_subscription(user_id, 1, days)
        
        print(f"✅ Реферальный бонус успешно начислен пользователю {user_id}")
        return True
    except Exception as e:
        print(f"❌ Ошибка apply_referral_bonus: {e}")
        return False

def notify_user(user_id: int, text: str, reply_markup: dict = None) -> bool:
    """Отправляет сообщение пользователю в Telegram через HTTP API."""
    try:
        import requests
        from config import BOT_TOKEN
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": user_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        app.logger.error(f"Не удалось отправить сообщение user_id={user_id}: {e}")
        return False


# ====================== ADMIN API: СЕРВЕРЫ ======================
@app.route('/admin-api/servers', methods=['GET', 'POST'])
def servers_api():
    """Получить список серверов или добавить новый"""
    try:
        if request.method == 'GET':
            r = sb.table('servers').select('*').order('sort_order').execute()
            return jsonify({"success": True, "servers": r.data})
        
        if request.method == 'POST':
            data = request.get_json()
            required = ['code', 'country_name', 'panel_url', 'panel_login', 'panel_password', 'server_ip']
            for field in required:
                if field not in data:
                    return jsonify({"success": False, "error": f"Поле {field} обязательно"}), 400
            
            new_server = {
                "code": data['code'],
                "country_name": data['country_name'],
                "country_flag": data.get('country_flag', ''),
                "country_code": data.get('country_code', data['code'].split('-')[0].upper()),
                "panel_url": data['panel_url'],
                "panel_login": data['panel_login'],
                "panel_password": encrypt_panel_password(data['panel_password']),
                "inbound_id": data.get('inbound_id', 1),
                "server_ip": data['server_ip'],
                "server_port": data.get('server_port', 443),
                "public_key": data.get('public_key', ''),
                "short_id": data.get('short_id', ''),
                "sni": data.get('sni', 'www.bing.com'),
                "flow": data.get('flow', 'xtls-rprx-vision'),
                "fingerprint": data.get('fingerprint', 'chrome'),
                "is_active": data.get('is_active', True),
                "sort_order": data.get('sort_order', 0),
                "created_at": datetime.utcnow().isoformat()
            }
            
            ins = sb.table('servers').insert(new_server).execute()

            
            new_id = ins.data[0]['id'] if ins.data else None

            
            # === AUTO-SYNC ON CREATE ===

            
            sync_started = False

            
            if new_id and new_server.get('is_active'):

            
                try:

            
                    created_server = get_server_by_id(new_id)

            
                    if created_server:

            
                        threading.Thread(

            
                            target=backfill_server_clients,

            
                            args=(created_server,),

            
                            daemon=True,

            
                        ).start()

            
                        sync_started = True

            
                        print(f'[auto-sync] backfill стартовал для нового сервера id={new_id}')

            
                except Exception as _e:

            
                    print(f'[auto-sync] failed to start on POST: {_e}')

            
            return jsonify({'success': True, 'message': 'Сервер добавлен', 'id': new_id, 'sync_started': sync_started})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/admin-api/servers/<server_id>', methods=['PUT', 'DELETE'])
def server_edit(server_id):
    """Обновить или удалить сервер"""
    try:
        if request.method == 'PUT':
            data = request.get_json()
            update_data = {}
            allowed_fields = ['code', 'country_name', 'country_flag', 'country_code', 
                            'panel_url', 'panel_login', 'panel_password', 'inbound_id',
                            'server_ip', 'server_port', 'public_key', 'short_id', 
                            'sni', 'flow', 'fingerprint', 'is_active', 'sort_order']
            for field in allowed_fields:
                if field in data:
                    update_data[field] = data[field]
            update_data['updated_at'] = datetime.utcnow().isoformat()

            # === AUTO-SYNC ON ENABLE ===

            need_sync = False

            try:

                if data.get('is_active'):

                    cur = sb.table('servers').select('is_active').eq('id', server_id).limit(1).execute()

                    was_active = bool(cur.data[0].get('is_active')) if cur.data else False

                    if not was_active:

                        need_sync = True

            except Exception:

                pass

            sb.table('servers').update(update_data).eq('id', server_id).execute()

            if need_sync:

                try:

                    srv = get_server_by_id(int(server_id))

                    if srv:

                        threading.Thread(

                            target=backfill_server_clients,

                            args=(srv,),

                            daemon=True,

                        ).start()

                        print(f'[auto-sync] backfill стартовал после активации сервера id={server_id}')

                except Exception as _e:

                    print(f'[auto-sync] failed to start on PUT: {_e}')

            return jsonify({'success': True, 'message': 'Сервер обновлён', 'sync_started': need_sync})
        
        if request.method == 'DELETE':
            sb.table('servers').delete().eq('id', server_id).execute()
            return jsonify({"success": True, "message": "Сервер удалён"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
# =================================================================

@app.route('/admin-api/servers/<server_id>/test', methods=['POST'])
def server_test(server_id):
    """Проверить соединение с панелью 3X-UI. Запишет результат в БД."""
    import time as _t
    try:
        srv_resp = sb.table("servers").select("*").eq("id", server_id).limit(1).execute()
        if not srv_resp.data:
            return jsonify({"success": False, "error": "server not found"}), 404
        server = srv_resp.data[0]
        start = _t.time()
        try:
            session, _ = xui_session(server)
            elapsed_ms = int((_t.time() - start) * 1000)
            status = "up"
            error = None
        except Exception as e:
            elapsed_ms = int((_t.time() - start) * 1000)
            status = "down"
            error = str(e)
        try:
            sb.table("servers").update({
                "last_check_at": datetime.utcnow().isoformat(),
                "last_check_status": status,
                "last_check_response_ms": elapsed_ms,
            }).eq("id", server_id).execute()
        except Exception:
            pass
        return jsonify({
            "success": status == "up",
            "status": status,
            "response_ms": elapsed_ms,
            "error": error,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/servers/encrypt_passwords', methods=['POST'])
def encrypt_server_passwords():
    """Зашифровать незашифрованные пароли серверов в БД. Только суперадмин. (П.6)"""
    try:
        if not _fernet:
            return jsonify({"success": False, "error": "PANEL_ENCRYPTION_KEY не задан в .env"}), 400
        servers_r = sb.table("servers").select("id,panel_password").execute()
        migrated = 0
        for s in (servers_r.data or []):
            pw = s.get("panel_password") or ""
            if pw and not pw.startswith('gAAAAA'):
                enc = encrypt_panel_password(pw)
                sb.table("servers").update({"panel_password": enc}).eq("id", s["id"]).execute()
                migrated += 1
        return jsonify({"success": True, "migrated": migrated})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/servers/<server_id>/clients', methods=['GET'])
def server_clients(server_id):
    """Получить список клиентов с конкретного сервера (из 3X-UI API)."""
    try:
        srv_resp = sb.table("servers").select("*").eq("id", server_id).limit(1).execute()
        if not srv_resp.data:
            return jsonify({"success": False, "error": "server not found"}), 404
        server = srv_resp.data[0]
        session, _ = xui_session(server)
        url = server["panel_url"].rstrip("/")
        r = session.get(f"{url}/xui/API/inbounds/list", timeout=10)
        data = r.json()
        clients = []
        for inbound in data.get("obj", []):
            if int(inbound.get("id", 0)) != int(server["inbound_id"]):
                continue
            settings_raw = inbound.get("settings", "{}")
            settings = settings_raw if isinstance(settings_raw, dict) else json.loads(settings_raw)
            for c in settings.get("clients", []):
                clients.append({
                    "uuid": c.get("id"),
                    "email": c.get("email"),
                    "limit_ip": c.get("limitIp"),
                    "expiry_ms": c.get("expiryTime"),
                    "expiry_human": (datetime.fromtimestamp(c["expiryTime"] / 1000).isoformat() if c.get("expiryTime") else None),
                    "enable": c.get("enable", True),
                })
        return jsonify({"success": True, "clients": clients, "total": len(clients)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/servers/<server_id>/stats', methods=['GET'])
def server_stats(server_id):
    """Сколько активных подписок ссылается на этот сервер (по факту все, т.к. multi-server)."""
    try:
        srv_resp = sb.table("servers").select("*").eq("id", server_id).limit(1).execute()
        if not srv_resp.data:
            return jsonify({"success": False, "error": "server not found"}), 404
        # Активные подписки в системе — общее число клиентов на сервере (так как multi-server)
        active = sb.table("subscriptions").select("id", count="exact").eq("status", "active").execute()
        total_active = active.count or 0
        return jsonify({
            "success": True,
            "active_subscriptions": total_active,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def healthcheck_loop():
    """Фоновая проверка всех активных серверов каждые 5 минут."""
    import time as _t
    while True:
        try:
            servers = get_active_servers()
            for s in servers:
                start = _t.time()
                try:
                    xui_session(s)
                    elapsed_ms = int((_t.time() - start) * 1000)
                    status = "up"
                except Exception:
                    elapsed_ms = int((_t.time() - start) * 1000)
                    status = "down"
                try:
                    sb.table("servers").update({
                        "last_check_at": datetime.utcnow().isoformat(),
                        "last_check_status": status,
                        "last_check_response_ms": elapsed_ms,
                    }).eq("id", s["id"]).execute()
                except Exception:
                    pass
        except Exception as e:
            print(f"healthcheck_loop error: {e}")
        _t.sleep(300)


@app.route('/admin-api/grant', methods=['POST', 'OPTIONS'])
def grant():
    if request.method == 'OPTIONS':
        resp = app.make_default_options_response()
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        return resp
    try:
        data = request.get_json() or {}
        uid = int(data['user_id'])
        # Текущее кол-во устройств (если set_devices не передан — оставляем как есть)
        cur_r = sb.table("subscriptions").select("devices").eq("user_id", uid).eq("status", "active").limit(1).execute()
        cur_devices = cur_r.data[0].get("devices", 1) if cur_r.data else 1
        devices = int(data.get("set_devices") or cur_devices)
        days = int(data.get("extend_days") or 0)
        result = issue_subscription(uid, devices, days)
        if result.get("success"):
            result["devices"] = devices
            resp = jsonify(result)
        else:
            resp = jsonify({"success": False, "error": result.get("error", "unknown")})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    except Exception as e:
        resp = jsonify({"success": False, "error": str(e)})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp



@app.route('/admin-api/revoke/<int:sub_id>', methods=['POST', 'OPTIONS'])
def revoke_subscription(sub_id):
    """Отозвать подписку: деактивировать клиента на всех 3X-UI серверах + обновить БД."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        sub_r = sb.table("subscriptions").select("*").eq("id", sub_id).limit(1).execute()
        if not sub_r.data:
            return jsonify({"success": False, "error": "subscription not found"}), 404
        sub = sub_r.data[0]
        client_uuid = sub.get("sub_url", "").split("/sub/")[-1] if "/sub/" in sub.get("sub_url", "") else None
        errors = []
        if client_uuid:
            servers = get_active_servers()
            for server in servers:
                try:
                    xui_disable_client_on_server(server, client_uuid, enable=False)
                except Exception as e:
                    errors.append(f"{server.get('code')}: {e}")
        sb.table("subscriptions").update({"status": "inactive"}).eq("id", sub_id).execute()
        return jsonify({"success": True, "sub_id": sub_id, "client_uuid": client_uuid, "server_errors": errors})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/notify_user', methods=['POST', 'OPTIONS'])
def admin_notify_user_endpoint():
    """Отправить сообщение пользователю от имени бота."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        data = request.get_json() or {}
        uid = int(data.get("user_id") or 0)
        text = (data.get("text") or "").strip()
        if not uid or not text:
            return jsonify({"success": False, "error": "user_id and text required"}), 400
        ok = notify_user(uid, text)
        return jsonify({"success": ok})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/broadcast', methods=['POST', 'OPTIONS'])
def admin_broadcast():
    """Рассылка сообщений пользователям по аудитории."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        data = request.get_json() or {}
        audience = data.get("audience", "all")
        text = (data.get("text") or "").strip()
        if not text:
            return jsonify({"success": False, "error": "text required"}), 400

        users_r = sb.table("users").select("user_id").execute()
        all_ids = [u["user_id"] for u in (users_r.data or [])]

        if audience == "active":
            subs_r = sb.table("subscriptions").select("user_id").eq("status", "active").execute()
            active_set = {s["user_id"] for s in (subs_r.data or [])}
            target_ids = [u for u in all_ids if u in active_set]
        elif audience == "inactive":
            subs_r = sb.table("subscriptions").select("user_id").eq("status", "active").execute()
            active_set = {s["user_id"] for s in (subs_r.data or [])}
            target_ids = [u for u in all_ids if u not in active_set]
        elif audience == "custom":
            target_ids = [int(x) for x in (data.get("user_ids") or []) if x]
        else:
            target_ids = all_ids

        sent = 0
        failed = 0
        for uid in target_ids:
            if notify_user(uid, text):
                sent += 1
            else:
                failed += 1

        try:
            sb.table("broadcasts").insert({
                "text": text,
                "audience": audience,
                "sent_count": sent,
                "failed_count": failed,
                "sent_by": getattr(request, 'admin_tg_id', None),
                "created_at": datetime.utcnow().isoformat(),
            }).execute()
        except Exception:
            pass

        return jsonify({"success": True, "sent": sent, "failed": failed, "total": len(target_ids)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _build_audit_report(uid):
    """Полная диагностика пользователя. Возвращает словарь report."""
    import requests as _req
    from concurrent.futures import ThreadPoolExecutor, as_completed
    now = datetime.utcnow()

    user_r = sb.table("users").select("*").eq("user_id", uid).limit(1).execute()
    if not user_r.data:
        raise ValueError("user not found")
    user = user_r.data[0]

    # Все подписки (история)
    all_subs_r = sb.table("subscriptions").select("*").eq("user_id", uid).order("created_at", desc=True).execute()
    all_subs = all_subs_r.data or []
    active_sub = next((s for s in all_subs if s.get("status") == "active"), None)

    # Устройства
    devs_r = sb.table("user_devices").select("*").eq("user_id", uid).order("last_seen", desc=True).execute()
    devices = devs_r.data or []

    # Платежи
    pays_r = sb.table("payments").select("*").eq("user_id", uid).order("created_at", desc=True).limit(20).execute()
    payments = pays_r.data or []

    # Рефералы
    refs_r = sb.table("referrals").select("referred_id").eq("referrer_id", uid).execute()
    referred_count = len(refs_r.data or [])

    ref_r = sb.table("referrals").select("referrer_id").eq("referred_id", uid).limit(1).execute()
    referrer = None
    if ref_r.data:
        ref_uid = ref_r.data[0]["referrer_id"]
        ref_user_r = sb.table("users").select("user_id,first_name,last_name,username").eq("user_id", ref_uid).limit(1).execute()
        if ref_user_r.data:
            referrer = ref_user_r.data[0]

    # UUID клиента
    client_uuid = None
    if active_sub:
        sub_url_str = active_sub.get("sub_url", "")
        client_uuid = sub_url_str.split("/sub/")[-1] if "/sub/" in sub_url_str else None

    def _check_server(server):
        code = server.get("code", "?")
        name = server.get("country_name", code)
        check = {
            "server_id": server.get("id"),
            "server_name": name,
            "code": code,
            "country_flag": server.get("country_flag"),
            "found": False, "enabled": None,
            "expiry": None, "expiry_ms": 0, "expiry_human": None,
            "response_ms": 0, "error": None,
        }
        if not client_uuid:
            check["error"] = "нет client_uuid"
            return check
        try:
            t0 = datetime.utcnow()
            session, _ = xui_session(server)
            url = server["panel_url"].rstrip("/")
            r = session.get(f"{url}/xui/API/inbounds/list", timeout=10)
            check["response_ms"] = int((datetime.utcnow() - t0).total_seconds() * 1000)
            for inb in r.json().get("obj", []):
                if int(inb.get("id", 0)) != int(server["inbound_id"]):
                    continue
                settings_raw = inb.get("settings", "{}")
                settings = settings_raw if isinstance(settings_raw, dict) else json.loads(settings_raw)
                for c in settings.get("clients", []):
                    if c.get("id") == client_uuid:
                        check["found"] = True
                        check["enabled"] = c.get("enable", True)
                        exp_ms = c.get("expiryTime", 0)
                        check["expiry_ms"] = exp_ms or 0
                        if exp_ms:
                            exp_dt = datetime.fromtimestamp(exp_ms / 1000)
                            check["expiry"] = exp_dt.isoformat()
                            check["expiry_human"] = "до " + exp_dt.strftime("%d.%m.%Y")
                        break
                if check["found"]:
                    break
        except Exception as e:
            check["error"] = str(e)[:100]
        return check

    # Параллельная проверка серверов
    active_servers = get_active_servers()
    server_checks = []
    if active_servers:
        with ThreadPoolExecutor(max_workers=min(len(active_servers), 6)) as pool:
            futures = {pool.submit(_check_server, srv): srv for srv in active_servers}
            for fut in as_completed(futures):
                server_checks.append(fut.result())
        server_checks.sort(key=lambda c: c.get("server_id") or 0)

    # Проверка sub_url
    sub_url_check = None
    if active_sub and active_sub.get("sub_url"):
        sub_url = active_sub["sub_url"]
        try:
            t0 = datetime.utcnow()
            r = _req.get(sub_url, timeout=10, allow_redirects=True,
                         headers={"X-Audit-Internal": "1"})
            ms = int((datetime.utcnow() - t0).total_seconds() * 1000)
            valid_json = (r.status_code == 200)
            note = "Лимит устройств достигнут" if r.status_code == 403 else None
            sub_url_check = {"url": sub_url, "status_code": r.status_code, "response_ms": ms, "valid_json": valid_json, "note": note}
        except Exception as e:
            sub_url_check = {"url": sub_url, "status_code": None, "response_ms": None, "valid_json": False, "error": str(e)[:80]}

    # Оценка (score) и проблемы
    issues = []
    if not active_sub:
        issues.append("Нет активной подписки")
    else:
        found_anywhere = any(c.get("found") for c in server_checks)
        if not found_anywhere and server_checks:
            issues.append("Клиент не найден ни на одном сервере")
        else:
            disabled = [c["code"] for c in server_checks if c.get("found") and c.get("enabled") is False]
            if disabled:
                issues.append(f"Клиент отключён на серверах: {', '.join(disabled)}")
            errors = [c["code"] for c in server_checks if c.get("error") and not c.get("found")]
            if errors:
                issues.append(f"Ошибка проверки серверов: {', '.join(errors)}")
        if sub_url_check and sub_url_check.get("status_code") not in (200, None) and not sub_url_check.get("valid_json"):
            issues.append(f"sub_url вернул HTTP {sub_url_check.get('status_code', '?')}")
        elif sub_url_check and sub_url_check.get("error"):
            issues.append(f"sub_url недоступен: {sub_url_check['error'][:60]}")
        exp_raw = active_sub.get("expires_at")
        if exp_raw:
            try:
                exp = datetime.fromisoformat(exp_raw.replace("Z", "+00:00")).replace(tzinfo=None)
                days_left = (exp - now).days
                if days_left < 0:
                    issues.append("Подписка просрочена (expires_at в прошлом)")
                elif days_left <= 3:
                    issues.append(f"Подписка истекает через {days_left} дн.")
            except Exception:
                pass

    score = "ok" if not issues else ("warn" if len(issues) == 1 else "error")

    return {
        "uid": uid,
        "user": user,
        "active_sub": active_sub,
        "server_checks": server_checks,
        "sub_url_check": sub_url_check,
        "devices": devices,
        "payments": payments,
        "subscriptions": all_subs,
        "referred_count": referred_count,
        "referrer": referrer,
        "score": score,
        "issues": issues,
        "ts": now.isoformat() + "Z",
    }


@app.route('/admin-api/user_audit/<int:uid>', methods=['GET', 'OPTIONS'])
def user_audit(uid):
    """Полная диагностика пользователя."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        report = _build_audit_report(uid)
        return jsonify({"success": True, "report": report})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/fix_user/<int:uid>', methods=['POST', 'OPTIONS'])
def fix_user(uid):
    """Восстановить клиента на всех серверах (принудительная синхронизация)."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        sub_r = sb.table("subscriptions").select("*").eq("user_id", uid).eq("status", "active").limit(1).execute()
        if not sub_r.data:
            return jsonify({"success": False, "error": "no active subscription"}), 404
        sub = sub_r.data[0]
        client_uuid = sub.get("sub_url", "").split("/sub/")[-1] if "/sub/" in sub.get("sub_url", "") else None
        if not client_uuid:
            return jsonify({"success": False, "error": "no client_uuid"}), 400
        devices = int(sub.get("devices") or 1)
        from datetime import datetime, timedelta
        exp_raw = sub.get("expires_at")
        exp_dt = datetime.fromisoformat(exp_raw.replace("Z", "+00:00")).replace(tzinfo=None) if exp_raw else (datetime.utcnow() + timedelta(days=30))
        expire_ms = int(exp_dt.timestamp() * 1000)
        results = []
        for server in get_active_servers():
            ok = xui_update_client_on_server(server, client_uuid, uid, devices, expire_ms)
            results.append({"code": server.get("code"), "ok": ok})
        return jsonify({"success": True, "results": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/user_fix/<int:uid>/<int:srv_id>', methods=['POST', 'OPTIONS'])
def fix_user_on_server(uid, srv_id):
    """Восстановить клиента на конкретном сервере."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        sub_r = sb.table("subscriptions").select("*").eq("user_id", uid).eq("status", "active").limit(1).execute()
        if not sub_r.data:
            return jsonify({"success": False, "error": "no active subscription"}), 404
        sub = sub_r.data[0]
        client_uuid = sub.get("sub_url", "").split("/sub/")[-1] if "/sub/" in sub.get("sub_url", "") else None
        if not client_uuid:
            return jsonify({"success": False, "error": "no client_uuid"}), 400
        devices = int(sub.get("devices") or 1)
        exp_raw = sub.get("expires_at")
        exp_dt = datetime.fromisoformat(exp_raw.replace("Z", "+00:00")).replace(tzinfo=None) if exp_raw else (datetime.utcnow() + timedelta(days=30))
        expire_ms = int(exp_dt.timestamp() * 1000)
        srv_r = sb.table("servers").select("*").eq("id", srv_id).limit(1).execute()
        if not srv_r.data:
            return jsonify({"success": False, "error": "server not found"}), 404
        server = srv_r.data[0]
        ok = xui_update_client_on_server(server, client_uuid, uid, devices, expire_ms)
        return jsonify({"success": ok, "message": "Клиент синхронизирован" if ok else "Ошибка синхронизации"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/user_devices/<int:uid>/<int:dev_id>', methods=['DELETE', 'OPTIONS'])
def delete_user_device(uid, dev_id):
    """Удалить (деактивировать) устройство пользователя."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        sb.table("user_devices").update({"is_active": False}).eq("id", dev_id).eq("user_id", uid).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== MY-PERMISSIONS ====================

SUPERADMIN_ID = 784871620

@app.route('/admin-api/my-permissions', methods=['GET', 'OPTIONS'])
def my_permissions():
    """Права текущего вошедшего администратора."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    tg_id = request.admin_tg_id
    is_superadmin = (int(tg_id) == SUPERADMIN_ID)
    if is_superadmin:
        permissions = [
            "view_users", "edit_users", "view_finance", "edit_finance",
            "view_tickets", "manage_tickets", "view_servers", "manage_servers",
            "send_broadcast", "view_analytics", "manage_roles",
        ]
    else:
        try:
            adm_r = sb.table("support_admins").select("*").eq("user_id", tg_id).eq("is_active", True).limit(1).execute()
            adm = adm_r.data[0] if adm_r.data else {}
            role_perms = []
            if adm.get("role_id"):
                role_r = sb.table("admin_roles").select("permissions").eq("id", adm["role_id"]).limit(1).execute()
                if role_r.data:
                    role_perms = role_r.data[0].get("permissions") or []
            added = adm.get("added_permissions") or []
            removed = adm.get("removed_permissions") or []
            permissions = list((set(role_perms) | set(added)) - set(removed))
        except Exception:
            permissions = ["view_tickets", "manage_tickets"]
    return jsonify({
        "user_id": tg_id,
        "is_superadmin": is_superadmin,
        "permissions": permissions,
        "sections": {},
        "all_permissions": [],
    })


# ==================== TICKETS ====================

def _notify_user_support(user_id: int, text: str) -> bool:
    """Отправляет сообщение пользователю через support-бот."""
    try:
        import requests as _req
        from config import SUPPORT_BOT_TOKEN
        r = _req.post(
            f"https://api.telegram.org/bot{SUPPORT_BOT_TOKEN}/sendMessage",
            json={"chat_id": user_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        app.logger.error(f"notify_support user={user_id}: {e}")
        return False


@app.route('/admin-api/tickets/<int:ticket_id>', methods=['GET', 'OPTIONS'])
def get_ticket_api(ticket_id):
    """Тикет + все сообщения."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        t_r = sb.table("support_tickets").select("*").eq("id", ticket_id).limit(1).execute()
        if not t_r.data:
            return jsonify({"success": False, "error": "ticket not found"}), 404
        ticket = t_r.data[0]
        # Данные пользователя
        u_r = sb.table("users").select("user_id,first_name,last_name,username").eq("user_id", ticket["user_id"]).limit(1).execute()
        ticket["user"] = u_r.data[0] if u_r.data else {}
        # Данные назначенного админа
        if ticket.get("assigned_admin_id"):
            a_r = sb.table("support_admins").select("user_id,full_name,username").eq("user_id", ticket["assigned_admin_id"]).limit(1).execute()
            ticket["assigned_admin"] = a_r.data[0] if a_r.data else {"user_id": ticket["assigned_admin_id"]}
        msgs_r = sb.table("support_messages").select("*").eq("ticket_id", ticket_id).order("created_at").execute()
        return jsonify({"success": True, "ticket": ticket, "messages": msgs_r.data or []})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/tickets/<int:ticket_id>/messages', methods=['GET', 'OPTIONS'])
def ticket_messages(ticket_id):
    """Новые сообщения в тикете после указанного id."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        after = int(request.args.get("after", 0))
        q = sb.table("support_messages").select("*").eq("ticket_id", ticket_id).order("id")
        if after:
            q = q.gt("id", after)
        r = q.execute()
        return jsonify({"success": True, "messages": r.data or []})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/tickets/<int:ticket_id>/take', methods=['POST', 'OPTIONS'])
def take_ticket(ticket_id):
    """Взять тикет в работу."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        admin_tg_id = request.admin_tg_id
        sb.table("support_tickets").update({
            "status": "in_progress",
            "assigned_admin_id": admin_tg_id,
        }).eq("id", ticket_id).execute()
        sb.table("support_messages").insert({
            "ticket_id": ticket_id, "sender_type": "system",
            "message_text": f"Тикет взят в работу администратором (id:{admin_tg_id})",
            "created_at": datetime.utcnow().isoformat(),
        }).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/tickets/<int:ticket_id>/close', methods=['POST', 'OPTIONS'])
def close_ticket(ticket_id):
    """Закрыть тикет."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        sb.table("support_tickets").update({
            "status": "closed",
            "closed_at": datetime.utcnow().isoformat(),
        }).eq("id", ticket_id).execute()
        sb.table("support_messages").insert({
            "ticket_id": ticket_id, "sender_type": "system",
            "message_text": "Тикет закрыт администратором.",
            "created_at": datetime.utcnow().isoformat(),
        }).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/tickets/<int:ticket_id>/reopen', methods=['POST', 'OPTIONS'])
def reopen_ticket(ticket_id):
    """Переоткрыть тикет."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        sb.table("support_tickets").update({
            "status": "open",
            "closed_at": None,
        }).eq("id", ticket_id).execute()
        sb.table("support_messages").insert({
            "ticket_id": ticket_id, "sender_type": "system",
            "message_text": "Тикет переоткрыт администратором.",
            "created_at": datetime.utcnow().isoformat(),
        }).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/tickets/<int:ticket_id>/reply', methods=['POST', 'OPTIONS'])
def reply_ticket(ticket_id):
    """Ответить на тикет от имени поддержки."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        data = request.get_json() or {}
        text = (data.get("text") or "").strip()
        if not text:
            return jsonify({"success": False, "error": "text required"}), 400
        t_r = sb.table("support_tickets").select("user_id,status").eq("id", ticket_id).limit(1).execute()
        if not t_r.data:
            return jsonify({"success": False, "error": "ticket not found"}), 404
        ticket = t_r.data[0]
        user_id = ticket["user_id"]
        # Определяем имя/никнейм отправителя
        admin_tg_id = request.admin_tg_id
        a_r = sb.table("support_admins").select("full_name,username").eq("tg_id", admin_tg_id).limit(1).execute()
        adm = a_r.data[0] if a_r.data else {}
        sender_name = adm.get("full_name") or adm.get("username") or f"Поддержка (id:{admin_tg_id})"
        sb.table("support_messages").insert({
            "ticket_id": ticket_id,
            "sender_type": "admin",
            "sender_id": admin_tg_id,
            "sender_name": sender_name,
            "message_text": text,
            "created_at": datetime.utcnow().isoformat(),
        }).execute()
        # Уведомить пользователя через support-бот
        msg = f"💬 <b>Ответ поддержки</b> (тикет #{ticket_id}):\n\n{text}"
        _notify_user_support(user_id, msg)
        # Если тикет открыт — переводим в in_progress
        if ticket.get("status") == "open":
            sb.table("support_tickets").update({
                "status": "in_progress",
                "assigned_admin_id": admin_tg_id,
            }).eq("id", ticket_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== WATCHLIST ====================

@app.route('/admin-api/watchlist', methods=['GET', 'POST', 'OPTIONS'])
def watchlist_api():
    """Список VIP-пользователей для мониторинга."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        if request.method == 'GET':
            r = sb.table("watchlist").select("*").order("created_at", desc=True).execute()
            return jsonify({"watchlist": r.data or []})
        data = request.get_json() or {}
        uid = int(data.get("user_id") or 0)
        if not uid:
            return jsonify({"success": False, "error": "user_id required"}), 400
        # Проверяем что юзер существует
        u_r = sb.table("users").select("user_id").eq("user_id", uid).limit(1).execute()
        if not u_r.data:
            return jsonify({"success": False, "error": "user not found"}), 404
        # Идемпотентно — не добавляем дважды
        ex = sb.table("watchlist").select("id").eq("user_id", uid).limit(1).execute()
        if not ex.data:
            sb.table("watchlist").insert({
                "user_id": uid,
                "created_at": datetime.utcnow().isoformat(),
            }).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/watchlist/<int:uid>', methods=['DELETE', 'OPTIONS'])
def watchlist_remove(uid):
    """Удалить пользователя из watchlist."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        sb.table("watchlist").delete().eq("user_id", uid).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/watchlist_batch_audit', methods=['GET', 'OPTIONS'])
def watchlist_batch_audit():
    """Запустить диагностику для всех пользователей из watchlist."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        wl_r = sb.table("watchlist").select("user_id").execute()
        uids = [row["user_id"] for row in (wl_r.data or [])]

        def _audit_one(uid):
            try:
                report = _build_audit_report(uid)
                return {
                    "user_id": uid,
                    "score": report["score"],
                    "issues": report["issues"],
                    "active_sub": report["active_sub"],
                    "server_checks": report["server_checks"],
                    "sub_url_check": report["sub_url_check"],
                    "ts": report["ts"],
                }
            except Exception as e:
                return {
                    "user_id": uid, "score": "error",
                    "issues": [str(e)], "active_sub": None,
                    "server_checks": [], "sub_url_check": None,
                    "ts": datetime.utcnow().isoformat() + "Z",
                }

        results = []
        if uids:
            with ThreadPoolExecutor(max_workers=min(len(uids), 4)) as pool:
                futures = {pool.submit(_audit_one, uid): uid for uid in uids}
                for fut in as_completed(futures):
                    results.append(fut.result())
            results.sort(key=lambda r: r["user_id"])

        return jsonify({"success": True, "results": results, "ts": datetime.utcnow().isoformat() + "Z"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== FINANCE ====================

@app.route('/admin-api/finance/summary', methods=['GET', 'OPTIONS'])
def finance_summary():
    """Суммарные показатели: доходы, расходы, вложения."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        pays_r = sb.table("payments").select("amount").eq("status", "succeeded").execute()
        total_income = sum(float(p.get("amount") or 0) for p in (pays_r.data or []))
        exp_r = sb.table("finance_expenses").select("amount").execute()
        total_expenses = sum(float(e.get("amount") or 0) for e in (exp_r.data or []))
        inv_r = sb.table("finance_investments").select("amount").execute()
        total_invested = sum(float(i.get("amount") or 0) for i in (inv_r.data or []))
        return jsonify({"summary": {
            "total_income": round(total_income, 2),
            "total_expenses": round(total_expenses, 2),
            "total_invested": round(total_invested, 2),
        }})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/admin-api/finance/expenses', methods=['GET', 'POST', 'OPTIONS'])
def finance_expenses():
    """Список расходов / добавить расход."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        if request.method == 'GET':
            r = sb.table("finance_expenses").select("*").order("expense_date", desc=True).execute()
            return jsonify(r.data or [])
        data = request.get_json() or {}
        r = sb.table("finance_expenses").insert({
            "amount": float(data.get("amount") or 0),
            "category": data.get("category", ""),
            "description": data.get("description", ""),
            "expense_date": data.get("expense_date") or datetime.utcnow().date().isoformat(),
            "is_recurring": bool(data.get("is_recurring", False)),
            "recurring_period": data.get("recurring_period") or None,
            "created_at": datetime.utcnow().isoformat(),
            "created_by": request.admin_tg_id,
        }).execute()
        return jsonify({"success": True, "id": (r.data or [{}])[0].get("id")})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/finance/expenses/<int:exp_id>', methods=['PUT', 'DELETE', 'OPTIONS'])
def finance_expense_item(exp_id):
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        if request.method == 'DELETE':
            sb.table("finance_expenses").delete().eq("id", exp_id).execute()
            return jsonify({"success": True})
        data = request.get_json() or {}
        upd = {k: data[k] for k in ("amount", "category", "description", "expense_date", "is_recurring", "recurring_period") if k in data}
        sb.table("finance_expenses").update(upd).eq("id", exp_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/finance/investments', methods=['GET', 'POST', 'OPTIONS'])
def finance_investments():
    """Список вложений / добавить вложение."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        if request.method == 'GET':
            r = sb.table("finance_investments").select("*").order("invested_at", desc=True).execute()
            return jsonify(r.data or [])
        data = request.get_json() or {}
        r = sb.table("finance_investments").insert({
            "amount": float(data.get("amount") or 0),
            "source_id": data.get("source_id"),
            "note": data.get("note", ""),
            "invested_at": data.get("invested_at") or datetime.utcnow().date().isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "created_by": request.admin_tg_id,
        }).execute()
        return jsonify({"success": True, "id": (r.data or [{}])[0].get("id")})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/finance/investments/<int:inv_id>', methods=['DELETE', 'OPTIONS'])
def finance_investment_item(inv_id):
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        sb.table("finance_investments").delete().eq("id", inv_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/finance/planned', methods=['GET', 'POST', 'OPTIONS'])
def finance_planned():
    """Список плановых расходов / добавить."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        if request.method == 'GET':
            r = sb.table("finance_planned").select("*").order("planned_date").execute()
            return jsonify(r.data or [])
        data = request.get_json() or {}
        r = sb.table("finance_planned").insert({
            "estimated_amount": float(data.get("estimated_amount") or 0) or None,
            "category": data.get("category", ""),
            "description": data.get("description", ""),
            "planned_date": data.get("planned_date") or None,
            "is_done": False,
            "created_at": datetime.utcnow().isoformat(),
            "created_by": request.admin_tg_id,
        }).execute()
        return jsonify({"success": True, "id": (r.data or [{}])[0].get("id")})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/finance/planned/<int:plan_id>', methods=['PUT', 'DELETE', 'OPTIONS'])
def finance_planned_item(plan_id):
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        if request.method == 'DELETE':
            sb.table("finance_planned").delete().eq("id", plan_id).execute()
            return jsonify({"success": True})
        data = request.get_json() or {}
        upd = {k: data[k] for k in ("estimated_amount", "category", "description", "planned_date", "is_done") if k in data}
        sb.table("finance_planned").update(upd).eq("id", plan_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/finance/sources', methods=['GET', 'OPTIONS'])
def finance_sources():
    """Список источников финансирования."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        r = sb.table("finance_sources").select("*").order("id").execute()
        return jsonify(r.data or [])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/admin-api/finance/breakdown', methods=['GET', 'OPTIONS'])
def finance_breakdown():
    """Финансовая раскладка по источникам."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        sources_r = sb.table("finance_sources").select("*").execute()
        sources = sources_r.data or []
        inv_r = sb.table("finance_investments").select("source_id,amount").execute()
        exp_r = sb.table("finance_expenses").select("source_id,amount").execute()

        from collections import defaultdict
        inv_by_src = defaultdict(float)
        for i in (inv_r.data or []):
            if i.get("source_id"):
                inv_by_src[i["source_id"]] += float(i.get("amount") or 0)
        exp_by_src = defaultdict(float)
        for e in (exp_r.data or []):
            if e.get("source_id"):
                exp_by_src[e["source_id"]] += float(e.get("amount") or 0)

        rows = []
        total_balance = 0.0
        for src in sources:
            sid = src["id"]
            contributed = round(inv_by_src.get(sid, 0), 2)
            spent = round(exp_by_src.get(sid, 0), 2)
            balance = round(contributed - spent, 2)
            total_balance += balance
            rows.append({"source": src, "contributed": contributed, "spent": spent, "balance": balance})

        return jsonify({"sources": rows, "total_balance": round(total_balance, 2)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== ROLES & ADMIN USERS ====================

@app.route('/admin-api/roles', methods=['GET', 'POST', 'OPTIONS'])
def admin_roles_list():
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        if request.method == 'GET':
            r = sb.table("admin_roles").select("*").order("id").execute()
            return jsonify(r.data or [])
        data = request.get_json() or {}
        r = sb.table("admin_roles").insert({
            "name": data.get("name", ""),
            "description": data.get("description", ""),
            "permissions": data.get("permissions", []),
            "created_by": request.admin_tg_id,
        }).execute()
        return jsonify({"success": True, "id": (r.data or [{}])[0].get("id")})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/roles/<int:role_id>', methods=['PUT', 'DELETE', 'OPTIONS'])
def admin_role_item(role_id):
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        if request.method == 'DELETE':
            sb.table("admin_roles").delete().eq("id", role_id).execute()
            return jsonify({"success": True})
        data = request.get_json() or {}
        upd = {k: data[k] for k in ("name", "description", "permissions") if k in data}
        sb.table("admin_roles").update(upd).eq("id", role_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/admin-users', methods=['GET', 'POST', 'OPTIONS'])
def admin_users_list():
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        if request.method == 'GET':
            r = sb.table("support_admins").select("*").order("added_at").execute()
            return jsonify(r.data or [])
        data = request.get_json() or {}
        uid = data.get("user_id")
        if not uid:
            return jsonify({"success": False, "error": "user_id required"}), 400
        fields = {
            "user_id": int(uid),
            "full_name": data.get("full_name", ""),
            "username": data.get("username", ""),
            "is_active": bool(data.get("is_active", True)),
            "role_id": data.get("role_id") or None,
            "added_permissions": data.get("added_permissions", []),
            "removed_permissions": data.get("removed_permissions", []),
        }
        existing_r = sb.table("support_admins").select("user_id").eq("user_id", int(uid)).limit(1).execute()
        if existing_r.data:
            sb.table("support_admins").update(fields).eq("user_id", int(uid)).execute()
        else:
            fields["added_at"] = datetime.utcnow().isoformat()
            sb.table("support_admins").insert(fields).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/admin-users/<int:uid>', methods=['DELETE', 'OPTIONS'])
def admin_user_item(uid):
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        sb.table("support_admins").update({"is_active": False}).eq("user_id", uid).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/payments/<int:pay_id>/register_receipt', methods=['POST', 'OPTIONS'])
def register_receipt(pay_id):
    """Пометить чек оформленным + опционально уведомить пользователя."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        body = request.get_json(silent=True) or {}
        receipt_url = (body.get('receipt_url') or '').strip() or None
        send_notif = bool(body.get('send_sms') or body.get('send_notification'))

        pay_r = sb.table("payments").select("*").eq("id", pay_id).limit(1).execute()
        if not pay_r.data:
            return jsonify({"success": False, "error": "payment not found"}), 404
        p = pay_r.data[0]

        upd = {
            "receipt_status": "registered",
            "receipt_registered_at": datetime.utcnow().isoformat(),
        }
        if receipt_url:
            upd["receipt_url"] = receipt_url

        sb.table("payments").update(upd).eq("id", pay_id).execute()

        delivered = False
        if send_notif and p.get("user_id"):
            paid_date = (p.get("paid_at") or p.get("created_at") or "")[:10]
            amount = p.get("amount", "")
            msg = f"✅ Чек за подписку TuVPN оформлен!\n\nСумма: {amount}₽, дата: {paid_date}."
            if receipt_url:
                msg += f"\n\n📄 Ссылка на чек: {receipt_url}"
            msg += "\n\nСпасибо, что с нами! ❤️"
            delivered = notify_user(int(p["user_id"]), msg)

        return jsonify({"success": True, "delivered": delivered})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/export/csv', methods=['GET', 'OPTIONS'])
def export_csv():
    """Экспорт данных в CSV: ?type=payments|users|subscriptions"""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    import csv, io
    t = request.args.get("type", "payments")
    try:
        if t == "payments":
            r = sb.table("payments").select("*").order("created_at", desc=True).limit(5000).execute()
            fields = ["id", "created_at", "user_id", "amount", "currency", "status", "devices", "months", "email", "provider_payment_id", "receipt_status", "campaign_code"]
        elif t == "users":
            r = sb.table("users").select("*").order("created_at", desc=True).limit(5000).execute()
            fields = ["user_id", "username", "first_name", "last_name", "created_at", "bonus_days", "referrer_id", "campaign_code"]
        elif t == "subscriptions":
            r = sb.table("subscriptions").select("*").order("created_at", desc=True).limit(5000).execute()
            fields = ["id", "user_id", "devices", "status", "started_at", "expires_at", "sub_url"]
        else:
            return jsonify({"success": False, "error": "unknown type"}), 400

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in (r.data or []):
            writer.writerow({f: row.get(f, "") for f in fields})
        csv_bytes = output.getvalue().encode("utf-8-sig")
        return Response(
            csv_bytes,
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{t}_{datetime.utcnow().strftime("%Y%m%d")}.csv"'},
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/yookassa/webhook', methods=['POST'])
def yookassa_webhook():
    """Обработка уведомлений от ЮКассы об оплате."""
    import yookassa_client
    from datetime import datetime
    client_ip = request.headers.get('X-Real-IP') or request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr
    if not yookassa_client.is_yookassa_ip(client_ip):
        app.logger.warning(f"Webhook от не-ЮКасса IP: {client_ip}")
        return jsonify({"error": "forbidden"}), 403

    body = request.json
    parsed = yookassa_client.parse_webhook(body)
    if not parsed:
        return jsonify({"error": "bad_payload"}), 400

    payment_id = parsed["payment_id"]
    event = parsed["event"]
    metadata = parsed["metadata"] or {}
    app.logger.info(f"Webhook ЮКассы: event={event}, payment_id={payment_id}")

    # === YOOKASSA WEBHOOK SECURITY ===
    # 1) Двойная сверка через API ЮКассы — нельзя доверять только webhook body
    verified = yookassa_client.get_payment_info(payment_id)
    if not verified:
        app.logger.error(f"[SECURITY] Не удалось верифицировать платёж {payment_id} через API ЮКассы — отклоняем")
        return jsonify({"error": "verification_failed"}), 403
    # Сверяем что статус, сумма и metadata совпадают
    if verified.get("status") != parsed.get("status"):
        app.logger.error(f"[SECURITY] Status mismatch для {payment_id}: webhook={parsed.get('status')}, api={verified.get('status')}")
        return jsonify({"error": "status_mismatch"}), 403
    try:
        if abs(float(verified.get("amount") or 0) - float(parsed.get("amount") or 0)) > 0.01:
            app.logger.error(f"[SECURITY] Amount mismatch для {payment_id}: webhook={parsed.get('amount')}, api={verified.get('amount')}")
            return jsonify({"error": "amount_mismatch"}), 403
    except Exception:
        pass
    verified_meta = verified.get("metadata") or {}
    if str(verified_meta.get("user_id") or "") != str(metadata.get("user_id") or ""):
        app.logger.error(f"[SECURITY] user_id mismatch для {payment_id}: webhook={metadata.get('user_id')}, api={verified_meta.get('user_id')}")
        return jsonify({"error": "user_id_mismatch"}), 403
    # Используем metadata из API, не из webhook — API source of truth
    metadata = verified_meta or metadata

    # 2) Idempotency: если этот payment уже обработан как succeeded — не выдаём подписку второй раз
    already_processed = False
    try:
        chk = sb.table("payments").select("status,paid_at").eq("provider_payment_id", payment_id).limit(1).execute()
        if chk.data:
            row = chk.data[0]
            if row.get("status") == "succeeded" and row.get("paid_at"):
                already_processed = True
                app.logger.info(f"[idempotency] Payment {payment_id} уже обработан — пропускаем выдачу подписки")
    except Exception as _e:
        app.logger.error(f"[idempotency] check error: {_e}")

    # 3) Проверка суммы (защита от подмены тарифа)
    if parsed.get("status") == "succeeded" and not already_processed:
        try:
            from config import PRICES
        except ImportError:
            PRICES = None
        if PRICES:
            try:
                d = int(metadata.get("devices") or 0)
                m = int(metadata.get("months") or 0)
                expected_price = None
                # PRICES может быть dict[(devices, months)] = price ИЛИ dict[devices][str(months)] = price
                if isinstance(PRICES, dict):
                    if (d, m) in PRICES:
                        expected_price = PRICES[(d, m)]
                    elif d in PRICES and isinstance(PRICES[d], dict):
                        # Ключи месяцев могут быть строками или int — проверяем оба варианта
                        expected_price = PRICES[d].get(str(m)) or PRICES[d].get(m)
                if expected_price is not None:
                    paid = float(parsed.get("amount") or 0)
                    # Разрешаем платёж быть НЕ МЕНЬШЕ ожидаемого минус 50% (если применён промокод-скидка)
                    # Это не идеально, но защищает от платежа в 1 рубль за годовую подписку
                    min_acceptable = float(expected_price) * 0.5
                    if paid < min_acceptable:
                        app.logger.error(f"[SECURITY] Price too low for {payment_id}: paid={paid}, expected_min={min_acceptable} (full={expected_price}, devices={d}, months={m})")
                        return jsonify({"error": "price_below_minimum"}), 403
            except Exception as _e:
                app.logger.error(f"[SECURITY] price check error: {_e}")
    # === END YOOKASSA WEBHOOK SECURITY ===


    # Обновляем платёж в БД
    existing = sb.table("payments").select("*").eq("provider_payment_id", payment_id).limit(1).execute()
    payment_row = {
        "provider": "yookassa",
        "provider_payment_id": payment_id,
        "user_id": int(metadata.get("user_id")) if metadata.get("user_id") else None,
        "amount": parsed["amount"],
        "currency": parsed["currency"],
        "status": parsed["status"],
        "payment_method": parsed.get("payment_method"),
        "email": metadata.get("email"),
        "devices": int(metadata.get("devices")) if metadata.get("devices") else None,
        "months": int(metadata.get("months")) if metadata.get("months") else None,
        "metadata": metadata,
        "updated_at": datetime.now().isoformat(),
    }
    if parsed["status"] == "succeeded":
        payment_row["paid_at"] = datetime.now().isoformat()

    if existing.data:
        sb.table("payments").update(payment_row).eq("provider_payment_id", payment_id).execute()
    else:
        sb.table("payments").insert(payment_row).execute()

    # Обработка отмены платежа (П.13)
    if event in ("payment.canceled", "payment.failed") or parsed.get("status") == "canceled":
        uid_str = metadata.get("user_id")
        if uid_str:
            try:
                notify_user(int(uid_str),
                    "❌ <b>Платёж не прошёл</b>\n\n"
                    "Оплата была отменена или произошла ошибка. "
                    "Попробуйте ещё раз или выберите другой способ оплаты.",
                    reply_markup={"inline_keyboard": [[{"text": "🛒 Попробовать снова", "callback_data": "buy"}]]})
            except Exception as e:
                app.logger.error(f"Не удалось уведомить о cancel payment: {e}")
        return jsonify({"ok": True}), 200

    # Статус waiting_for_capture — просто обновили запись в БД, ничего не делаем
    if parsed.get("status") == "waiting_for_capture":
        return jsonify({"ok": True}), 200

    if event == "payment.succeeded" and parsed["status"] == "succeeded":
        try:
            uid = int(metadata.get("user_id"))
# Campaign attribution: copy campaign_code from user to payment
            campaign_code = None
            try:
                user_r = sb.table("users").select("campaign_code").eq("user_id", uid).limit(1).execute()
                if user_r.data and user_r.data[0].get("campaign_code"):
                    campaign_code = user_r.data[0]["campaign_code"]
                    # Update payment record with campaign attribution
                    sb.table("payments").update({"campaign_code": campaign_code}).eq("provider_payment_id", payment_id).execute()
                    app.logger.info(f"Payment {payment_id} attributed to campaign {campaign_code}")
            except Exception as e:
                app.logger.error(f"Campaign attribution error: {e}")
            devices = int(metadata.get("devices"))
            months = int(metadata.get("months"))
            email = metadata.get("email", "—")
            days = months * 30
            months_label = {1: "1 месяц", 3: "3 месяца", 12: "1 год"}.get(months, f"{months} мес.")

            # Промокод — добавляем бонусные дни (если type=days)
            promo_id = metadata.get("promo_id")
            promo_code = metadata.get("promo_code")
            promo_type = metadata.get("promo_type")
            promo_value = metadata.get("promo_value")
            try:
                bonus_days_from_promo = int(metadata.get("bonus_days_from_promo", 0) or 0)
            except (TypeError, ValueError):
                bonus_days_from_promo = 0
            if bonus_days_from_promo > 0:
                days += bonus_days_from_promo
                app.logger.info(f"Промокод {promo_code} даёт +{bonus_days_from_promo} дн. user_id={uid}")

            if already_processed:
                app.logger.info(f"[idempotency] skip issue_subscription для {payment_id}")
                result = {"success": True, "skipped": True}
            else:
                result = issue_subscription(uid, devices, days)
                app.logger.info(f"Выдача подписки по платежу {payment_id}: {result}")

            # Записываем использование промокода (после успешной выдачи)
            if promo_id and result.get("success"):
                try:
                    promo_id_int = int(promo_id)
                    # Получаем internal payment_id из нашей таблицы
                    pay_row = sb.table("payments").select("id, amount").eq("provider_payment_id", payment_id).limit(1).execute()
                    internal_pay_id = pay_row.data[0]["id"] if pay_row.data else None

                    # applied_value — что фактически дал промокод
                    if promo_type == "percent":
                        # Скидка в рублях = base_price - final_price (final_price = amount платежа)
                        try:
                            base_price = float(parsed["amount"]) / (1 - int(promo_value) / 100)
                            applied_value = round(base_price - float(parsed["amount"]), 2)
                        except Exception:
                            applied_value = None
                    else:  # days
                        applied_value = bonus_days_from_promo

                    # Идемпотентность: не дублируем запись если пользователь уже использовал этот промокод (П.5)
                    already_used = sb.table("promocode_uses").select("id").eq("promocode_id", promo_id_int).eq("user_id", uid).limit(1).execute()
                    if already_used.data:
                        app.logger.info(f"Промокод {promo_code} уже был записан для user_id={uid} — пропускаем")
                    else:
                        # Атомарная проверка лимита: читаем текущее состояние + условное обновление
                        promo_cur = sb.table("promocodes").select("uses_count, max_uses").eq("id", promo_id_int).limit(1).execute()
                        if promo_cur.data:
                            pc = promo_cur.data[0]
                            cur_uses = (pc.get("uses_count") or 0)
                            max_uses = pc.get("max_uses")
                            if max_uses and cur_uses >= max_uses:
                                app.logger.warning(f"Промокод {promo_code} уже исчерпан (race condition): {cur_uses}/{max_uses}")
                            else:
                                sb.table("promocode_uses").insert({
                                    "promocode_id": promo_id_int,
                                    "user_id": uid,
                                    "payment_id": internal_pay_id,
                                    "applied_value": applied_value,
                                }).execute()
                                # Условное обновление: только если uses_count не изменился (оптимистичная блокировка)
                                upd = sb.table("promocodes").update({"uses_count": cur_uses + 1}).eq("id", promo_id_int).eq("uses_count", cur_uses).execute()
                                if not upd.data:
                                    # Другой webhook успел обновить — просто логируем
                                    app.logger.warning(f"Промокод {promo_code}: race condition при инкременте, проверьте вручную")
                                app.logger.info(f"Промокод {promo_code} зафиксирован для user_id={uid}")
                except Exception as e:
                    app.logger.error(f"Не удалось записать использование промокода: {e}")

            # Реферальный бонус — рефереру +7 дней за оплату другом
            try:
                user_row = sb.table("users").select("referrer_id").eq("user_id", uid).limit(1).execute()
                referrer_id = (user_row.data[0].get("referrer_id") if user_row.data else None)
                if referrer_id and referrer_id != uid:
                    apply_referral_bonus(referrer_id, 7, f"Друг оплатил подписку")
                    app.logger.info(f"Реф.бонус 7 дней начислен реферу {referrer_id} за оплату user_id={uid}")
            except Exception as e:
                app.logger.error(f"Ошибка начисления реф.бонуса: {e}")

            if result.get("success"):
                # Короткое уведомление пользователю — без ссылки, она в боте
                user_text = (
                    f"✅ <b>Оплата прошла!</b>\n\n"
                    f"Подписка активирована. Откройте раздел «Подключиться» в боте — там ваша ссылка и инструкция."
                )
                notify_user(uid, user_text)

                # Уведомление админам о новой оплате + напоминание про чек
                admin_text = (
                    f"💰 <b>Новая оплата!</b>\n\n"
                    f"👤 user_id: <code>{uid}</code>\n"
                    f"📦 {months_label}, {devices} уст.\n"
                    f"💵 Сумма: <b>{parsed['amount']} ₽</b>\n"
                    f"📧 Email: <code>{email}</code>\n"
                    f"🆔 Платёж: <code>{payment_id}</code>\n\n"
                    f"⚠️ Не забудь сформировать чек в «Мой налог»"
                )
                try:
                    notify_user(SUPERADMIN_ID, admin_text)
                except Exception as e:
                    app.logger.error(f"Не удалось уведомить суперадмина: {e}")
        except Exception as e:
            app.logger.error(f"Ошибка выдачи подписки по {payment_id}: {e}")

    return jsonify({"ok": True}), 200



# ──────────────────────────────────────────────────────────────────────
# AUTO-INSTALL SERVER ENDPOINTS
# ──────────────────────────────────────────────────────────────────────

@app.route('/admin-api/install_server', methods=['POST', 'OPTIONS'])
def install_server_start():
    """Стартует автоматическую установку нового сервера.
    Body JSON:
      server_ip, ssh_password, country_name, country_flag, country_code, code_slug,
      [ssh_port=22], [sort_order=99]
    Returns: {success, install_uuid}
    """
    if request.method == 'OPTIONS':
        resp = app.make_default_options_response()
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        return resp
    try:
        data = request.json or {}
        required = ["server_ip", "ssh_password", "country_name", "country_flag", "country_code", "code_slug"]
        missing = [f for f in required if not data.get(f)]
        if missing:
            return jsonify({"success": False, "error": f"missing fields: {missing}"}), 400

        # Создаём запись в БД
        install_uuid = create_installation(
            sb_client=sb,
            server_ip=data["server_ip"],
            country_name=data["country_name"],
            country_flag=data["country_flag"],
            country_code=data["country_code"],
            code_slug=data["code_slug"],
            sort_order=int(data.get("sort_order") or 99),
            ssh_port=int(data.get("ssh_port") or 22),
        )

        # Стартуем поток установки
        start_installation_thread(
            sb_client=sb,
            install_uuid=install_uuid,
            ssh_password=data["ssh_password"],
            logger=app.logger,
        )

        resp = jsonify({"success": True, "install_uuid": install_uuid})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    except Exception as e:
        app.logger.error(f"install_server_start error: {e}")
        resp = jsonify({"success": False, "error": str(e)})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp, 500


@app.route('/admin-api/install_server/<install_uuid>/status', methods=['GET', 'OPTIONS'])
def install_server_status(install_uuid):
    """Возвращает текущее состояние установки.
    Для polling фронтом каждые 1-2 сек.
    """
    if request.method == 'OPTIONS':
        resp = app.make_default_options_response()
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        return resp
    try:
        r = sb.table("server_installations").select("*").eq("install_uuid", install_uuid).limit(1).execute()
        if not r.data:
            return jsonify({"success": False, "error": "not found"}), 404
        row = r.data[0]
        # Чувствительные поля не выводим целиком
        # panel_password покажем только частично
        if row.get("panel_password"):
            pp = row["panel_password"]
            row["panel_password_masked"] = pp[:3] + "***" + pp[-3:] if len(pp) > 6 else "***"
        # private_key не выводим вообще
        row.pop("private_key", None)

        resp = jsonify({"success": True, "data": row})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    except Exception as e:
        app.logger.error(f"install_server_status error: {e}")
        resp = jsonify({"success": False, "error": str(e)})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp, 500


@app.route('/admin-api/install_server/<install_uuid>/select_target', methods=['POST', 'OPTIONS'])
def install_server_select_target(install_uuid):
    """Админ выбрал Reality target. Сохраняем выбор и перезапускаем поток установки.
    Body JSON: { target: "chat.deepseek.com", ssh_password: "..." }
    """
    if request.method == 'OPTIONS':
        resp = app.make_default_options_response()
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        return resp
    try:
        data = request.json or {}
        target = data.get("target")
        ssh_password = data.get("ssh_password")
        if not target:
            return jsonify({"success": False, "error": "target is required"}), 400
        if not ssh_password:
            return jsonify({"success": False, "error": "ssh_password is required for continuation"}), 400

        # Проверяем что установка существует и в правильном статусе
        r = sb.table("server_installations").select("*").eq("install_uuid", install_uuid).limit(1).execute()
        if not r.data:
            return jsonify({"success": False, "error": "installation not found"}), 404
        row = r.data[0]
        if row.get("status") != "awaiting_target":
            return jsonify({"success": False, "error": f"wrong status: {row.get('status')}"}), 400

        # Сохраняем выбор и перезапускаем установку
        sb.table("server_installations").update({
            "selected_target": target,
            "status": "pending",
        }).eq("install_uuid", install_uuid).execute()

        start_installation_thread(
            sb_client=sb,
            install_uuid=install_uuid,
            ssh_password=ssh_password,
            logger=app.logger,
        )

        resp = jsonify({"success": True, "message": "Установка продолжена"})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    except Exception as e:
        app.logger.error(f"install_server_select_target error: {e}")
        resp = jsonify({"success": False, "error": str(e)})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp, 500


@app.route('/admin-api/installations', methods=['GET', 'OPTIONS'])
def installations_list():
    """Список последних установок (для отображения истории/активных)."""
    if request.method == 'OPTIONS':
        resp = app.make_default_options_response()
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp
    try:
        r = sb.table("server_installations").select(
            "id, install_uuid, server_ip, country_name, country_flag, code_slug, "
            "status, current_step, progress_percent, error_message, "
            "started_at, completed_at, final_server_id"
        ).order("started_at", desc=True).limit(20).execute()
        resp = jsonify({"success": True, "data": r.data or []})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    except Exception as e:
        resp = jsonify({"success": False, "error": str(e)})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp, 500


@app.route('/admin-api/reality_target_candidates', methods=['GET', 'OPTIONS'])
def reality_target_candidates():
    """Возвращает справочный список Reality target кандидатов."""
    if request.method == 'OPTIONS':
        resp = app.make_default_options_response()
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    resp = jsonify({"success": True, "data": REALITY_TARGET_CANDIDATES})
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp




# === ADMIN AUTH BLOCK ===
import secrets as _secrets
import time as _time
from threading import Lock as _LockCls

try:
    from config import ADMIN_TG_IDS, ADMIN_SESSION_DAYS, ADMIN_LOGIN_TOKEN_MINUTES
except ImportError:
    ADMIN_TG_IDS = [784871620, 1027228622]
    ADMIN_SESSION_DAYS = 7
    ADMIN_LOGIN_TOKEN_MINUTES = 10

# --- OTP store (in-memory, Flask single-process) ---
_otp_store: dict = {}   # {tg_id: {code, expires, attempts, next_allowed}}
_otp_mutex = _LockCls()
OTP_TTL_SEC = 300        # 5 минут
OTP_MAX_ATTEMPTS = 5
OTP_COOLDOWN_SEC = 60    # 1 минута между запросами кода


def _now_utc():
    return datetime.utcnow()


def _iso(dt):
    return dt.isoformat()


def _get_client_ip():
    # Берём X-Forwarded-For если есть (nginx), иначе remote_addr
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or ""


def get_session_by_token(session_token: str):
    """Вернуть валидную (не отозванную, не истёкшую) сессию или None."""
    if not session_token:
        return None
    try:
        r = sb.table("admin_sessions").select("*").eq("session_token", session_token).limit(1).execute()
        if not r.data:
            return None
        s = r.data[0]
        if s.get("is_revoked"):
            return None
        exp_raw = s.get("expires_at")
        try:
            exp = datetime.fromisoformat(exp_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None
        if exp <= _now_utc():
            return None
        # Проверяем что tg_id всё ещё в whitelist (если убрали из конфига — выкидываем)
        if int(s.get("tg_id") or 0) not in ADMIN_TG_IDS:
            return None
        return s
    except Exception as e:
        print(f"get_session_by_token error: {e}")
        return None


def touch_session(session_id: int):
    """Обновляет last_used_at."""
    try:
        sb.table("admin_sessions").update({"last_used_at": _iso(_now_utc())}).eq("id", session_id).execute()
    except Exception:
        pass


# --- Middleware: на все /admin-api/* требуем cookie, кроме /auth/* и OPTIONS ---
@app.before_request
def _admin_auth_gate():
    p = request.path or ""
    if not p.startswith("/admin-api/"):
        return None
    if request.method == "OPTIONS":
        return None
    # Auth endpoints — без проверки
    if p.startswith("/admin-api/auth/"):
        return None
    # Дальше проверка cookie
    token = request.cookies.get("admin_session")
    s = get_session_by_token(token)
    if not s:
        resp = jsonify({"success": False, "error": "unauthorized", "code": "AUTH_REQUIRED"})
        resp.status_code = 401
        resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp
    touch_session(s["id"])
    # Прокидываем в request для возможного логирования
    request.admin_tg_id = int(s.get("tg_id"))
    request.admin_username = s.get("tg_username") or ""
    return None


# --- /admin-api/auth/start ---
@app.route("/admin-api/auth/start", methods=["POST", "OPTIONS"])
def auth_start():
    if request.method == "OPTIONS":
        return make_response("", 204)
    login_token = _secrets.token_urlsafe(32)
    expires_at = _now_utc() + timedelta(minutes=ADMIN_LOGIN_TOKEN_MINUTES)
    try:
        sb.table("admin_login_attempts").insert({
            "login_token": login_token,
            "status": "pending",
            "expires_at": _iso(expires_at),
            "ip_address": _get_client_ip(),
            "user_agent": (request.headers.get("User-Agent") or "")[:500],
        }).execute()
    except Exception as e:
        return jsonify({"success": False, "error": f"db: {e}"}), 500

    # Готовим deeplink в бот
    try:
        from config import MAIN_BOT_USERNAME
    except Exception:
        MAIN_BOT_USERNAME = "MaxArtVPN_bot"
    deeplink = f"https://t.me/{MAIN_BOT_USERNAME}?start=login_admin_{login_token}"

    return jsonify({
        "success": True,
        "login_token": login_token,
        "deeplink": deeplink,
        "expires_in_minutes": ADMIN_LOGIN_TOKEN_MINUTES,
    })


# --- /admin-api/auth/request_code ---
@app.route("/admin-api/auth/request_code", methods=["POST", "OPTIONS"])
def auth_request_code():
    """Запросить OTP-код: генерируем 6 цифр и отправляем в Telegram."""
    if request.method == "OPTIONS":
        return make_response("", 204)
    data = request.get_json() or {}
    try:
        tg_id = int(data.get("tg_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "not_found"}), 400

    now = _time.time()
    with _otp_mutex:
        existing = _otp_store.get(tg_id, {})
        next_allowed = existing.get("next_allowed", 0)
        if now < next_allowed:
            wait = int(next_allowed - now)
            return jsonify({"success": False, "error": "too_soon", "wait_seconds": wait}), 429
        if tg_id not in ADMIN_TG_IDS:
            return jsonify({"success": False, "error": "not_found"}), 400
        code = f"{_secrets.randbelow(1000000):06d}"
        _otp_store[tg_id] = {
            "code": code,
            "expires": now + OTP_TTL_SEC,
            "attempts": 0,
            "next_allowed": now + OTP_COOLDOWN_SEC,
        }

    # Отправляем через HTTP API бота
    try:
        from config import BOT_TOKEN as _bt
        import requests as _rq
        _rq.post(
            f"https://api.telegram.org/bot{_bt}/sendMessage",
            json={
                "chat_id": tg_id,
                "text": (
                    "🔐 <b>Код для входа в админку TuVPN</b>\n\n"
                    f"<code>{code}</code>\n\n"
                    "Действует 5 минут. Если вы не запрашивали вход — проигнорируйте."
                ),
                "parse_mode": "HTML",
            },
            timeout=10,
        )
    except Exception as e:
        app.logger.error(f"OTP send error for {tg_id}: {e}")

    return jsonify({"success": True})


# --- /admin-api/auth/verify_code ---
@app.route("/admin-api/auth/verify_code", methods=["POST", "OPTIONS"])
def auth_verify_code():
    """Проверить OTP-код и выдать сессию."""
    if request.method == "OPTIONS":
        return make_response("", 204)
    data = request.get_json() or {}
    try:
        tg_id = int(data.get("tg_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "invalid_code"}), 400
    code = str(data.get("code") or "").strip()

    now = _time.time()
    with _otp_mutex:
        entry = _otp_store.get(tg_id)
        if not entry or not entry.get("code"):
            return jsonify({"success": False, "error": "invalid_code"}), 400
        if now > entry["expires"]:
            del _otp_store[tg_id]
            return jsonify({"success": False, "error": "expired"}), 400
        entry["attempts"] += 1
        if entry["attempts"] > OTP_MAX_ATTEMPTS:
            del _otp_store[tg_id]
            return jsonify({"success": False, "error": "too_many_attempts"}), 400
        if code != entry["code"] or tg_id not in ADMIN_TG_IDS:
            remaining = max(0, OTP_MAX_ATTEMPTS - entry["attempts"])
            return jsonify({"success": False, "error": "invalid_code", "remaining": remaining}), 400
        # Код верный — удаляем запись
        del _otp_store[tg_id]

    # Создаём сессию
    session_token = _secrets.token_urlsafe(48)
    session_exp = _now_utc() + timedelta(days=ADMIN_SESSION_DAYS)
    try:
        sb.table("admin_sessions").insert({
            "session_token": session_token,
            "tg_id": tg_id,
            "tg_username": "",
            "expires_at": _iso(session_exp),
            "ip_address": _get_client_ip(),
            "user_agent": (request.headers.get("User-Agent") or "")[:500],
        }).execute()
        # Аудит-лог попытки
        sb.table("admin_login_attempts").insert({
            "login_token": f"otp_{tg_id}_{int(now)}",
            "status": "confirmed",
            "tg_id": tg_id,
            "tg_username": "",
            "session_token": session_token,
            "expires_at": _iso(_now_utc() + timedelta(minutes=5)),
            "ip_address": _get_client_ip(),
            "user_agent": (request.headers.get("User-Agent") or "")[:500],
            "confirmed_at": _iso(_now_utc()),
        }).execute()
    except Exception as e:
        app.logger.error(f"OTP session create error: {e}")
        return jsonify({"success": False, "error": "db_error"}), 500

    resp = make_response(jsonify({"success": True, "tg_id": tg_id}))
    resp.set_cookie(
        "admin_session", session_token,
        max_age=ADMIN_SESSION_DAYS * 86400,
        httponly=True, secure=True, samesite="Lax", path="/",
    )
    return resp


# --- /admin-api/auth/poll ---
@app.route("/admin-api/auth/poll", methods=["GET", "OPTIONS"])
def auth_poll():
    """Опрашивается фронтом каждые 2 сек. Если бот подтвердил вход — выдаём cookie."""
    if request.method == "OPTIONS":
        return make_response("", 204)
    token = request.args.get("token") or ""
    if not token:
        return jsonify({"success": False, "error": "token required"}), 400
    try:
        r = sb.table("admin_login_attempts").select("*").eq("login_token", token).limit(1).execute()
        if not r.data:
            return jsonify({"success": False, "status": "not_found"}), 404
        att = r.data[0]
        # Проверим истечение
        try:
            exp = datetime.fromisoformat(att["expires_at"].replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            exp = _now_utc()
        if att["status"] == "pending" and exp <= _now_utc():
            sb.table("admin_login_attempts").update({"status": "expired"}).eq("login_token", token).execute()
            return jsonify({"success": False, "status": "expired"})

        if att["status"] == "pending":
            return jsonify({"success": True, "status": "pending"})

        if att["status"] == "rejected":
            return jsonify({"success": False, "status": "rejected"})

        if att["status"] != "confirmed":
            return jsonify({"success": False, "status": att["status"]})

        # confirmed → выдаём cookie
        session_token = att.get("session_token")
        if not session_token:
            return jsonify({"success": False, "error": "no session_token in attempt"}), 500

        resp = make_response(jsonify({
            "success": True,
            "status": "confirmed",
            "tg_id": att.get("tg_id"),
            "tg_username": att.get("tg_username"),
        }))
        # Cookie на ADMIN_SESSION_DAYS дней, HttpOnly, Secure (через https), SameSite=Lax
        max_age = ADMIN_SESSION_DAYS * 86400
        resp.set_cookie(
            "admin_session",
            session_token,
            max_age=max_age,
            httponly=True,
            secure=True,
            samesite="Lax",
            path="/",
        )
        return resp
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# --- /admin-api/auth/me ---
@app.route("/admin-api/auth/me", methods=["GET", "OPTIONS"])
def auth_me():
    if request.method == "OPTIONS":
        return make_response("", 204)
    token = request.cookies.get("admin_session")
    s = get_session_by_token(token)
    if not s:
        return jsonify({"success": False, "error": "not_authenticated"}), 401
    return jsonify({
        "success": True,
        "tg_id": s.get("tg_id"),
        "tg_username": s.get("tg_username"),
        "created_at": s.get("created_at"),
        "expires_at": s.get("expires_at"),
    })


# --- /admin-api/auth/logout ---
@app.route("/admin-api/auth/logout", methods=["POST", "OPTIONS"])
def auth_logout():
    if request.method == "OPTIONS":
        return make_response("", 204)
    token = request.cookies.get("admin_session")
    if token:
        try:
            sb.table("admin_sessions").update({"is_revoked": True}).eq("session_token", token).execute()
        except Exception:
            pass
    resp = make_response(jsonify({"success": True}))
    resp.set_cookie("admin_session", "", max_age=0, path="/")
    return resp


# === END ADMIN AUTH BLOCK ===





# === GENERIC DB PROXY ===
# Generic CRUD для админки: фронт ходит сюда вместо прямого Supabase
# Защищено auth middleware /admin-api/* + cookie + whitelist админов

# Whitelist таблиц и разрешённых методов
# methods: 'r' = read, 'w' = write (insert/update/delete)
_DB_PROXY_TABLES = {
    "users": "rw",
    "subscriptions": "rw",
    "payments": "rw",
    "promocodes": "rw",
    "promocode_uses": "r",
    "referrals": "rw",
    "support_tickets": "rw",
    "support_messages": "rw",
    "support_admins": "rw",
    "servers": "rw",
    "campaigns": "rw",
    "campaign_clicks": "r",
    "user_devices": "rw",
    "server_installations": "r",
    "broadcasts": "r",
    "admin_roles": "r",
    # Не добавлены намеренно: admin_sessions, admin_login_attempts
    # (они никогда не должны быть доступны через generic API)
}

_DB_PROXY_MAX_LIMIT = 5000  # защита от случайных тяжёлых запросов


def _db_proxy_check(table: str, mode: str):
    """Проверка whitelist'а. Возвращает (allowed, error_response)."""
    if table not in _DB_PROXY_TABLES:
        return False, (jsonify({"success": False, "error": "table_not_allowed", "table": table}), 403)
    allowed_modes = _DB_PROXY_TABLES[table]
    if mode == "r" and "r" not in allowed_modes:
        return False, (jsonify({"success": False, "error": "read_not_allowed"}), 403)
    if mode == "w" and "w" not in allowed_modes:
        return False, (jsonify({"success": False, "error": "write_not_allowed"}), 403)
    return True, None


# ==================== BROADCASTS ====================

def _get_recipient_ids(audience, campaign_filter=None, target_user_id=None, target_user_ids=None):
    """Возвращает список user_id для указанной аудитории рассылки."""
    if audience == "single":
        return [target_user_id] if target_user_id else []
    if audience == "custom_list":
        return [int(x) for x in (target_user_ids or []) if x]

    users_r = sb.table("users").select("user_id,campaign_code").execute()
    all_users = users_r.data or []

    if campaign_filter and campaign_filter != "all":
        all_users = [u for u in all_users if u.get("campaign_code") == campaign_filter]

    all_ids = [u["user_id"] for u in all_users]

    if audience == "active":
        subs_r = sb.table("subscriptions").select("user_id").eq("status", "active").execute()
        active_set = {s["user_id"] for s in (subs_r.data or [])}
        return [uid for uid in all_ids if uid in active_set]
    elif audience == "inactive":
        subs_r = sb.table("subscriptions").select("user_id").eq("status", "active").execute()
        active_set = {s["user_id"] for s in (subs_r.data or [])}
        return [uid for uid in all_ids if uid not in active_set]
    elif audience == "expires_6h":
        from datetime import timedelta
        now = datetime.utcnow()
        cutoff = (now + timedelta(hours=6)).isoformat()
        subs_r = sb.table("subscriptions").select("user_id").eq("status", "active").lte("expires_at", cutoff).gte("expires_at", now.isoformat()).execute()
        exp_set = {s["user_id"] for s in (subs_r.data or [])}
        return [uid for uid in all_ids if uid in exp_set]
    elif audience == "expired_unpaid_14d":
        from datetime import timedelta
        cutoff_from = (datetime.utcnow() - timedelta(days=14)).isoformat()
        subs_r = sb.table("subscriptions").select("user_id").eq("status", "inactive").gte("expires_at", cutoff_from).execute()
        exp_ids = {s["user_id"] for s in (subs_r.data or [])}
        pay_r = sb.table("payments").select("user_id").eq("status", "succeeded").gte("paid_at", cutoff_from).execute()
        paid_ids = {p["user_id"] for p in (pay_r.data or [])}
        return [uid for uid in all_ids if uid in exp_ids and uid not in paid_ids]
    elif audience == "utm_no_device":
        dev_r = sb.table("user_devices").select("user_id").eq("is_active", True).execute()
        dev_set = {d["user_id"] for d in (dev_r.data or [])}
        camp_users = [u["user_id"] for u in all_users if u.get("campaign_code")]
        return [uid for uid in camp_users if uid not in dev_set]
    elif audience == "utm_never_paid":
        # UTM-пользователи, у которых нет ни одного успешного платежа
        camp_users = [u["user_id"] for u in all_users if u.get("campaign_code")]
        if not camp_users:
            return []
        pay_r = sb.table("payments").select("user_id").eq("status", "succeeded").execute()
        paid_set = {p["user_id"] for p in (pay_r.data or [])}
        return [uid for uid in camp_users if uid not in paid_set]
    elif audience == "utm_expired":
        # UTM-пользователи, у которых подписка была но сейчас неактивна
        camp_users = [u["user_id"] for u in all_users if u.get("campaign_code")]
        if not camp_users:
            return []
        subs_r = sb.table("subscriptions").select("user_id,status").execute()
        active_set = {s["user_id"] for s in (subs_r.data or []) if s.get("status") == "active"}
        had_sub_set = {s["user_id"] for s in (subs_r.data or [])}
        return [uid for uid in camp_users if uid in had_sub_set and uid not in active_set]
    else:  # all
        return all_ids


@app.route('/admin-api/broadcasts', methods=['GET', 'OPTIONS'])
def list_broadcasts():
    """История рассылок."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        r = sb.table("broadcasts").select("*").order("created_at", desc=True).limit(100).execute()
        return jsonify({"broadcasts": r.data or []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/admin-api/broadcast/preview', methods=['POST', 'OPTIONS'])
def broadcast_preview():
    """Предпросмотр: сколько пользователей получат рассылку."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        data = request.get_json() or {}
        audience = data.get("audience", "all")
        campaign_filter = data.get("campaign_filter") or "all"
        target_user_id = data.get("target_user_id")
        target_user_ids = data.get("target_user_ids")
        ids = _get_recipient_ids(audience, campaign_filter, target_user_id, target_user_ids)
        return jsonify({"success": True, "count": len(ids)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/broadcast/send', methods=['POST', 'OPTIONS'])
def broadcast_send():
    """Отправить рассылку с сохранением в историю."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        data = request.get_json() or {}
        audience = data.get("audience", "all")
        message_text = (data.get("message_text") or "").strip()
        campaign_filter = data.get("campaign_filter") or "all"
        target_user_id = data.get("target_user_id")
        target_user_ids = data.get("target_user_ids")
        bonus_days = int(data.get("bonus_days") or 0)
        button_action = data.get("button_action") or ""

        if not message_text:
            return jsonify({"success": False, "error": "message_text required"}), 400

        _bc_buttons = {
            "buy":     {"text": "💳 Продлить подписку", "callback_data": "buy"},
            "connect": {"text": "🔌 Подключиться",       "callback_data": "connect"},
            "back":    {"text": "🏠 Главное меню",        "callback_data": "back"},
            "howto":   {"text": "📘 Инструкция",          "callback_data": "howto"},
        }
        reply_markup = None
        if button_action and button_action in _bc_buttons:
            btn = _bc_buttons[button_action]
            reply_markup = {"inline_keyboard": [[{"text": btn["text"], "callback_data": btn["callback_data"]}]]}

        ids = _get_recipient_ids(audience, campaign_filter, target_user_id, target_user_ids)

        sent = 0
        blocked = 0
        for uid in ids:
            if notify_user(uid, message_text, reply_markup):
                sent += 1
                if bonus_days > 0:
                    try:
                        issue_subscription(uid, None, bonus_days)
                    except Exception:
                        pass
            else:
                blocked += 1

        try:
            sb.table("broadcasts").insert({
                "audience": audience,
                "campaign_filter": campaign_filter if campaign_filter != "all" else None,
                "target_user_id": target_user_id,
                "message_text": message_text,
                "button_action": button_action or None,
                "recipients_count": len(ids),
                "sent_count": sent,
                "blocked_count": blocked,
                "bonus_days": bonus_days,
                "status": "completed" if blocked == 0 else ("partial" if sent > 0 else "failed"),
                "created_at": datetime.utcnow().isoformat(),
            }).execute()
        except Exception:
            pass

        return jsonify({"success": True, "sent": sent, "total": len(ids)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== MONITOR ====================

@app.route('/admin-api/monitor/settings', methods=['GET', 'POST', 'OPTIONS'])
def monitor_settings():
    """Настройки демона мониторинга (интервал проверок)."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        if request.method == 'GET':
            r = sb.table("monitor_settings").select("*").eq("id", 1).limit(1).execute()
            settings = r.data[0] if r.data else {"interval_sec": 300, "enabled": True}
            return jsonify({"settings": settings})
        else:
            body = request.get_json() or {}
            interval = int(body.get("interval_sec", 300))
            # upsert записи с id=1
            try:
                sb.table("monitor_settings").update({"interval_sec": interval}).eq("id", 1).execute()
            except Exception:
                sb.table("monitor_settings").insert({"id": 1, "interval_sec": interval, "enabled": True}).execute()
            return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/monitor/latest', methods=['GET', 'OPTIONS'])
def monitor_latest():
    """Последнее состояние каждого сервера."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        servers_r = sb.table("servers").select("*").eq("is_active", True).order("sort_order").execute()
        servers = servers_r.data or []

        from datetime import timedelta
        cutoff_24h = (datetime.utcnow() - timedelta(hours=24)).isoformat()

        result = []
        for srv in servers:
            code = srv["code"]
            # последняя запись здоровья
            h_r = sb.table("server_health").select("*").eq("server_code", code).order("checked_at", desc=True).limit(1).execute()
            health = h_r.data[0] if h_r.data else {}

            # uptime за 24 часа
            all_r = sb.table("server_health").select("is_up").eq("server_code", code).gte("checked_at", cutoff_24h).execute()
            all_checks = all_r.data or []
            uptime_24h = None
            if all_checks:
                up_count = sum(1 for c in all_checks if c.get("is_up"))
                uptime_24h = round(up_count / len(all_checks) * 100, 1)

            result.append({
                "code": code,
                "name": srv.get("country_name", code),
                "flag": srv.get("country_flag", ""),
                "ip": srv.get("server_ip", ""),
                "sni": srv.get("sni", ""),
                "health": health,
                "uptime_24h": uptime_24h,
            })

        return jsonify({"servers": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/admin-api/monitor/health', methods=['GET', 'OPTIONS'])
def monitor_health():
    """История проверок серверов за N часов."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        hours = int(request.args.get("hours", 6))
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        r = sb.table("server_health").select("server_code,checked_at,is_up,latency_ms,clients_count,target_ok").gte("checked_at", cutoff).order("checked_at").execute()
        return jsonify({"health": r.data or []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== ANALYTICS ====================

@app.route('/admin-api/analytics/funnel', methods=['GET', 'OPTIONS'])
def analytics_funnel():
    """Воронка конверсии: регистрации → триал → покупка → активная."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        from datetime import timedelta
        campaign = request.args.get("campaign", "all")
        # Поддерживаем как period так и from_date/to_date (П.23)
        from_date = request.args.get("from_date")
        to_date = request.args.get("to_date")
        if from_date and to_date:
            cutoff = from_date
            cutoff_end = to_date + "T23:59:59"
        else:
            period = int(request.args.get("period", 30))
            cutoff = (datetime.utcnow() - timedelta(days=period)).isoformat()
            cutoff_end = None

        users_q = sb.table("users").select("user_id,campaign_code").gte("created_at", cutoff)
        if cutoff_end:
            users_q = users_q.lte("created_at", cutoff_end)
        if campaign != "all":
            users_q = users_q.eq("campaign_code", campaign)
        users_r = users_q.execute()
        user_ids = [u["user_id"] for u in (users_r.data or [])]
        total_reg = len(user_ids)

        if not user_ids:
            return jsonify({"success": True, "funnel": [
                {"step": "Зарегистрировались", "count": 0, "pct": 100},
                {"step": "Получили триал", "count": 0, "pct": 0},
                {"step": "Оформили подписку", "count": 0, "pct": 0},
                {"step": "Активная подписка", "count": 0, "pct": 0},
            ]})

        uid_set = set(user_ids)

        # триал = есть запись в subscriptions (status не важен)
        subs_q = sb.table("subscriptions").select("user_id").gte("created_at", cutoff)
        if cutoff_end:
            subs_q = subs_q.lte("created_at", cutoff_end)
        subs_r = subs_q.execute()
        trialed = len({s["user_id"] for s in (subs_r.data or []) if s["user_id"] in uid_set})

        # оформили = есть успешный платёж
        pay_q = sb.table("payments").select("user_id").eq("status", "succeeded").gte("paid_at", cutoff)
        if cutoff_end:
            pay_q = pay_q.lte("paid_at", cutoff_end)
        pay_r = pay_q.execute()
        paid = len({p["user_id"] for p in (pay_r.data or []) if p["user_id"] in uid_set})

        # активная подписка сейчас
        act_r = sb.table("subscriptions").select("user_id").eq("status", "active").execute()
        active_now = len({s["user_id"] for s in (act_r.data or []) if s["user_id"] in uid_set})

        def pct(n):
            return round(n / total_reg * 100, 1) if total_reg else 0

        funnel = [
            {"step": "Зарегистрировались", "count": total_reg, "pct": 100},
            {"step": "Получили триал", "count": trialed, "pct": pct(trialed)},
            {"step": "Оформили подписку", "count": paid, "pct": pct(paid)},
            {"step": "Активная подписка", "count": active_now, "pct": pct(active_now)},
        ]
        return jsonify({"success": True, "funnel": funnel})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/analytics/cohorts', methods=['GET', 'OPTIONS'])
def analytics_cohorts():
    """Когортный анализ: конверсия и LTV по месяцам регистрации."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        users_r = sb.table("users").select("user_id,created_at,campaign_code").execute()
        users = users_r.data or []

        pay_r = sb.table("payments").select("user_id,amount,paid_at").eq("status", "succeeded").execute()
        payments = pay_r.data or []

        # группировка пользователей по месяцу
        from collections import defaultdict
        cohorts_map = defaultdict(list)
        for u in users:
            if not u.get("created_at"):
                continue
            month = u["created_at"][:7]  # "YYYY-MM"
            cohorts_map[month].append(u["user_id"])

        pay_by_user = defaultdict(float)
        for p in payments:
            pay_by_user[p["user_id"]] += float(p.get("amount") or 0)

        cohorts = []
        for month in sorted(cohorts_map.keys(), reverse=True)[:12]:
            uid_list = cohorts_map[month]
            new_users = len(uid_list)
            paid_users = sum(1 for uid in uid_list if pay_by_user.get(uid, 0) > 0)
            total_ltv = sum(pay_by_user.get(uid, 0) for uid in uid_list)
            cohorts.append({
                "month": month,
                "new_users": new_users,
                "paid_users": paid_users,
                "paid_pct": round(paid_users / new_users * 100, 1) if new_users else 0,
                "ltv_per_user": round(total_ltv / new_users, 2) if new_users else 0,
            })

        # UTM-когорты
        camps_r = sb.table("campaigns").select("code,name,cost").execute()
        camps = {c["code"]: c for c in (camps_r.data or [])}

        utm_map = defaultdict(list)
        for u in users:
            code = u.get("campaign_code")
            if code:
                utm_map[code].append(u["user_id"])

        utm_cohorts = []
        for code, uid_list in utm_map.items():
            new_users = len(uid_list)
            total_ltv = sum(pay_by_user.get(uid, 0) for uid in uid_list)
            ltv_per_user = round(total_ltv / new_users, 2) if new_users else 0
            camp = camps.get(code, {})
            cost = float(camp.get("cost") or 0)
            cac = round(cost / new_users, 2) if new_users and cost else 0
            roi_pct = round((total_ltv - cost) / cost * 100) if cost > 0 else None
            utm_cohorts.append({
                "name": camp.get("name") or code,
                "new_users": new_users,
                "ltv_per_user": ltv_per_user,
                "cac": cac,
                "roi_pct": roi_pct,
            })
        utm_cohorts.sort(key=lambda x: x["new_users"], reverse=True)

        return jsonify({"success": True, "cohorts": cohorts, "utm_cohorts": utm_cohorts})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin-api/analytics/calendar', methods=['GET', 'OPTIONS'])
def analytics_calendar():
    """Календарь истечений подписок на ближайшие 30 дней."""
    if request.method == 'OPTIONS':
        return make_response('', 204)
    try:
        from datetime import timedelta
        now = datetime.utcnow()
        cutoff = (now + timedelta(days=30)).isoformat()
        subs_r = sb.table("subscriptions").select("user_id,expires_at,devices").eq("status", "active").gte("expires_at", now.isoformat()).lte("expires_at", cutoff).execute()
        subs = subs_r.data or []

        # загрузим имена юзеров
        if subs:
            uid_list = list({s["user_id"] for s in subs})
            # Supabase ограничивает in() — разобьём если нужно
            users_r = sb.table("users").select("user_id,first_name,last_name,username").in_("user_id", uid_list[:500]).execute()
            user_map = {u["user_id"]: u for u in (users_r.data or [])}
        else:
            user_map = {}

        from collections import defaultdict
        days_map = defaultdict(list)
        for s in subs:
            exp = s["expires_at"]
            day = exp[:10]
            days_left = (datetime.fromisoformat(exp[:19]) - now).days
            u = user_map.get(s["user_id"], {})
            days_map[day].append({
                "user_id": s["user_id"],
                "username": u.get("username"),
                "first_name": u.get("first_name"),
                "last_name": u.get("last_name"),
                "devices": s["devices"],
                "days_left": max(0, days_left),
            })

        days = [{"date": d, "items": days_map[d]} for d in sorted(days_map.keys())]
        total = len(subs)
        next7_cutoff = (now + timedelta(days=7)).isoformat()[:10]
        next3_cutoff = (now + timedelta(days=3)).isoformat()[:10]
        next7 = sum(len(v) for k, v in days_map.items() if k <= next7_cutoff)
        next3 = sum(len(v) for k, v in days_map.items() if k <= next3_cutoff)

        return jsonify({"success": True, "days": days, "summary": {"total": total, "next7": next7, "next3": next3}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== TODAY STATS ====================

@app.route('/admin-api/analytics/today', methods=['GET', 'OPTIONS'])
def analytics_today():
    """Статистика за сегодня: выручка, новые юзеры, платежи."""
    if request.method == 'OPTIONS':
        return make_response("", 204)
    try:
        today = datetime.utcnow().strftime('%Y-%m-%d')
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')

        pays_today = sb.table("payments").select("amount").eq("status", "succeeded").gte("paid_at", today + "T00:00:00").execute().data
        pays_yday = sb.table("payments").select("amount").eq("status", "succeeded").gte("paid_at", yesterday + "T00:00:00").lt("paid_at", today + "T00:00:00").execute().data
        rev_today = sum(float(p.get("amount", 0)) for p in pays_today)
        rev_yday = sum(float(p.get("amount", 0)) for p in pays_yday)

        users_today = sb.table("users").select("user_id", count="exact").gte("created_at", today + "T00:00:00").execute()
        users_yday = sb.table("users").select("user_id", count="exact").gte("created_at", yesterday + "T00:00:00").lt("created_at", today + "T00:00:00").execute()

        open_tix = sb.table("support_tickets").select("id", count="exact").in_("status", ["open", "in_progress"]).execute()

        # Последний статус каждого сервера из server_health
        latest_health = sb.table("server_health").select("server_code,status").order("checked_at", desc=True).limit(100).execute().data
        seen_srv = set()
        offline_count = 0
        for row in latest_health:
            code = row.get("server_code") or row.get("code")
            if code and code not in seen_srv:
                seen_srv.add(code)
                if row.get("status") != "online":
                    offline_count += 1

        return jsonify({
            "success": True,
            "revenue_today": rev_today,
            "revenue_yesterday": rev_yday,
            "payments_today": len(pays_today),
            "new_users_today": users_today.count or 0,
            "new_users_yesterday": users_yday.count or 0,
            "open_tickets": open_tix.count or 0,
            "servers_offline": offline_count,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== ALERTS ====================

@app.route('/admin-api/alerts', methods=['GET', 'OPTIONS'])
def admin_alerts():
    """Алерты для колокольчика: тикеты, серверы offline, платежи без чека."""
    if request.method == 'OPTIONS':
        return make_response("", 204)
    try:
        alerts = []

        open_tix = sb.table("support_tickets").select("id", count="exact").in_("status", ["open", "in_progress"]).execute()
        tcnt = open_tix.count or 0
        if tcnt:
            alerts.append({"type": "tickets", "title": f"Открытых тикетов: {tcnt}", "count": tcnt, "page": "tickets"})

        no_receipt = sb.table("payments").select("id", count="exact").eq("status", "succeeded").eq("provider", "yookassa").is_("receipt_url", "null").execute()
        rcnt = no_receipt.count or 0
        if rcnt:
            alerts.append({"type": "receipt", "title": f"Без чека ЮКасса: {rcnt}", "count": rcnt, "page": "payments"})

        today_start = datetime.utcnow().strftime('%Y-%m-%d') + "T00:00:00"
        tomorrow_start = (datetime.utcnow() + timedelta(days=1)).strftime('%Y-%m-%d') + "T00:00:00"
        expiring = sb.table("subscriptions").select("user_id", count="exact").eq("status", "active").gte("expires_at", today_start).lt("expires_at", tomorrow_start).execute()
        ecnt = expiring.count or 0
        if ecnt:
            alerts.append({"type": "expiring", "title": f"Истекает сегодня: {ecnt}", "count": ecnt, "page": "subs"})

        return jsonify({"success": True, "alerts": alerts, "total": sum(a["count"] for a in alerts)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _db_proxy_log(table: str, op: str):
    """Минимальное логирование действий админа на таблицах."""
    admin = getattr(request, "admin_tg_id", None)
    if admin:
        app.logger.info(f"[admin-db] tg_id={admin} {op} table={table}")


@app.route("/admin-api/db/<table>", methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"])
def db_proxy(table):
    """Generic CRUD через Supabase Python SDK."""
    if request.method == "OPTIONS":
        return make_response("", 204)

    # Проверка whitelist
    mode = "r" if request.method == "GET" else "w"
    ok, err = _db_proxy_check(table, mode)
    if not ok:
        return err

    try:
        # ── GET: SELECT с произвольным PostgREST-like query ──
        if request.method == "GET":
            q = sb.table(table).select(request.args.get("select", "*"))

            # Парсим query string. PostgREST синтаксис:
            #   ?status=eq.active&order=created_at.desc&limit=10
            for key, val in request.args.items():
                if key in ("select", "order", "limit", "offset", "count"):
                    continue
                # Формат: field=eq.value, field=in.(a,b,c), field=like.*foo*
                if "." in val:
                    op, _, v = val.partition(".")
                    op = op.lower()
                    if op == "eq":
                        q = q.eq(key, v)
                    elif op == "neq":
                        q = q.neq(key, v)
                    elif op == "gt":
                        q = q.gt(key, v)
                    elif op == "gte":
                        q = q.gte(key, v)
                    elif op == "lt":
                        q = q.lt(key, v)
                    elif op == "lte":
                        q = q.lte(key, v)
                    elif op == "like":
                        q = q.like(key, v)
                    elif op == "ilike":
                        q = q.ilike(key, v)
                    elif op == "is":
                        q = q.is_(key, v if v != "null" else None)
                    elif op == "in":
                        # in.(a,b,c) → ['a','b','c']
                        v_clean = v.strip("()")
                        q = q.in_(key, v_clean.split(","))
                    else:
                        # Неизвестный оператор — игнорим (можно сделать строже)
                        pass
                else:
                    # Без оператора — считаем eq
                    q = q.eq(key, val)

            # order=field.desc[,field.asc]
            if request.args.get("order"):
                for clause in request.args["order"].split(","):
                    clause = clause.strip()
                    if "." in clause:
                        field, _, direction = clause.partition(".")
                        q = q.order(field, desc=(direction.lower() == "desc"))
                    else:
                        q = q.order(clause)

            # limit/offset
            try:
                limit = int(request.args.get("limit", 1000))
                limit = min(limit, _DB_PROXY_MAX_LIMIT)
            except (TypeError, ValueError):
                limit = 1000
            try:
                offset = int(request.args.get("offset", 0))
            except (TypeError, ValueError):
                offset = 0

            if offset > 0:
                q = q.range(offset, offset + limit - 1)
            else:
                q = q.limit(limit)

            r = q.execute()
            return jsonify({"success": True, "data": r.data or []})

        # ── POST: INSERT ──
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            _db_proxy_log(table, "INSERT")
            r = sb.table(table).insert(body).execute()
            return jsonify({"success": True, "data": r.data or []})

        # ── PATCH: UPDATE с фильтром в query string ──
        if request.method == "PATCH":
            body = request.get_json(silent=True) or {}
            # Должен быть хотя бы один фильтр
            filters = [(k, v) for k, v in request.args.items() if k not in ("select",)]
            if not filters:
                return jsonify({"success": False, "error": "filter_required"}), 400
            q = sb.table(table).update(body)
            for key, val in filters:
                if "." in val:
                    op, _, v = val.partition(".")
                    if op == "eq":
                        q = q.eq(key, v)
                    elif op == "in":
                        v_clean = v.strip("()")
                        q = q.in_(key, v_clean.split(","))
                    else:
                        q = q.eq(key, v)
                else:
                    q = q.eq(key, val)
            _db_proxy_log(table, f"UPDATE filters={filters}")
            r = q.execute()
            return jsonify({"success": True, "data": r.data or []})

        # ── DELETE ──
        if request.method == "DELETE":
            filters = [(k, v) for k, v in request.args.items() if k not in ("select",)]
            if not filters:
                return jsonify({"success": False, "error": "filter_required"}), 400
            q = sb.table(table).delete()
            for key, val in filters:
                if "." in val:
                    op, _, v = val.partition(".")
                    if op == "eq":
                        q = q.eq(key, v)
                    elif op == "in":
                        v_clean = v.strip("()")
                        q = q.in_(key, v_clean.split(","))
                    else:
                        q = q.eq(key, v)
                else:
                    q = q.eq(key, val)
            _db_proxy_log(table, f"DELETE filters={filters}")
            r = q.execute()
            return jsonify({"success": True, "data": r.data or []})

    except Exception as e:
        app.logger.error(f"db_proxy error on table={table}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({"success": False, "error": "method_not_allowed"}), 405


# === END GENERIC DB PROXY ===



if __name__ == '__main__':
    threading.Thread(target=healthcheck_loop, daemon=True).start()
    app.run(host='127.0.0.1', port=5000)
