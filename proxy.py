import sys
sys.path.insert(0, '/root')
sys.path.insert(0, '/root/tuvpn')
from server_installer import create_installation, start_installation_thread, REALITY_TARGET_CANDIDATES
from flask import Flask, request, jsonify, Response
import requests, json, uuid, base64
import asyncio
from datetime import datetime, timedelta
from config import PANEL_URL, PANEL_USER, PANEL_PASS, INBOUND_ID, SERVER_IP, SUB_BASE_URL
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
import urllib3
urllib3.disable_warnings()

app = Flask(__name__)
# ─── CORS для админки ───
from flask import make_response

@app.after_request
def add_cors_headers(response):
    if request.path.startswith('/admin-api/'):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Max-Age'] = '3600'
    return response

@app.route('/admin-api/<path:path>', methods=['OPTIONS'])
def handle_admin_options(path):
    return make_response('', 204)
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
    creds = {"username": server["panel_login"], "password": server["panel_password"]}

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


def xui_add_client_on_server(server, client_uuid, uid, devices, expire_ms):
    """Создаёт клиента на одном сервере. True если успешно."""
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
        # Клиента нет на этом сервере — добавляем
        print(f"[{server.get('country_name')}] updateClient failed ({result.get('msg', '')}) — trying addClient")
        return xui_add_client_on_server(server, client_uuid, uid, devices, expire_ms)
    except Exception as e:
        print(f"[{server.get('country_name', '?')}] update_client error: {e}")
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
                settings = json.loads(inbound["settings"])
                for client in settings.get("clients", []):
                    if client.get("id") == client_uuid:
                        return client.get("expiryTime", 0) // 1000
        except Exception as e:
            print(f"get_client_expire on {server.get('country_name')}: {e}")
            continue
    return 0


def get_existing_client(uid):
    """Получаем активную подписку пользователя из Supabase"""
    try:
        r = sb.table("subscriptions").select("*").eq("user_id", uid).eq("status", "active").execute()
        if r.data:
            sub = r.data[0]
            if "/sub/" in sub.get("sub_url", ""):
                existing_uuid = sub["sub_url"].split("/sub/")[-1]
                return sub["id"], existing_uuid, sub["devices"]
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


def make_device_name(ua: str, dtype: str) -> str:
    """Формирует читаемое имя устройства."""
    icons = {"ios": "🍏 iPhone/iPad", "android": "🤖 Android", "pc": "💻 ПК", "unknown": "📱 Устройство"}
    name = icons.get(dtype, "📱 Устройство")
    # Достаём версию из UA если есть
    import re as _re
    m = _re.search(r"(iOS|Android|Windows|Mac OS X)[ /]?(\d+[\d._]*)", ua or "", _re.IGNORECASE)
    if m:
        name += f" · {m.group(1)} {m.group(2).replace('_', '.')}"
    return name


