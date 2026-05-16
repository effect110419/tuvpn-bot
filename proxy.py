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
                # PRICES может быть dict[(devices, months)] = price ИЛИ dict[devices][months] = price
                if isinstance(PRICES, dict):
                    if (d, m) in PRICES:
                        expected_price = PRICES[(d, m)]
                    elif d in PRICES and isinstance(PRICES[d], dict) and m in PRICES[d]:
                        expected_price = PRICES[d][m]
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




# === ADMIN AUTH BLOCK ===
import secrets as _secrets

try:
    from config import ADMIN_TG_IDS, ADMIN_SESSION_DAYS, ADMIN_LOGIN_TOKEN_MINUTES
except ImportError:
    ADMIN_TG_IDS = [784871620, 1027228622]
    ADMIN_SESSION_DAYS = 7
    ADMIN_LOGIN_TOKEN_MINUTES = 10


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



if __name__ == '__main__':
    import threading
    threading.Thread(target=healthcheck_loop, daemon=True).start()
    app.run(host='127.0.0.1', port=5000)
