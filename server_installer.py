"""
TuVPN — Server Installer
Автоматическая установка нового VPN-сервера (3X-UI + Reality) на чистом VPS.

Использование:
    from server_installer import ServerInstaller
    installer = ServerInstaller(sb, install_uuid="...", logger=app.logger)
    installer.run()  # запускается в отдельном потоке
"""
import os
import re
import time
import json
import uuid
import secrets
import string
import socket
import logging
import threading
from typing import Optional, List, Dict, Any

import paramiko
import requests

requests.packages.urllib3.disable_warnings()


# ────────────────────────────────────────────────────────────────────────────
# Константы
# ────────────────────────────────────────────────────────────────────────────

REALITY_TARGET_CANDIDATES = [
    "chat.deepseek.com",
    "cdn.kernel.org",
    "addons.mozilla.org",
    "docs.python.org",
    "www.cloudflare.com",
    "www.microsoft.com",
    "www.icloud.com",
]

# Шаги установки и их прогресс
STEPS = [
    ("connecting",         5,  "Подключение по SSH"),
    ("system_update",      15, "Обновление системы"),
    ("install_packages",   25, "Установка пакетов"),
    ("configure_firewall", 30, "Настройка firewall"),
    ("install_xui",        55, "Установка 3X-UI (это может занять 1-2 мин)"),
    ("configure_panel",    65, "Настройка панели"),
    ("create_inbound",     75, "Создание VLESS-Reality inbound"),
    ("check_targets",      85, "Проверка доступных Reality target"),
    ("awaiting_target",    85, "Ожидание выбора target от админа"),
    ("apply_target",       90, "Применение выбранного target"),
    ("save_server",        95, "Сохранение в БД"),
    ("migrate_clients",    98, "Миграция существующих клиентов"),
    ("completed",          100, "✓ Установка завершена"),
]


# ────────────────────────────────────────────────────────────────────────────
# Утилиты
# ────────────────────────────────────────────────────────────────────────────

def gen_random_string(length: int = 18, alphabet: Optional[str] = None) -> str:
    """Генерирует случайную строку для логина/паролей/base path."""
    if alphabet is None:
        alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def gen_random_port() -> int:
    """Генерирует случайный порт для 3X-UI панели."""
    return secrets.choice(range(15000, 65000))


# ────────────────────────────────────────────────────────────────────────────
# Основной класс
# ────────────────────────────────────────────────────────────────────────────