def track_device(client_uuid: str, client_ip: str, user_agent: str) -> dict:
    """
    Регистрирует/обновляет устройство при обращении к подписке.
    Возвращает {"allowed": bool, "reason": str, "device_id": int|None}.

    Логика:
    - Находим подписку по client_uuid
    - Если устройство с таким (uuid, ip) уже есть и активно — обновляем last_seen
    - Если новое устройство:
        * считаем активные устройства этого юзера
        * если меньше лимита (subscription.devices) — добавляем
        * если уже равно лимиту — отказываем
    """
    try:
        # Находим подписку
        sub_q = sb.table("subscriptions").select("*").eq("status", "active").like("sub_url", f"%{client_uuid}").limit(1).execute()
        if not sub_q.data:
            return {"allowed": False, "reason": "subscription_not_found", "device_id": None}
        sub = sub_q.data[0]
        user_id = sub["user_id"]
        device_limit = sub.get("devices", 1)

        # Ищем существующее устройство с тем же IP и uuid
        existing = sb.table("user_devices").select("*").eq("user_id", user_id).eq("client_uuid", client_uuid).eq("ip_address", client_ip).limit(1).execute()
        if existing.data:
            dev = existing.data[0]
            # Просто обновляем last_seen и реактивируем если было выключено
            sb.table("user_devices").update({
                "last_seen": datetime.utcnow().isoformat(),
                "is_active": True,
                "user_agent": user_agent,
            }).eq("id", dev["id"]).execute()
            return {"allowed": True, "reason": "updated", "device_id": dev["id"]}

        # Новое устройство — проверим лимит
        active_count_q = sb.table("user_devices").select("id", count="exact").eq("user_id", user_id).eq("is_active", True).execute()
        active_count = active_count_q.count or 0
        if active_count >= device_limit:
            app.logger.warning(f"Device limit exceeded: user={user_id} limit={device_limit} active={active_count} IP={client_ip}")
            return {"allowed": False, "reason": "limit_exceeded", "device_id": None}

        # Добавляем новое устройство
        dtype = detect_device_type(user_agent)
        dname = make_device_name(user_agent, dtype)
        new_dev = sb.table("user_devices").insert({
            "user_id": user_id,
            "device_name": dname,
            "device_type": dtype,
            "device_info": (user_agent or "")[:200],
            "client_uuid": client_uuid,
            "ip_address": client_ip,
            "user_agent": (user_agent or "")[:500],
            "connected_at": datetime.utcnow().isoformat(),
            "last_seen": datetime.utcnow().isoformat(),
            "is_active": True,
        }).execute()
        dev_id = new_dev.data[0]["id"] if new_dev.data else None
        app.logger.info(f"New device tracked: user={user_id} IP={client_ip} type={dtype} id={dev_id}")
        return {"allowed": True, "reason": "added", "device_id": dev_id}
    except Exception as e:
        app.logger.error(f"track_device error: {e}")
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

    # Регистрация устройства / проверка лимита
    track_result = track_device(client_uuid, client_ip, user_agent)
    if not track_result["allowed"]:
        if track_result["reason"] == "limit_exceeded":
            app.logger.info(f"Subscription blocked (limit): {client_uuid} from {client_ip}")
            return Response("Device limit exceeded for this subscription", status=403)
        # Если subscription_not_found — отдаём 404
        if track_result["reason"] == "subscription_not_found":
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

    configs = subscription_generator.build_subscription(servers, client_uuid)
    body = _json.dumps(configs, ensure_ascii=False, separators=(",", ":"))
    expire_ts = get_client_expire(client_uuid)
    announcement_b64 = "4pqg77iPINCd0LUg0YDQsNCx0L7RgtCw0LXRgj8g0J3QsNC20LzQuCDwn5SEINC4INCy0YvQsdC10YDQuCDQtNGA0YPQs9GD0Y4g0LvQvtC60LDRhtC40Y4uIPCfk4Ug0J/RgNC+0LTQu9C10LLQsNC5INC30LDRgNCw0L3QtdC1IOKAlCBUZWxlZ3JhbSDQt9Cw0LzQtdC00LvRj9GO0YIh"
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "profile-title": "TuVPN",
        "profile-update-interval": "6",
        "support-url": "https://t.me/MaxArtVPN_bot",
        "subscription-userinfo": f"upload=0; download=0; total=0; expire={expire_ts}",
        "announce": "base64:" + announcement_b64,
    }
    return Response(body, headers=headers)


