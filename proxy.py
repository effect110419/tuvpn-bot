import sys
sys.path.insert(0, '/root')
from flask import Flask, request, jsonify, Response
import requests, json, uuid, base64
from datetime import datetime, timedelta
from config import PANEL_URL, PANEL_USER, PANEL_PASS, INBOUND_ID, SERVER_IP, SUB_BASE_URL
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
import urllib3
urllib3.disable_warnings()

app = Flask(__name__)
PUBLIC_KEY = "9q2JxVMnpr1nvhK407R0ymy5k-W_tyE_iEvSLJTXWg8"
SHORT_ID = "d1a247d5a8"
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

def xui_session():
    s = requests.Session()
    s.verify = False
    s.post(f"{PANEL_URL}/login", json={"username": PANEL_USER, "password": PANEL_PASS})
    return s

def get_client_expire(client_uuid):
    try:
        s = xui_session()
        r = s.get(f"{PANEL_URL}/xui/API/inbounds/list")
        data = r.json()
        settings = json.loads(data["obj"][0]["settings"])
        for client in settings.get("clients", []):
            if client.get("id") == client_uuid:
                return client.get("expiryTime", 0) // 1000
    except:
        pass
    return 0

def get_existing_client(uid):
    """Получаем активную подписку пользователя из Supabase"""
    try:
        r = sb.table("subscriptions").select("*").eq("user_id", uid).eq("status", "active").execute()
        if r.data:
            sub = r.data[0]
            # Извлекаем UUID из sub_url
            if "/sub/" in sub["sub_url"]:
                existing_uuid = sub["sub_url"].split("/sub/")[-1]
                return sub["id"], existing_uuid, sub["devices"]
    except:
        pass
    return None, None, None

@app.route('/sub/<client_uuid>')
def subscription(client_uuid):
    vless = (
        f"vless://{client_uuid}@{SERVER_IP}:443"
        f"?type=tcp&security=reality"
        f"&pbk={PUBLIC_KEY}"
        f"&fp=chrome&sni=www.bing.com"
        f"&sid={SHORT_ID}&spx=%2F"
        f"&flow=xtls-rprx-vision"
        f"#\U0001f1eb\U0001f1ee Finland"
    )
    encoded = base64.b64encode(vless.encode()).decode()
    expire_ts = get_client_expire(client_uuid)
    announcement_b64 = "4pqg77iPINCd0LUg0YDQsNCx0L7RgtCw0LXRgj8g0J3QsNC20LzQuCDwn5SEINC4INCy0YvQsdC10YDQuCDQtNGA0YPQs9GD0Y4g0LvQvtC60LDRhtC40Y4uIPCfk4Ug0J/RgNC+0LTQu9C10LLQsNC5INC30LDRgNCw0L3QtdC1IOKAlCBUZWxlZ3JhbSDQt9Cw0LzQtdC00LvRj9GO0YIh"
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "profile-title": "TuVPN",
        "profile-update-interval": "6",
        "support-url": "https://t.me/MaxArtVPN_bot",
        "subscription-userinfo": f"upload=0; download=0; total=0; expire={expire_ts}",
        "announce": "base64:" + announcement_b64,
    }
    return Response(encoded, headers=headers)

def issue_subscription(uid: int, devices: int, days: int) -> dict:
    """Создаёт или обновляет подписку в 3X-UI и Supabase."""
    from datetime import datetime, timedelta
    import json, uuid
    expire_ms = int((datetime.now() + timedelta(days=days)).timestamp() * 1000)
    ts = int(datetime.now().timestamp())
    s = xui_session()
    sub_id, existing_uuid, existing_devices = get_existing_client(uid)

    if existing_uuid:
        payload = {
            "id": INBOUND_ID,
            "settings": json.dumps({"clients": [{
                "id": existing_uuid,
                "email": f"user_{uid}_{ts}",
                "limitIp": devices,
                "totalGB": 0,
                "expiryTime": expire_ms,
                "enable": True,
                "flow": "xtls-rprx-vision"
            }]})
        }
        r = s.post(f"{PANEL_URL}/panel/api/inbounds/updateClient/{existing_uuid}", json=payload)
        result = r.json()
        if result.get("success"):
            sub_url = f"{SUB_BASE_URL}/sub/{existing_uuid}"
            sb.table("subscriptions").update({
                "devices": devices,
                "expires_at": (datetime.now() + timedelta(days=days)).isoformat(),
                "sub_url": sub_url,
                "status": "active"
            }).eq("id", sub_id).execute()
            return {"success": True, "uuid": existing_uuid, "sub_url": sub_url, "action": "updated"}
        return {"success": False, "error": str(result)}
    else:
        client_uuid = str(uuid.uuid4())
        payload = {
            "id": INBOUND_ID,
            "settings": json.dumps({"clients": [{
                "id": client_uuid,
                "email": f"user_{uid}_{ts}",
                "limitIp": devices,
                "totalGB": 0,
                "expiryTime": expire_ms,
                "enable": True,
                "flow": "xtls-rprx-vision"
            }]})
        }
        r = s.post(f"{PANEL_URL}/panel/api/inbounds/addClient", json=payload)
        result = r.json()
        if result.get("success"):
            sub_url = f"{SUB_BASE_URL}/sub/{client_uuid}"
            sb.table("subscriptions").update({"status": "inactive"}).eq("user_id", uid).eq("status", "active").execute()
            sb.table("subscriptions").insert({
                "user_id": uid, "devices": devices, "status": "active",
                "sub_url": sub_url, "started_at": datetime.now().isoformat(),
                "expires_at": (datetime.now() + timedelta(days=days)).isoformat()
            }).execute()
            sb.table("users").update({"client_uuid": client_uuid}).eq("user_id", uid).execute()
            return {"success": True, "uuid": client_uuid, "sub_url": sub_url, "action": "created"}
        return {"success": False, "error": str(result)}


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
            devices = int(metadata.get("devices"))
            months = int(metadata.get("months"))
            email = metadata.get("email", "—")
            days = months * 30
            months_label = {1: "1 месяц", 3: "3 месяца", 12: "1 год"}.get(months, f"{months} мес.")

            result = issue_subscription(uid, devices, days)
            app.logger.info(f"Выдача подписки по платежу {payment_id}: {result}")

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

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000)
