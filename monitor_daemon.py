#!/usr/bin/env python3
"""
TuVPN Monitor Daemon — проверяет здоровье всех VPN-узлов и пишет в server_health.
Интервал читается из monitor_settings (можно менять через админку, вплоть до 5 сек).
Запускается как systemd-сервис (постоянный процесс).

Два независимых сигнала здоровья — это разные системы, и путать их нельзя:
  - service_up  ("VPN доступен")   — TLS-хендшейк до реального порта, на который
    подключаются клиенты. Это то, что реально волнует пользователя.
  - panel_up    ("Панель управления") — логин в 3X-UI. Panel может недоступен/тормозить
    (перегрузка, рестарт) при полностью рабочем VPN — и наоборот, Xray может упасть
    при живой панели. Раньше "is_up" (=panel_up) ошибочно показывался как общий статус
    сервера — отсюда ложные тревоги и пропущенные реальные падения.
service_up хранится в той же колонке is_up для обратной совместимости со старыми
данными и графиками; panel_up — отдельная новая колонка panel_up.
При смене состояния service_up (вверх⇄вниз) — алерт суперадмину в Telegram, с дебаунсом
(шлём только на переходе, не на каждом цикле).
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
SUPERADMIN_ID = 784871620

try:
    _BOT_TOKEN = None
    from config import BOT_TOKEN as _BOT_TOKEN
except Exception:
    pass

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


def notify_admin(text: str):
    """Прямой вызов Telegram Bot API — без импорта proxy.py (демон должен
    оставаться лёгким и независимым от Flask-приложения)."""
    if not _BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage",
            json={"chat_id": SUPERADMIN_ID, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=10,
        )
    except Exception as e:
        print(f"notify_admin error: {e}", flush=True)


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
    """Голый TCP-коннект. Быстрый, но слепой: не отличит живой процесс от
    зависшего — порт может слушать (accept), а дальше не отвечать."""
    t0 = time.time()
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True, int((time.time() - t0) * 1000)
    except Exception:
        return False, None


def check_tls_handshake(host, port, sni=None, timeout=6):
    """TLS-хендшейк до host:port. Сильнее голого TCP-коннекта: ловит зависший
    процесс (порт слушает, но handshake не завершается), а не только 'мёртвый' порт.
    Это и есть реальный сигнал "VPN доступен пользователю" — Reality отвечает
    на TLS ClientHello так же, как обычный HTTPS-сайт.
    sni — какое имя слать в ClientHello (server_hostname); по умолчанию host.
    Важно передавать настоящий SNI-донор (server['sni']), а не голый IP: если
    Reality сконфигурирован строго (serverNames без запасного 'dest'-фоллбека),
    он рвёт хендшейк на несовпадающем SNI как невалидный трафик — так уже давало
    ложный DOWN, когда сюда прилетал IP вместо реального домена.
    Возвращает (ok, latency_ms)."""
    t0 = time.time()
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=(sni or host)) as ssock:
                _ = ssock.version()
        return True, int((time.time() - t0) * 1000)
    except Exception:
        return False, None


def xui_check(server):
    """Логин в 3X-UI (v3 Bearer-токен если задан api_token, иначе v2 cookie-логин)
    + получить кол-во клиентов. Это здоровье ПАНЕЛИ УПРАВЛЕНИЯ, не VPN-сервиса.
    (panel_up, latency_ms, clients, error)."""
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


# Последнее известное состояние сервиса на сервер — для дебаунса алертов
# (шлём только на смене состояния, не на каждом цикле). Живёт в памяти процесса:
# рестарт демона в худшем случае даст один спорный алерт, не страшно.
_last_service_state = {}


def _handle_alert(code, name, service_up, err):
    prev = _last_service_state.get(code)
    _last_service_state[code] = service_up
    if prev is None:
        return  # первый цикл после старта демона — не с чем сравнивать, не алертим
    if prev == service_up:
        return  # состояние не менялось
    if service_up:
        notify_admin(f"✅ <b>{name or code} снова доступен</b>\n\nVPN-порт отвечает на TLS-хендшейк.")
    else:
        notify_admin(f"🔴 <b>{name or code} недоступен!</b>\n\n"
                     f"VPN-порт не проходит TLS-хендшейк — пользователи не могут подключиться."
                     + (f"\nПричина панели: {err}" if err else ""))


def check_one(server):
    code = server.get("code")
    name = server.get("country_name")
    ip = server.get("server_ip")
    port = int(server.get("server_port") or 443)
    sni = server.get("sni")

    panel_up, panel_latency, clients, panel_err = xui_check(server)
    tcp_ok, _ = check_tcp(ip, port)                            # порт открыт?
    service_up, service_lat = check_tls_handshake(ip, port, sni=sni)    # реальный сигнал "VPN работает"
    target_ok, target_lat = check_tls_handshake(sni, 443) if sni else (None, None)

    _handle_alert(code, name, service_up, panel_err)

    # error: приоритет диагностике, которая объясняет ЧТО именно сломано.
    # tcp открыт, но TLS не прошёл — процесс завис. tcp закрыт — процесс не слушает.
    # Если сам VPN-сервис жив, но не смогли залогиниться в панель — это отдельная,
    # менее критичная проблема (не мешает текущим клиентам), помечаем отдельно.
    if service_up:
        error = None if panel_up else f"panel: {panel_err}"
    elif tcp_ok:
        error = "порт открыт, но TLS-хендшейк не прошёл (процесс завис?)"
    else:
        error = "порт не отвечает (сервис не слушает / firewall / сеть)"

    row = {
        "server_code": code,
        "server_name": name,
        # is_up — реальная доступность VPN (TLS-хендшейк на боевой порт). Это главный
        # статус в админке и то, что участвует в uptime%. Раньше тут ошибочно был
        # логин в панель управления — панель может тормозить при полностью рабочем VPN.
        "is_up": bool(service_up),
        "latency_ms": service_lat if service_lat is not None else panel_latency,
        "xray_listening": bool(tcp_ok),
        "clients_count": clients,
        "target_ok": target_ok,
        "target_latency_ms": target_lat,
        "sni": sni,
        "error": error,
    }
    try:
        requests.post(f"{SUPABASE_URL}/rest/v1/server_health", headers=H, json=row, timeout=10)
    except Exception as e:
        print(f"write health error {code}: {e}", flush=True)
    status = "UP" if service_up else "DOWN"
    print(f"[{datetime.utcnow().isoformat()}] {code}: service={status} panel={'UP' if panel_up else 'DOWN'} "
          f"tcp={'Y' if tcp_ok else 'N'} lat={service_lat}ms clients={clients} target={'Y' if target_ok else 'N'}"
          + (f" err={error}" if error else ""), flush=True)


def cleanup_old():
    """Чистка записей старше 30 дней (раз в цикл, не критично).
    30 дней вместо прежних 7 — чтобы хватало на анализ инцидентов месячной давности."""
    try:
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
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
