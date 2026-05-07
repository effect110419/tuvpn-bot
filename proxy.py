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
    """
    Создаёт или обновляет подписку в 3X-UI и Supabase.
    Если у пользователя уже есть активная неистёкшая подписка — продлевает её
    от текущего expires_at, а не перезаписывает срок.
    """
    from datetime import datetime, timedelta
    import json, uuid
    ts = int(datetime.now().timestamp())
    s = xui_session()
    sub_id, existing_uuid, existing_devices = get_existing_client(uid)

    if existing_uuid:
        # Получаем текущий expires_at из БД для этой подписки
        sub_row = sb.table("subscriptions").select("expires_at").eq("id", sub_id).limit(1).execute()
        now = datetime.now()
        base_expires = now
        if sub_row.data and sub_row.data[0].get("expires_at"):
            try:
                current_exp = datetime.fromisoformat(sub_row.data[0]["expires_at"].replace("Z", "+00:00"))
                # Если работаем с aware datetime — приводим к naive для сравнения
                if current_exp.tzinfo is not None:
                    current_exp = current_exp.replace(tzinfo=None)
                # Продлеваем от current_exp если он в будущем, иначе от сейчас
                if current_exp > now:
                    base_expires = current_exp
            except Exception as e:
                app.logger.warning(f"Не удалось распарсить expires_at: {e}")

        # Учитываем накопленные бонусные дни пользователя
        bonus_days = 0
        try:
            user_row = sb.table("users").select("bonus_days").eq("user_id", uid).limit(1).execute()
            bonus_days = (user_row.data[0].get("bonus_days") or 0) if user_row.data else 0
        except Exception:
            pass
        total_days = days + bonus_days
        new_expires = base_expires + timedelta(days=total_days)
        expire_ms = int(new_expires.timestamp() * 1000)
        if bonus_days > 0:
            try:
                sb.table("users").update({"bonus_days": 0}).eq("user_id", uid).execute()
                app.logger.info(f"Применены {bonus_days} бонусных дней для user_id={uid}")
            except Exception as e:
                app.logger.error(f"Не удалось обнулить bonus_days: {e}")

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
                "expires_at": new_expires.isoformat(),
                "sub_url": sub_url,
                "status": "active"
            }).eq("id", sub_id).execute()
            app.logger.info(f"Подписка продлена user_id={uid}: было до {base_expires}, стало до {new_expires}")
            return {"success": True, "uuid": existing_uuid, "sub_url": sub_url, "action": "extended"}
        return {"success": False, "error": str(result)}
    else:
        # Применяем накопленные бонусные дни и для нового клиента
        bonus_days = 0
        try:
            user_row = sb.table("users").select("bonus_days").eq("user_id", uid).limit(1).execute()
            bonus_days = (user_row.data[0].get("bonus_days") or 0) if user_row.data else 0
        except Exception:
            pass
        total_days = days + bonus_days
        new_expires = datetime.now() + timedelta(days=total_days)
        expire_ms = int(new_expires.timestamp() * 1000)
        if bonus_days > 0:
            try:
                sb.table("users").update({"bonus_days": 0}).eq("user_id", uid).execute()
                app.logger.info(f"Применены {bonus_days} бонусных дней для нового клиента user_id={uid}")
            except Exception:
                pass
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
                "expires_at": new_expires.isoformat()
            }).execute()
            sb.table("users").update({"client_uuid": client_uuid}).eq("user_id", uid).execute()
            return {"success": True, "uuid": client_uuid, "sub_url": sub_url, "action": "created"}
        return {"success": False, "error": str(result)}


def apply_referral_bonus(user_id: int, days: int, reason: str):
    """
    Начисляет бонусные дни пользователю.
    - Если есть активная подписка (не истёкшая) — продлевает её на days дней.
    - Если подписки нет или истекла — копит в users.bonus_days,
      эти дни будут добавлены при следующей покупке/выдаче ключа.
    """
    from datetime import datetime, timedelta
    import json
    now = datetime.now()
    # Ищем активную неистёкшую подписку
    subs = sb.table("subscriptions").select("*").eq("user_id", user_id).eq("status", "active").order("expires_at", desc=True).limit(1).execute()
    has_active = False
    if subs.data:
        sub = subs.data[0]
        try:
            exp = datetime.fromisoformat(sub["expires_at"].replace("Z", "+00:00"))
            if exp.tzinfo is not None:
                exp = exp.replace(tzinfo=None)
            if exp > now:
                has_active = True
        except Exception:
            pass

    if has_active:
        # Продлеваем активную подписку
        sub = subs.data[0]
        try:
            exp = datetime.fromisoformat(sub["expires_at"].replace("Z", "+00:00"))
            if exp.tzinfo is not None:
                exp = exp.replace(tzinfo=None)
        except Exception:
            exp = now
        new_exp = exp + timedelta(days=days)
        sb.table("subscriptions").update({"expires_at": new_exp.isoformat()}).eq("id", sub["id"]).execute()

        # Обновляем в 3X-UI
        try:
            client_uuid = sub.get("sub_url", "").rsplit("/", 1)[-1]
            if client_uuid and "-" in client_uuid:
                s = xui_session()
                ts_now = int(now.timestamp())
                payload = {
                    "id": INBOUND_ID,
                    "settings": json.dumps({"clients": [{
                        "id": client_uuid,
                        "email": f"user_{user_id}_{ts_now}",
                        "limitIp": sub.get("devices", 1),
                        "totalGB": 0,
                        "expiryTime": int(new_exp.timestamp() * 1000),
                        "enable": True,
                        "flow": "xtls-rprx-vision"
                    }]})
                }
                s.post(f"{PANEL_URL}/panel/api/inbounds/updateClient/{client_uuid}", json=payload)
        except Exception as e:
            app.logger.error(f"Не удалось обновить срок в 3X-UI для бонуса: {e}")

        notify_user(user_id, f"🎁 <b>Бонус +{days} дней!</b>\n{reason}\n\nВаша подписка продлена.")
    else:
        # Копим в bonus_days
        try:
            user_row = sb.table("users").select("bonus_days").eq("user_id", user_id).limit(1).execute()
            current_bonus = (user_row.data[0].get("bonus_days") or 0) if user_row.data else 0
            new_bonus = current_bonus + days
            sb.table("users").update({"bonus_days": new_bonus}).eq("user_id", user_id).execute()
            notify_user(user_id, f"🎁 <b>Бонус +{days} дней!</b>\n{reason}\n\nДни сохранены и будут добавлены при следующей оплате подписки. Сейчас на счету: <b>{new_bonus}</b> дн.")
        except Exception as e:
            app.logger.error(f"Не удалось сохранить bonus_days: {e}")




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

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000)