class ServerInstaller:
    """
    Управляет процессом установки нового сервера.
    Состояние хранится в Supabase в таблице server_installations.
    """

    def __init__(self, sb_client, install_uuid: str, ssh_password: Optional[str] = None,
                 logger: Optional[logging.Logger] = None):
        self.sb = sb_client
        self.install_uuid = install_uuid
        self.ssh_password = ssh_password  # передаётся при старте, не хранится в БД
        self.logger = logger or logging.getLogger(__name__)
        self.ssh: Optional[paramiko.SSHClient] = None
        self.state: Dict[str, Any] = {}

    # ────────── работа с состоянием ──────────

    def _load_state(self) -> Dict[str, Any]:
        r = self.sb.table("server_installations").select("*").eq(
            "install_uuid", self.install_uuid
        ).limit(1).execute()
        if not r.data:
            raise RuntimeError(f"Installation {self.install_uuid} not found")
        self.state = r.data[0]
        return self.state

    def _update_state(self, **fields):
        fields["updated_at"] = "now()"
        # Supabase Python client не умеет "now()" — используем datetime
        from datetime import datetime, timezone
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.sb.table("server_installations").update(fields).eq(
            "install_uuid", self.install_uuid
        ).execute()
        # Локально тоже обновим
        self.state.update(fields)

    def _log(self, message: str, level: str = "info"):
        """Добавляет строку в log_lines."""
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"[{ts}] {message}"
        if level == "error":
            self.logger.error(f"[install:{self.install_uuid[:8]}] {message}")
        else:
            self.logger.info(f"[install:{self.install_uuid[:8]}] {message}")
        # Берём текущие log_lines, добавляем, сохраняем
        cur_logs = self.state.get("log_lines") or []
        if isinstance(cur_logs, str):
            try:
                cur_logs = json.loads(cur_logs)
            except Exception:
                cur_logs = []
        cur_logs.append(line)
        # Не больше последних 200 строк
        cur_logs = cur_logs[-200:]
        self.sb.table("server_installations").update({
            "log_lines": cur_logs
        }).eq("install_uuid", self.install_uuid).execute()
        self.state["log_lines"] = cur_logs

    def _set_step(self, step_id: str):
        """Обновляет текущий шаг и прогресс."""
        for sid, percent, label in STEPS:
            if sid == step_id:
                self._update_state(
                    current_step=step_id,
                    progress_percent=percent,
                )
                self._log(f"▶ {label}")
                return
        # Если шаг не нашёлся — просто запишем
        self._update_state(current_step=step_id)

    def _fail(self, error: str):
        self._log(f"✗ ОШИБКА: {error}", level="error")
        self._update_state(status="failed", error_message=error)

    # ────────── SSH-команды ──────────

    def _ssh_connect(self):
        ip = self.state["server_ip"]
        port = self.state.get("ssh_port") or 22
        self._log(f"Подключение к {ip}:{port}...")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=ip,
            port=port,
            username="root",
            password=self.ssh_password,
            timeout=15,
            banner_timeout=15,
            auth_timeout=15,
        )
        self.ssh = client
        self._log("✓ SSH-соединение установлено")

    def _ssh_run(self, cmd: str, timeout: int = 120, check: bool = True) -> tuple:
        """Выполняет команду по SSH. Возвращает (rc, stdout, stderr)."""
        if not self.ssh:
            raise RuntimeError("SSH-соединение не установлено")
        # Логируем кратко
        cmd_short = cmd if len(cmd) < 100 else cmd[:97] + "..."
        self.logger.debug(f"SSH> {cmd_short}")
        stdin, stdout, stderr = self.ssh.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        rc = stdout.channel.recv_exit_status()
        if check and rc != 0:
            raise RuntimeError(f"Команда упала (rc={rc}): {cmd_short}\nSTDERR: {err[:500]}")
        return rc, out, err

    # ────────── основной flow ──────────

    def run(self):
        """Запускается в отдельном потоке. Главная процедура установки."""
        try:
            self._load_state()

            if self.state.get("status") == "completed":
                self._log("Установка уже завершена ранее — нечего делать")
                return

            # Если статус awaiting_target и target ещё не выбран — выходим, ждём
            if self.state.get("status") == "awaiting_target" and not self.state.get("selected_target"):
                self._log("Ожидание выбора target — установка приостановлена")
                return

            self._update_state(status="running", error_message=None)

            # 1. Подключение
            self._set_step("connecting")
            self._ssh_connect()

            # 2. Обновление системы
            self._set_step("system_update")
            self._ssh_run("export DEBIAN_FRONTEND=noninteractive; apt-get update -y", timeout=180)
            self._log("✓ apt update готово")

            # 3. Установка базовых пакетов
            self._set_step("install_packages")
            self._ssh_run(
                "export DEBIAN_FRONTEND=noninteractive; "
                "apt-get install -y curl wget nano htop ufw fail2ban sqlite3 socat",
                timeout=240
            )
            self._log("✓ Базовые пакеты установлены")

            # 4. Hostname
            slug = self.state.get("code_slug") or "vpn"
            self._ssh_run(f"hostnamectl set-hostname vpn-{slug} 2>/dev/null || true", check=False)

            # 5. Firewall
            self._set_step("configure_firewall")
            for port_rule in ["22/tcp", "443/tcp", "80/tcp"]:
                self._ssh_run(f"ufw allow {port_rule}", check=False)
            # Откроем порт панели после установки
            self._ssh_run("ufw --force enable", check=False)
            self._log("✓ UFW настроен (22, 80, 443)")

            # 6. Проверка: установлен ли уже 3X-UI?
            rc, out, _ = self._ssh_run("which x-ui 2>/dev/null && systemctl is-active x-ui 2>/dev/null", check=False)
            xui_already_installed = (rc == 0 and "active" in out)

            if xui_already_installed:
                self._log("✓ 3X-UI уже установлен — пропускаем установку")
            else:
                self._set_step("install_xui")
                self._install_xui()

            # 7. Настройка панели
            self._set_step("configure_panel")
            self._configure_panel()

            # 8. Создание inbound
            self._set_step("create_inbound")
            self._create_inbound()

            # 9. Проверка Reality target
            self._set_step("check_targets")
            available = self._check_reality_targets()
            self._update_state(available_targets=available)

            # Если уже выбран ранее — продолжаем; если нет — ждём
            if not self.state.get("selected_target"):
                self._set_step("awaiting_target")
                self._update_state(status="awaiting_target")
                self._log(f"⏸ Ожидание выбора target от админа. Доступно: {len(available)} вариантов")
                return  # выходим, продолжим когда админ выберет

            # 10. Применение target
            self._set_step("apply_target")
            self._apply_reality_target(self.state["selected_target"])

            # 11. Сохранение в servers
            self._set_step("save_server")
            self._save_to_servers_table()

            # 12. Миграция клиентов
            self._set_step("migrate_clients")
            self._migrate_existing_clients()

            # 13. Готово
            from datetime import datetime, timezone
            self._set_step("completed")
            self._update_state(
                status="completed",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            self._log("🎉 Сервер успешно установлен и добавлен в подписку!")

        except paramiko.AuthenticationException:
            self._fail("Неверный SSH-пароль")
        except (paramiko.SSHException, socket.timeout, socket.error) as e:
            self._fail(f"SSH-ошибка: {e}")
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.logger.error(f"Installation crashed: {tb}")
            self._fail(f"{type(e).__name__}: {e}")
        finally:
            if self.ssh:
                try:
                    self.ssh.close()
                except Exception:
                    pass
                self.ssh = None

    # ────────── шаги ──────────

    def _install_xui(self):
        """Устанавливает 3X-UI с предзаданными параметрами."""
        # Генерируем креды если их ещё нет
        if not self.state.get("panel_port"):
            port = gen_random_port()
            login = gen_random_string(10)
            password = gen_random_string(20)
            base_path = gen_random_string(18)
            self._update_state(
                panel_port=port,
                panel_login=login,
                panel_password=password,
                panel_base_path=base_path,
            )
        else:
            port = self.state["panel_port"]
            login = self.state["panel_login"]
            password = self.state["panel_password"]
            base_path = self.state["panel_base_path"]

        self._log(f"Креды панели сгенерированы (порт {port})")

        # Установочный скрипт 3X-UI принимает параметры через переменные среды
        # или через автоматизированный ввод. Используем подход с автоматизированными ответами.
        install_cmd = (
            "export DEBIAN_FRONTEND=noninteractive && "
            "cd /tmp && "
            "wget -q -O /tmp/x-ui-install.sh https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh && "
            "chmod +x /tmp/x-ui-install.sh && "
            # Отвечаем на интерактивные вопросы: y, login, password, port, base_path, 4 (skip SSL — настроим через nginx позже или через панель отдельно)
            # 4 = Skip SSL, мы пока без сертификата
            f"echo 'y\\n{login}\\n{password}\\n{port}\\n{base_path}\\n4' | bash /tmp/x-ui-install.sh"
        )
        self._log("Запускаю установочный скрипт 3X-UI...")
        rc, out, err = self._ssh_run(install_cmd, timeout=600, check=False)
        # Скрипт может вернуть нестандартный rc — проверим что x-ui запустился
        self._ssh_run("sleep 3 && systemctl is-active x-ui", timeout=15)
        self._log("✓ 3X-UI установлен")

        # Открываем порт панели
        self._ssh_run(f"ufw allow {port}/tcp", check=False)

    def _configure_panel(self):
        """Применяет креды через x-ui CLI (на случай если установщик не принял их)."""
        port = self.state["panel_port"]
        login = self.state["panel_login"]
        password = self.state["panel_password"]
        base_path = self.state["panel_base_path"]

        # На свежеустановленном 3X-UI CLI поддерживает все эти настройки
        self._ssh_run(f"/usr/local/x-ui/x-ui setting -port {port}", check=False)
        self._ssh_run(f"/usr/local/x-ui/x-ui setting -username {login}", check=False)
        self._ssh_run(f"/usr/local/x-ui/x-ui setting -password {password}", check=False)
        self._ssh_run(f"/usr/local/x-ui/x-ui setting -webBasePath {base_path}", check=False)
        self._ssh_run("systemctl restart x-ui", check=False)
        time.sleep(3)
        self._log(f"✓ Креды панели применены (port={port}, base_path=/{base_path}/)")

    def _create_inbound(self):
        """Создаёт VLESS-Reality inbound через 3X-UI API."""
        ip = self.state["server_ip"]
        port = self.state["panel_port"]
        base_path = self.state["panel_base_path"]
        login = self.state["panel_login"]
        password = self.state["panel_password"]

        panel_url = f"http://{ip}:{port}/{base_path}"

        # Логин (без HTTPS — Skip SSL вариант)
        session = self._xui_login(panel_url, login, password)

        # Генерируем уникальные Reality-ключи для этого сервера (если ещё нет)
        if not self.state.get("public_key"):
            # Просим 3X-UI сгенерировать пару X25519 ключей
            r = session.post(f"{panel_url}/server/getNewX25519Cert", timeout=15)
            data = r.json()
            if not data.get("success"):
                raise RuntimeError(f"Не удалось получить X25519 ключи: {data}")
            keys = data["obj"]
            pub_key = keys["publicKey"]
            priv_key = keys["privateKey"]
            short_id = secrets.token_hex(8)
            self._update_state(
                public_key=pub_key,
                private_key=priv_key,
                short_id=short_id,
            )
            self._log(f"✓ Сгенерированы Reality ключи (shortId={short_id})")
        else:
            pub_key = self.state["public_key"]
            priv_key = self.state["private_key"]
            short_id = self.state["short_id"]

        # Placeholder host для target — потом заменим
        placeholder_host = "w" + "w" + "w" + "." + "b" + "i" + "n" + "g" + "." + "c" + "o" + "m"

        # Тело запроса addInbound
        settings = {
            "clients": [],
            "decryption": "none",
            "encryption": "none",
            "fallbacks": [],
        }
        stream_settings = {
            "network": "tcp",
            "security": "reality",
            "externalProxy": [],
            "realitySettings": {
                "show": False,
                "xver": 0,
                "target": placeholder_host + ":443",
                "serverNames": [placeholder_host],
                "privateKey": priv_key,
                "minClientVer": "",
                "maxClientVer": "",
                "maxTimediff": 0,
                "shortIds": [short_id],
                "settings": {
                    "publicKey": pub_key,
                    "fingerprint": "chrome",
                    "serverName": "",
                    "spiderX": "/",
                },
            },
            "tcpSettings": {
                "acceptProxyProtocol": False,
                "header": {"type": "none"},
            },
        }
        sniffing = {
            "enabled": False,
            "destOverride": ["http", "tls", "quic", "fakedns"],
            "metadataOnly": False,
            "routeOnly": False,
        }

        payload = {
            "remark": "VLESS-Reality",
            "enable": True,
            "port": 443,
            "protocol": "vless",
            "settings": json.dumps(settings, ensure_ascii=False),
            "streamSettings": json.dumps(stream_settings, ensure_ascii=False),
            "sniffing": json.dumps(sniffing, ensure_ascii=False),
            "expiryTime": 0,
            "total": 0,
            "up": 0,
            "down": 0,
            "listen": "",
        }
        r = session.post(f"{panel_url}/panel/api/inbounds/add", json=payload, timeout=20)
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"addInbound failed: {data}")

        # Получаем ID созданного inbound
        r2 = session.get(f"{panel_url}/panel/api/inbounds/list", timeout=10)
        inbounds = r2.json().get("obj") or []
        inbound_id = None
        for ib in inbounds:
            if ib.get("port") == 443 and ib.get("protocol") == "vless":
                inbound_id = ib.get("id")
                break
        if not inbound_id:
            raise RuntimeError("Не удалось найти созданный inbound")

        self._update_state(panel_port=port)  # уже был, но обновим updated_at
        # Сохраняем inbound_id для дальнейшей работы через временное поле
        # (у нас в server_installations есть selected_target — отдельный, но для inbound_id колонки нет)
        # Будем брать его динамически из 3X-UI на следующих шагах.
        self._log(f"✓ Inbound создан (id={inbound_id})")

    def _xui_login(self, panel_url: str, login: str, password: str) -> requests.Session:
        """Логин в 3X-UI с поддержкой CSRF."""
        session = requests.Session()
        session.verify = False
        csrf = None
        try:
            get_resp = session.get(f"{panel_url}/", timeout=10, headers={
                "User-Agent": "Mozilla/5.0"
            })
            if get_resp.status_code == 200:
                m = re.search(r'name="csrf-token"\s+content="([^"]+)"', get_resp.text)
                if m:
                    csrf = m.group(1)
        except Exception:
            pass

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": f"{panel_url}/",
        }
        if csrf:
            headers["X-CSRF-Token"] = csrf
        session.headers.update(headers)

        if csrf:
            r = session.post(f"{panel_url}/login", data={"username": login, "password": password}, timeout=15)
        else:
            r = session.post(f"{panel_url}/login", json={"username": login, "password": password}, timeout=15)
        if r.status_code == 200 and r.json().get("success"):
            return session
        raise RuntimeError(f"3X-UI login failed: HTTP {r.status_code}, body={r.text[:200]}")

    def _check_reality_targets(self) -> List[Dict]:
        """С удалённого сервера через SSH проверяет какие домены отдают TLS."""
        self._log("Проверяю кандидатов для Reality target...")
        results = []
        for host in REALITY_TARGET_CANDIDATES:
            # curl + измеряем время handshake
            cmd = (
                f"curl -sI --connect-timeout 3 --max-time 5 -o /dev/null "
                f"-w '%{{http_code}}|%{{time_connect}}|%{{time_appconnect}}' "
                f"https://{host}/ 2>/dev/null"
            )
            rc, out, _ = self._ssh_run(cmd, timeout=15, check=False)
            out = out.strip()
            if rc == 0 and "|" in out:
                code, t_conn, t_app = out.split("|")
                ms = int(float(t_app) * 1000) if t_app else 0
                # Подходит если код 2xx/3xx/405 (405 для chat.deepseek.com — это норма)
                if code and code[0] in ("2", "3") or code == "405":
                    results.append({
                        "host": host,
                        "http_code": code,
                        "latency_ms": ms,
                    })
                    self._log(f"  ✓ {host} → {code} ({ms}ms)")
                else:
                    self._log(f"  ✗ {host} → {code}")
            else:
                self._log(f"  ✗ {host} → недоступен")
        # Сортируем по латентности
        results.sort(key=lambda x: x["latency_ms"])
        self._log(f"✓ Найдено доступных target: {len(results)}")
        return results

    def _apply_reality_target(self, host: str):
        """Меняет target и serverNames в БД 3X-UI."""
        self._log(f"Применяю target: {host}")
        py_code = (
            "import sqlite3,json; "
            f"H={host!r}; "
            "c=sqlite3.connect('/etc/x-ui/x-ui.db'); "
            "r=c.execute('SELECT id, stream_settings FROM inbounds WHERE port=443').fetchone(); "
            "d=json.loads(r[1]); "
            "rs=d['realitySettings']; "
            "rs['target']=H+':443'; "
            "rs['serverNames']=[H]; "
            "c.execute('UPDATE inbounds SET stream_settings=? WHERE id=?', (json.dumps(d, ensure_ascii=False), r[0])); "
            "c.commit(); c.close(); "
            "print('OK')"
        )
        self._ssh_run(f"python3 -c \"{py_code}\"", timeout=15)
        self._ssh_run("x-ui restart-xray", check=False)
        time.sleep(3)
        self._log(f"✓ Target применён: {host}")

    def _save_to_servers_table(self):
        """Сохраняет новый сервер в Supabase.servers."""
        ip = self.state["server_ip"]
        port = self.state["panel_port"]
        base_path = self.state["panel_base_path"]
        login = self.state["panel_login"]
        password = self.state["panel_password"]
        target = self.state["selected_target"]
        slug = self.state.get("code_slug") or f"srv-{self.install_uuid[:6]}"

        # Получаем inbound_id с сервера
        panel_url = f"http://{ip}:{port}/{base_path}"
        session = self._xui_login(panel_url, login, password)
        r = session.get(f"{panel_url}/panel/api/inbounds/list", timeout=10)
        inbounds = r.json().get("obj") or []
        inbound_id = None
        for ib in inbounds:
            if ib.get("port") == 443 and ib.get("protocol") == "vless":
                inbound_id = ib.get("id")
                break
        if not inbound_id:
            raise RuntimeError("Inbound id не найден при сохранении")

        # Идемпотентность: проверяем нет ли уже такого сервера
        existing = self.sb.table("servers").select("id").eq("server_ip", ip).limit(1).execute()
        server_data = {
            "code": slug,
            "country_name": self.state["country_name"],
            "country_flag": self.state.get("country_flag") or "🏳️",
            "country_code": self.state.get("country_code") or "??",
            "panel_url": panel_url,
            "panel_login": login,
            "panel_password": password,
            "inbound_id": inbound_id,
            "server_ip": ip,
            "server_port": 443,
            "public_key": self.state["public_key"],
            "short_id": self.state["short_id"],
            "sni": target,
            "flow": "xtls-rprx-vision",
            "fingerprint": "chrome",
            "is_active": True,
            "sort_order": self.state.get("sort_order") or 99,
        }
        if existing.data:
            srv_id = existing.data[0]["id"]
            self.sb.table("servers").update(server_data).eq("id", srv_id).execute()
            self._log(f"✓ Сервер обновлён в БД (id={srv_id})")
        else:
            ins = self.sb.table("servers").insert(server_data).execute()
            srv_id = ins.data[0]["id"]
            self._log(f"✓ Сервер добавлен в БД (id={srv_id})")
        self._update_state(final_server_id=srv_id)

    def _migrate_existing_clients(self):
        """Добавляет всех активных клиентов на новый сервер."""
        ip = self.state["server_ip"]
        port = self.state["panel_port"]
        base_path = self.state["panel_base_path"]
        login = self.state["panel_login"]
        password = self.state["panel_password"]
        panel_url = f"http://{ip}:{port}/{base_path}"

        # Получаем inbound_id
        session = self._xui_login(panel_url, login, password)
        r = session.get(f"{panel_url}/panel/api/inbounds/list", timeout=10)
        inbounds = r.json().get("obj") or []
        inbound_id = None
        for ib in inbounds:
            if ib.get("port") == 443:
                inbound_id = ib.get("id")
                break
        if not inbound_id:
            self._log("⚠ Inbound не найден — пропускаю миграцию", level="error")
            return

        # Активные подписки
        subs_q = self.sb.table("subscriptions").select("*").eq("status", "active").execute()
        subs = subs_q.data or []
        self._log(f"Активных подписок для миграции: {len(subs)}")
        added = 0
        skipped = 0

        from datetime import datetime, timezone

        for sub in subs:
            sub_url = sub.get("sub_url") or ""
            client_uuid = sub_url.rsplit("/", 1)[-1]
            if not client_uuid:
                continue

            # Проверяем не добавлен ли уже
            r = session.get(f"{panel_url}/panel/api/inbounds/list", timeout=10)
            inbounds = r.json().get("obj") or []
            target_inb = next((i for i in inbounds if i.get("id") == inbound_id), None)
            if target_inb:
                settings = json.loads(target_inb.get("settings", "{}"))
                existing_uuids = [c.get("id") for c in settings.get("clients", [])]
                if client_uuid in existing_uuids:
                    skipped += 1
                    continue

            # Считаем expire_ms
            try:
                exp = datetime.fromisoformat(sub["expires_at"].replace("Z", "+00:00"))
                expire_ms = int(exp.timestamp() * 1000)
            except Exception:
                continue

            ts = int(time.time())
            payload = {
                "id": inbound_id,
                "settings": json.dumps({"clients": [{
                    "id": client_uuid,
                    "email": f"user_{sub['user_id']}_{ts}",
                    "limitIp": sub.get("devices", 1),
                    "totalGB": 0,
                    "expiryTime": expire_ms,
                    "enable": True,
                    "flow": "xtls-rprx-vision",
                }]}),
            }
            r2 = session.post(f"{panel_url}/panel/api/inbounds/addClient", json=payload, timeout=15)
            if r2.status_code == 200 and r2.json().get("success"):
                added += 1
            else:
                self._log(f"⚠ Не удалось добавить {client_uuid[:8]} (HTTP {r2.status_code})")

        self._log(f"✓ Миграция завершена: добавлено {added}, пропущено {skipped}")


