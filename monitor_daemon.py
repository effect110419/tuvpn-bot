#!/usr/bin/env python3
"""
TuVPN Monitor Daemon — проверяет здоровье всех VPN-узлов и пишет в server_health.
Интервал читается из monitor_settings (можно менять через админку, вплоть до 5 сек).
Запускается как systemd-сервис (постоянный процесс).
"""
import sys, time, json, socket, ssl, os, re
sys.path.insert(0, '/root/tuvpn')
import requests
from datetime import datetime
from config import SUPABASE_URL, SUPABASE_KEY

requests.packages.urllib3.disable_warnings()
H = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
     "Content-Type": "application/json"}

DEFAULT_INTERVAL = 300
MIN_INTERVAL = 5

# Пароли панелей могут храниться зашифрованными (Fernet, см. proxy.py П.6) —
# тот же формат тут, чтобы демон не сломался молча после миграции на шифрование.
try:
    from cryptography.fernet import Fernet as _Fernet
    _PANEL_ENC_KEY = os.environ.get('PANEL_ENCRYPTION_KEY', '').strip()
    _fernet = _Fernet(_PANEL_ENC_KEY.encode()) if _PANEL_ENC_KEY else None
except Exception:
    _fernet = None


def decrypt_panel_password(raw: str) -> str:
    if _fernet and raw and raw.startswith('gAAAAA'):
        try:
            return _fernet.decrypt(raw.encode()).decode()
        except Exception:
            pass
    return raw


def get_interval():
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/monitor_settings?id=eq.1&select=interval_sec,enabled",
                         headers=H, timeout=10)
        d = r.json()
        if d and d[0].get("enabled"):
            return max(MIN_INTERVAL, int(d[0].get("interval_sec") or DEFAULT_INTERVAL))
        elif d and not d[0].get("enabled"):
            return None  # мониторинг выключен
    except Exception:
        pass
    return DEFAULT_INTERVAL


def get_servers():
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/servers?is_active=eq.true&select=*&order=sort_order",
                         headers=H, timeout=10)
        return r.json() or []
    except Exception as e:
        print(f"get_servers error: {e}", flush=True)
        return []


def check_tcp(ip, port, timeout=5):
    """TCP-проба порта. Возвращает (доступен, latency_ms)."""
    t0 = time.time()
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True, int((time.time() - t0) * 1000)
    except Exception:
        return False, None


def check_target(sni, timeout=6):
    """TLS-handshake до SNI-донора (Reality target). (ok, latency_ms)."""
    if not sni:
        return None, None
    t0 = time.time()
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((sni, 443), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=sni) as ssock:
                _ = ssock.version()
        return True, int((time.time() - t0) * 1000)
    except Exception:
        return False, None


def xui_check(server):
    """Логин в 3X-UI (v3 Bearer-токен если задан api_token, иначе v2 cookie-логин)
    + получить кол-во клиентов. (up, latency_ms, clients, error)."""
    url = (server.get("panel_url") or "").rstrip("/")
    inbound_id = server.get("inbound_id")
    api_token = (server.get("api_token") or "").strip()
    if not url:
        return False, None, None, "no panel_url"
    t0 = time.time()

    if api_token:
        # v3 — Bearer-токен, отдельного логина не требует
        try:
            s = requests.Session(); s.verify = False
            s.headers.update({"Authorization": f"Bearer {api_token}",
                               "Content-Type": "application/json", "Accept": "application/json"})
            r = s.get(f"{url}/panel/api/inbounds/get/{int(inbound_id)}", timeout=10)
            latency = int((time.time() - t0) * 1000)
            if r.status_code != 200:
                return False, latency, None, f"v3 HTTP {r.status_code}"
            obj = r.json().get("obj", {})
            st = obj.get("settings")
            if isinstance(st, str):
                st = json.loads(st)
            clients = len((st or {}).get("clients", []))
            return True, latency, clients, None
        except Exception as e:
            return False, int((time.time() - t0) * 1000), None, str(e)[:200]

    # v2 — cookie-логин. Новые панели требуют CSRF-токен из главной страницы,
    # без него /login отвечает 403 (та же логика, что в proxy.py xui_session).
    login = server.get("panel_login")
    pw = decrypt_panel_password(server.get("panel_password") or "")
    try:
        s = requests.Session(); s.verify = False
        base_headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Origin": url.split("/", 3)[0] + "//" + url.split("/", 3)[2],
            "Referer": f"{url}/",
        }
        csrf = None
        try:
            get_resp = s.get(f"{url}/", timeout=10, headers=base_headers)
            if get_resp.status_code == 200:
                m = re.search(r'name="csrf-token"\s+content="([^"]+)"', get_resp.text)
                if m:
                    csrf = m.group(1)
        except Exception:
            pass
        if csrf:
            base_headers["X-CSRF-Token"] = csrf
        s.headers.update(base_headers)
        if csrf:
            r = s.post(f"{url}/login", data={"username": login, "password": pw}, timeout=10)
        else:
            r = s.post(f"{url}/login", json={"username": login, "password": pw}, timeout=10)
        latency = int((time.time() - t0) * 1000)
        if r.status_code != 200:
            return False, latency, None, f"login HTTP {r.status_code}"
        clients = None
        try:
            gr = s.get(f"{url}/panel/api/inbounds/get/{int(inbound_id)}", timeout=10)
            obj = gr.json().get("obj", {})
            st = obj.get("settings")
            if isinstance(st, str):
                st = json.loads(st)
            clients = len((st or {}).get("clients", []))
        except Exception:
            pass
        return True, latency, clients, None
    except Exception as e:
        return False, int((time.time() - t0) * 1000), None, str(e)[:200]


def check_one(server):
    code = server.get("code")
    name = server.get("country_name")
    ip = server.get("server_ip")
    port = int(server.get("server_port") or 443)
    sni = server.get("sni")

    up, latency, clients, err = xui_check(server)
    xray_ok, _ = check_tcp(ip, port)   # слушает ли 443
    target_ok, target_lat = check_target(sni)

    row = {
        "server_code": code,
        "server_name": name,
        "is_up": bool(up),
        "latency_ms": latency,
        "xray_listening": bool(xray_ok),
        "clients_count": clients,
        "target_ok": target_ok,
        "target_latency_ms": target_lat,
        "sni": sni,
        "error": err,
    }
    try:
        requests.post(f"{SUPABASE_URL}/rest/v1/server_health", headers=H, json=row, timeout=10)
    except Exception as e:
        print(f"write health error {code}: {e}", flush=True)
    status = "UP" if up else "DOWN"
    print(f"[{datetime.utcnow().isoformat()}] {code}: {status} lat={latency}ms "
          f"xray={'Y' if xray_ok else 'N'} clients={clients} target={'Y' if target_ok else 'N'}", flush=True)


def cleanup_old():
    """Чистка записей старше 7 дней (раз в цикл, не критично)."""
    try:
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
        requests.delete(f"{SUPABASE_URL}/rest/v1/server_health?checked_at=lt.{cutoff}",
                        headers=H, timeout=15)
    except Exception:
        pass


def main():
    print("TuVPN Monitor Daemon запущен", flush=True)
    cleanup_counter = 0
    while True:
        interval = get_interval()
        if interval is None:
            # мониторинг выключен — спим минуту и проверяем настройку снова
            time.sleep(60)
            continue
        servers = get_servers()
        for srv in servers:
            check_one(srv)
        # чистка раз в ~100 циклов
        cleanup_counter += 1
        if cleanup_counter >= 100:
            cleanup_old()
            cleanup_counter = 0
        time.sleep(interval)


if __name__ == "__main__":
    main()
