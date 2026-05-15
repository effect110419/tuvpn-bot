"""
Добавление сервера DE (Германия) в таблицу servers в Supabase.

Запускать на App-сервере: python3 /tmp/add_de_server.py

Перед запуском убедись что:
- inbound на DE создан (TuVPN-DE, id=2 в локальной x-ui.db)
- ключи Reality такие же как на FI (privateKey/publicKey)
- target = chat.deepseek.com
"""
import sys
sys.path.insert(0, '/root/tuvpn')

import requests
from config import SUPABASE_URL, SUPABASE_KEY

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

# Сначала проверим, нет ли уже сервера DE (по IP или code)
print("[1/3] Проверяю, нет ли уже сервера DE в БД...")
r = requests.get(
    f"{SUPABASE_URL}/rest/v1/servers?or=(code.eq.DE,server_ip.eq.78.17.56.109)",
    headers=SUPABASE_HEADERS,
    timeout=15,
)
r.raise_for_status()
existing = r.json()
if existing:
    print(f"  ! Уже есть сервер: {existing}")
    print("  Останавливаюсь, чтобы не плодить дубли. Если надо переустановить — сначала DELETE.")
    sys.exit(1)
print("  OK, DE ещё не зарегистрирован.")

# Берём максимальный sort_order, чтобы DE встал последним
print("[2/3] Беру следующий sort_order...")
r = requests.get(
    f"{SUPABASE_URL}/rest/v1/servers?select=sort_order&order=sort_order.desc&limit=1",
    headers=SUPABASE_HEADERS,
    timeout=15,
)
r.raise_for_status()
rows = r.json()
next_sort_order = (rows[0]["sort_order"] + 1) if rows else 1
print(f"  next sort_order = {next_sort_order}")

# Готовим payload
payload = {
    "code": "DE",
    "country_name": "Германия",
    "country_flag": "🇩🇪",
    "country_code": "DE",
    "panel_url": "https://78.17.56.109:17627/I4z8tB7MLF8wPjpKDW/",
    "panel_login": "clmHydSJD6",
    "panel_password": "otfCjziZyn",
    "inbound_id": 2,
    "server_ip": "78.17.56.109",
    "server_port": 443,
    "public_key": "9q2JxVMnpr1nvhK407R0ymy5k-W_tyE_iEvSLJTXWg8",
    "short_id": "fe7a4c33947cd7",
    "sni": "chat.deepseek.com",
    "flow": "xtls-rprx-vision",
    "fingerprint": "chrome",
    "is_active": True,
    "sort_order": next_sort_order,
    "notes": "DE node, Reality target chat.deepseek.com, 3X-UI v3.0.2 (CSRF)",
}

print("[3/3] Добавляю DE в servers...")
r = requests.post(
    f"{SUPABASE_URL}/rest/v1/servers",
    headers=SUPABASE_HEADERS,
    json=payload,
    timeout=15,
)
if r.status_code >= 400:
    print(f"  FAIL {r.status_code}: {r.text}")
    sys.exit(1)
print(f"  OK {r.status_code}")
result = r.json()
print(f"  Создана запись: id={result[0]['id']}, code={result[0]['code']}")
print()
print("=== ВСЕ СЕРВЕРА СЕЙЧАС ===")
r = requests.get(
    f"{SUPABASE_URL}/rest/v1/servers?select=id,code,country_name,server_ip,inbound_id,sni,is_active,sort_order&order=sort_order.asc",
    headers=SUPABASE_HEADERS,
    timeout=15,
)
for s in r.json():
    flag = "✓" if s["is_active"] else "✗"
    print(f"  [{s['sort_order']}] id={s['id']} {flag} {s['code']:3s} {s['country_name']:15s} {s['server_ip']:18s} inb={s['inbound_id']} sni={s['sni']}")

print("\n[DONE]")