# ────────────────────────────────────────────────────────────────────────────
# Публичные функции
# ────────────────────────────────────────────────────────────────────────────

# Глобальное хранилище активных потоков (по install_uuid)
_active_threads: Dict[str, threading.Thread] = {}


def start_installation_thread(sb_client, install_uuid: str,
                               ssh_password: str,
                               logger: Optional[logging.Logger] = None) -> threading.Thread:
    """Стартует установку в отдельном потоке."""
    # Если уже запущен — не дублируем
    if install_uuid in _active_threads and _active_threads[install_uuid].is_alive():
        return _active_threads[install_uuid]

    def _worker():
        try:
            installer = ServerInstaller(sb_client, install_uuid, ssh_password, logger)
            installer.run()
        except Exception as e:
            if logger:
                logger.error(f"Worker crashed for {install_uuid}: {e}")

    t = threading.Thread(target=_worker, daemon=True, name=f"installer-{install_uuid[:8]}")
    t.start()
    _active_threads[install_uuid] = t
    return t


def create_installation(sb_client, server_ip: str, country_name: str,
                        country_flag: str, country_code: str,
                        code_slug: str, sort_order: int = 99,
                        ssh_port: int = 22, started_by_admin_id: Optional[int] = None) -> str:
    """Создаёт запись в server_installations и возвращает install_uuid."""
    install_uuid = str(uuid.uuid4())
    sb_client.table("server_installations").insert({
        "install_uuid": install_uuid,
        "server_ip": server_ip,
        "ssh_port": ssh_port,
        "country_name": country_name,
        "country_flag": country_flag,
        "country_code": country_code,
        "code_slug": code_slug,
        "sort_order": sort_order,
        "status": "pending",
        "started_by_admin_id": started_by_admin_id,
    }).execute()
    return install_uuid
