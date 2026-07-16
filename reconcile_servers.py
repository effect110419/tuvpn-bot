#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuVPN Reconcile — автосверка клиентов на VPN-панелях с активными подписками.

Почему это нужно: issue_subscription/backfill/cleanup — это единичные операции
по требованию. Если в момент выдачи/удаления юзера конкретная панель была
недоступна (перегружена, упала, сетевой сбой), клиент на ней навсегда
рассинхронизируется с БД — либо остаётся «протухшим» после того как юзер
удалён/подписка истекла, либо не появляется вовсе, хотя должен быть.
Раньше это лечилось только вручную кнопкой в админке — на деле правилось
редко, и на de-2 накопилось 369 протухших клиентов, на остальных — под сотню
недостающих. Этот скрипт по расписанию (systemd-таймер) сам:
  1. backfill — докатывает недостающих активных клиентов на каждый сервер;
  2. cleanup  — снимает клиентов, которых больше нет в активных подписках.
Тихо логирует, если сверка ничего не нашла; шлёт Максиму сводку в Telegram,
только если реально что-то поправил или встретил ошибку.

Запускается как systemd oneshot + timer (deploy/systemd/tuvpn-reconcile.*).
"""
import sys
import logging

sys.path.insert(0, '/root/tuvpn')
from proxy import get_active_servers, backfill_server_clients, cleanup_stale_clients, notify_user, SUPERADMIN_ID

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("reconcile")


def main():
    servers = get_active_servers()
    if not servers:
        log.warning("Нет активных серверов — нечего сверять")
        return

    lines = []
    total_added = 0
    total_removed = 0
    total_errors = 0

    for srv in servers:
        code = srv.get("code") or srv.get("country_name") or "?"

        try:
            bf = backfill_server_clients(srv)
        except Exception as e:
            bf = {"ok": 0, "failed": 0, "failures": [str(e)[:150]]}
        bf_failed = bf.get("failed", 0)
        bf_ok = bf.get("ok", 0)

        try:
            cl = cleanup_stale_clients(srv)
        except Exception as e:
            cl = {"removed": 0, "error": str(e)[:150]}
        cl_removed = cl.get("removed", 0)
        cl_error = cl.get("error")

        total_removed += cl_removed
        total_errors += bf_failed + (1 if cl_error else 0)

        log.info(f"{code}: backfill ok={bf_ok} failed={bf_failed} | cleanup removed={cl_removed} error={cl_error}")

        # В отчёт Максиму попадает только то, что реально поправили/сломалось —
        # успешный no-op backfill (ok=N, failed=0) не в счёт.
        if bf_failed or cl_removed or cl_error:
            part = f"<b>{code}</b>: "
            bits = []
            if cl_removed:
                bits.append(f"снято протухших {cl_removed}")
            if bf_failed:
                bits.append(f"⚠️ не докатилось {bf_failed}")
            if cl_error:
                bits.append(f"⚠️ ошибка очистки: {cl_error}")
            lines.append(part + ", ".join(bits))

    if not lines:
        log.info("Сверка чистая — расхождений не найдено")
        return

    log.info("Найдены расхождения — уведомляю суперадмина")
    text = "🔧 <b>Автосверка VPN-серверов</b>\n\n" + "\n".join(lines)
    if total_errors:
        text += f"\n\n⚠️ Ошибок: {total_errors} — стоит проверить вручную."
    notify_user(SUPERADMIN_ID, text)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("Автосверка упала")
        try:
            notify_user(SUPERADMIN_ID, f"⚠️ <b>Автосверка VPN-серверов упала</b>\n\n{str(e)[:500]}")
        except Exception:
            pass
        sys.exit(1)
