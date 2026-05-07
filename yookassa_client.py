"""
Модуль для работы с ЮКассой.
- Создание платежей
- Проверка подписи webhook'ов
- Обработка успешных оплат
"""
import logging
import uuid as uuid_lib
import ipaddress
from decimal import Decimal
from typing import Optional

from yookassa import Configuration, Payment
from yookassa.domain.notification import WebhookNotification

from config import (
    YOOKASSA_SHOP_ID,
    YOOKASSA_SECRET_KEY,
    YOOKASSA_RETURN_URL,
)

log = logging.getLogger("yookassa_client")

# Инициализация SDK
Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY


# Список IP-адресов с которых ЮКасса присылает webhook'и.
# Источник: https://yookassa.ru/developers/using-api/webhooks
YOOKASSA_WEBHOOK_IPS = [
    "185.71.76.0/27",
    "185.71.77.0/27",
    "77.75.153.0/25",
    "77.75.156.11",
    "77.75.156.35",
    "77.75.154.128/25",
    "2a02:5180::/32",
]


def is_yookassa_ip(ip_str: str) -> bool:
    """Проверяет что IP принадлежит ЮКассе."""
    try:
        ip = ipaddress.ip_address(ip_str)
        for cidr in YOOKASSA_WEBHOOK_IPS:
            if "/" in cidr:
                if ip in ipaddress.ip_network(cidr):
                    return True
            else:
                if ip == ipaddress.ip_address(cidr):
                    return True
    except (ValueError, TypeError):
        pass
    return False


def create_payment(
    amount: float,
    description: str,
    user_id: int,
    devices: int,
    months: int,
    email: str,
    promo_id=None,
    promo_code=None,
    promo_type=None,
    promo_value=None,
    bonus_days_from_promo: int = 0,
) -> dict:
    """
    Создаёт платёж в ЮКассе.

    Параметры промо (опционально) сохраняются в metadata платежа,
    чтобы webhook мог применить бонусные дни и зафиксировать использование.
    """
    idempotence_key = str(uuid_lib.uuid4())

    metadata = {
        "user_id": str(user_id),
        "devices": str(devices),
        "months": str(months),
        "email": email,
    }
    if promo_id:
        metadata["promo_id"] = str(promo_id)
        metadata["promo_code"] = str(promo_code or "")
        metadata["promo_type"] = str(promo_type or "")
        metadata["promo_value"] = str(promo_value or "")
        metadata["bonus_days_from_promo"] = str(bonus_days_from_promo or 0)

    payment = Payment.create(
        {
            "amount": {
                "value": f"{Decimal(str(amount)):.2f}",
                "currency": "RUB",
            },
            "confirmation": {
                "type": "redirect",
                "return_url": YOOKASSA_RETURN_URL,
            },
            "capture": True,
            "description": description,
            "metadata": metadata,
            # Чек НЕ передаём — самозанятый формирует вручную в "Мой налог"
        },
        idempotence_key,
    )

    log.info(f"Создан платёж {payment.id} для user_id={user_id} на сумму {amount} RUB")

    return {
        "payment_id": payment.id,
        "confirmation_url": payment.confirmation.confirmation_url,
        "status": payment.status,
    }


def get_payment_info(payment_id: str) -> Optional[dict]:
    """Получает актуальный статус платежа из ЮКассы."""
    try:
        payment = Payment.find_one(payment_id)
        return {
            "payment_id": payment.id,
            "status": payment.status,
            "paid": payment.paid,
            "amount": float(payment.amount.value),
            "currency": payment.amount.currency,
            "payment_method": payment.payment_method.type if payment.payment_method else None,
            "metadata": payment.metadata or {},
        }
    except Exception as e:
        log.error(f"Не удалось получить платёж {payment_id}: {e}")
        return None


def parse_webhook(body: dict) -> Optional[dict]:
    """
    Разбирает тело webhook'а от ЮКассы.

    Возвращает dict с ключами:
        - event: "payment.succeeded" | "payment.canceled" | etc.
        - payment_id, status, paid, amount, metadata
    """
    try:
        notification = WebhookNotification(body)
        payment = notification.object

        return {
            "event": notification.event,
            "payment_id": payment.id,
            "status": payment.status,
            "paid": payment.paid,
            "amount": float(payment.amount.value),
            "currency": payment.amount.currency,
            "payment_method": payment.payment_method.type if payment.payment_method else None,
            "metadata": payment.metadata or {},
        }
    except Exception as e:
        log.error(f"Не удалось разобрать webhook: {e}")
        return None