def issue_subscription(uid: int, devices: int, days: int) -> dict:
    """Выдать/продлить подписку на всех активных серверах.
    - Если есть активная подписка — продлевает с тем же UUID
    - Если нет — создаёт новую с новым UUID
    - Применяет накопленные bonus_days
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

        # Проверяем существующую подписку
        sub_id, existing_uuid, _ = get_existing_client(uid)
        now = datetime.utcnow()

        if existing_uuid and sub_id:
            # ПРОДЛЕНИЕ существующей
            try:
                cur_row = sb.table("subscriptions").select("expires_at").eq("id", sub_id).limit(1).execute()
                cur_exp_raw = cur_row.data[0]["expires_at"] if cur_row.data else None
                cur_exp = datetime.fromisoformat(cur_exp_raw.replace("Z", "+00:00")).replace(tzinfo=None) if cur_exp_raw else now
                base = cur_exp if cur_exp > now else now
            except Exception:
                base = now
            new_expires = base + timedelta(days=total_days)
            client_uuid = existing_uuid
            action = "extended"
        else:
            # СОЗДАНИЕ новой
            client_uuid = str(uuid.uuid4())
            new_expires = now + timedelta(days=total_days)
            action = "created"

        expire_ms = int(new_expires.timestamp() * 1000)

        # Применяем на всех активных серверах
        servers = get_active_servers()
        if not servers:
            return {"success": False, "error": "no active servers in DB"}

        success_count = 0
        for server in servers:
            if action == "extended":
                ok = xui_update_client_on_server(server, client_uuid, uid, devices, expire_ms)
            else:
                ok = xui_add_client_on_server(server, client_uuid, uid, devices, expire_ms)
            if ok:
                success_count += 1

        if success_count == 0:
            return {"success": False, "error": "failed on all servers"}

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
            sb.table("subscriptions").update(sub_data).eq("id", sub_id).execute()
        else:
            sub_data["started_at"] = now.isoformat()
            sb.table("subscriptions").insert(sub_data).execute()
            sb.table("users").update({"client_uuid": client_uuid}).eq("user_id", uid).execute()

        # Списываем bonus_days если применили
        if bonus_days > 0:
            try:
                sb.table("users").update({"bonus_days": 0}).eq("user_id", uid).execute()
                print(f"Применены {bonus_days} бонусных дней для user_id={uid}")
            except Exception:
                pass

        print(f"✅ {action} user_id={uid} on {success_count}/{len(servers)} servers, expires {new_expires}")
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

def notify_user(user_id: int, text: str) -> bool:
    """Отправляет сообщение пользователю в Telegram через HTTP API."""
    try:
        import requests
        from config import BOT_TOKEN
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": user_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
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
                "panel_password": data['panel_password'],
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
            
            sb.table('servers').insert(new_server).execute()
            return jsonify({"success": True, "message": "Сервер добавлен"})
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
            
            sb.table('servers').update(update_data).eq('id', server_id).execute()
            return jsonify({"success": True, "message": "Сервер обновлён"})
        
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
            settings = json.loads(inbound.get("settings", "{}"))
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
        data = request.json
        uid = int(data['user_id'])
        devices = data['devices']
        days = data['days']
        result = issue_subscription(uid, devices, days)
        if result.get("success"):
            resp = jsonify(result)
        else:
            resp = jsonify({"success": False, "error": result.get("error", "unknown")})

        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    except Exception as e:
        resp = jsonify({"success": False, "error": str(e)})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp



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

                    sb.table("promocode_uses").insert({
                        "promocode_id": promo_id_int,
                        "user_id": uid,
                        "payment_id": internal_pay_id,
                        "applied_value": applied_value,
                    }).execute()

                    # Инкрементим счётчик uses_count
                    cur = sb.table("promocodes").select("uses_count").eq("id", promo_id_int).limit(1).execute()
                    if cur.data:
                        new_count = (cur.data[0].get("uses_count") or 0) + 1
                        sb.table("promocodes").update({"uses_count": new_count}).eq("id", promo_id_int).execute()
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
                    admins_res = sb.table("support_admins").select("user_id").eq("is_active", True).execute()
                    for a in (admins_res.data or []):
                        notify_user(a["user_id"], admin_text)
                except Exception as e:
                    app.logger.error(f"Не удалось уведомить админов: {e}")
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


if __name__ == '__main__':
    import threading
    threading.Thread(target=healthcheck_loop, daemon=True).start()
    app.run(host='127.0.0.1', port=5000)
