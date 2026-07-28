# TuVPN — Полный контекст проекта

Коммерческий VPN-сервис, продаётся через Telegram. Подписки, мульти-серверный VPN, платежи, веб-панель администратора.

---

## Стек технологий

| Компонент | Технология |
|-----------|-----------|
| Backend API | Flask (`proxy.py`), порт 5000 (nginx проксирует) |
| Боты | aiogram 3.x — `bot.py` (продажи) + `support_bot.py` (поддержка) |
| Frontend | Vanilla JS (`app.js`), HTML/CSS — веб-панель админа |
| База данных | Supabase (Postgres), клиент `supabase-py` |
| VPN-панели | 3X-UI (Xray, протокол Reality) на каждом сервере |
| Платежи | ЮКасса (банковские карты) + Telegram Stars |
| Конфиг | `config.py` читает из `.env` (не коммитится) |

---

## Серверы

| Алиас SSH | Роль | IP | Примечания |
|-----------|------|----|-----------|
| `app` | APP — backend, боты, nginx, веб | 188.214.107.107 | Все сервисы + Supabase-клиент |
| `fi` | VPN-узел Финляндия | 89.125.53.210 | Legacy-сервер, первый |
| `nl` | VPN-узел Нидерланды | 78.17.16.183 | |
| `de` | VPN-узел Германия | 78.17.56.109 | |
| `de2` | VPN-узел Германия 2 | 89.127.203.48 | |

SSH: `root` через ключ `~/.ssh/tuvpn`. Подключение: `ssh app`, `ssh fi` и т.д.

---

## Сервисы systemd (на APP-сервере)

```bash
systemctl restart tuvpn-proxy    # Flask backend
systemctl restart tuvpn-bot      # Sales bot
systemctl restart tuvpn-support  # Support bot

journalctl -u tuvpn-proxy -f     # Логи backend
journalctl -u tuvpn-bot -f       # Логи sales-бота
journalctl -u tuvpn-support -f   # Логи support-бота
```

---

## Расположение файлов на сервере

- Код: `/root/tuvpn/`
- Веб-панель: `/var/www/html/`
- nginx конфиг: `deploy/nginx/` (локальный репо)

---

## Ключевые файлы

### `proxy.py` — Flask backend
Главный файл. Запускается на `127.0.0.1:5000`, nginx проксирует снаружи.

**Основные блоки:**
- `xui_session(server)` — логин в 3X-UI v2 (cookie-сессия + CSRF)
- `_v3_session(server)` — Bearer-токен для 3X-UI v3.x
- `xui_v3_add_client` / `xui_v3_update_client` / `xui_v3_del_client` — API v3
- `xui_add_client_on_server` / `xui_update_client_on_server` — роутинг v2/v3
- `track_device(...)` — регистрация устройств, проверка лимита
- `issue_subscription(uid, devices, days)` — выдать/продлить подписку на всех серверах
- `apply_referral_bonus(user_id, days, reason)` — реферальный бонус
- `backfill_server_clients(server)` — синхронизация всех активных подписок на сервер
- `GET /sub/<uuid>` — отдача конфига клиенту (проверяет лимит устройств)
- `POST /yookassa/webhook` — обработка webhook ЮКассы (с верификацией через API)

**Admin API (`/admin-api/*`):**
- Защищён `before_request` middleware — cookie `admin_session`
- Auth endpoints: `/admin-api/auth/start`, `/poll`, `/me`, `/logout`
- Суперадмин: `SUPERADMIN_ID = 784871620` (Максим)
- RBAC: `get_admin_permissions(tg_id)`, `has_permission(perm)`, `require_perm(perm)`
- Generic DB proxy: `GET/POST/PATCH/DELETE /admin-api/db/<table>`
- Analytics: `/admin-api/analytics/funnel`, `/cohorts`, `/calendar`
- Finance: `/admin-api/finance/sources`, `/expenses`, `/investments`, `/breakdown`
- Broadcasts: `/admin-api/broadcast/preview`, `/send`
- Geo: `/admin-api/geo/points`, `/geo/resolve`
- Monitoring: `/admin-api/monitor/health`, `/latest`
- User audit: `/admin-api/user_audit/<uid>` — полная диагностика
- Watchlist: `/admin-api/watchlist` — VIP-пользователи для мониторинга
- Server install: `/admin-api/install_server` (автоматическая установка 3X-UI)

### `bot.py` — sales-бот (`@MaxArtVPN_bot`)
- aiogram 3.x, FSM для состояний покупки
- `PRICES` — тарифы в рублях: 1/2/5 устройств × 1/3/12 месяцев
- `PRICES_STARS` — тарифы в Telegram Stars
- Реферальная система: +7 дней новому юзеру, +3 дня реферу за переход, +7 дней реферу за оплату
- Промокоды: скидка `percent` или бонусные дни `days`
- UTM-кампании: `?start=CAMPAIGN_CODE` → запись в `campaigns`, начисление `bonus_days`
- Admin login deeplink: `?start=login_admin_TOKEN` → подтверждение входа суперадмином
- `give_new_user_bonus(user_id, days=7)` — бонус новому юзеру через `proxy.issue_subscription`
- `check_expired()` — фоновая задача каждый час: уведомления за 3д/1д, деактивация

### `support_bot.py` — support-бот (`@TuVPNSupport_bot`)
- Тикет-система: `open` → `in_progress` → `closed`
- FAQ из хардкода: установка iOS/Android, VPN не работает, оплата, несколько устройств
- Таблицы: `support_tickets`, `support_messages`, `support_admins`
- Команды для adminов: `/tickets`, `/ticket <id>`, `/take <id>`, `/close <id>`, `/reply <id> <text>`

### `subscription_generator.py`
Собирает JSON-конфиги для Happ/V2RayN. Один конфиг на сервер.
- `build_subscription(servers, client_uuid) → list[dict]`
- Протокол: VLESS + Reality, flow `xtls-rprx-vision`
- Routing: прямой для РФ-сервисов, через VPN для заблокированных

### `routing_rules.py`
Правила маршрутизации трафика:
- `DIRECT_DOMAINS` — банки, госуслуги, маркетплейсы, РФ-сервисы, IP-определители
- `DIRECT_GEOSITE` — `private`, `category-ru`, `apple`, `microsoft`, `steam`
- `PROXY_DOMAINS` — Claude/OpenAI, Meta, Twitter, LinkedIn, Spotify, Discord, Reddit
- `PROXY_GEOSITE` — `youtube`, `telegram`, `github`, `twitch`
- `BLOCK_GEOSITE` — `category-ads`
- **Критично:** IP-определители (`ipify.org`, `ifconfig.me` и др.) идут `DIRECT` — иначе российские приложения (МАКС, Ozon Bank, Яндекс) видят VPN-IP и блокируют

### `config.py`
Читает `.env`, обязательные переменные падают через `_req()`. Структура:
- `BOT_TOKEN`, `SUPPORT_BOT_TOKEN`, `MAIN_BOT_USERNAME`
- `SUPABASE_URL`, `SUPABASE_KEY` (secret), `SUPABASE_PUBLISHABLE_KEY` (frontend)
- `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`
- `ADMIN_TG_IDS`, `ADMIN_SESSION_DAYS=7`, `ADMIN_LOGIN_TOKEN_MINUTES=10`
- `SUB_BASE_URL` = `https://sub.tuvpn.ru`
- Legacy `PANEL_*` переменные — только для `apply_referral_bonus` fallback

### `yookassa_client.py`
- `create_payment(amount, description, user_id, devices, months, email, promo_*)` → `{payment_id, confirmation_url, status}`
- `get_payment_info(payment_id)` — верификация через API ЮКассы
- `parse_webhook(body)` — разбор webhook
- `is_yookassa_ip(ip)` — проверка IP-адресов ЮКассы
- Чек НЕ передаётся в ЮКассу — Максим формирует вручную в «Мой налог»

### `server_installer.py`
Автоматическая установка 3X-UI + Reality на новый VPN-сервер через SSH.
Вызывается через `/admin-api/install_server` из панели.

### `monitor_daemon.py`
Фоновый демон: пингует серверы, пишет в `server_health`.

---

## База данных (Supabase)

### Основные таблицы

| Таблица | Описание |
|---------|---------|
| `users` | Зарегистрированные юзеры. Поля: `user_id`, `username`, `first_name`, `last_name`, `referrer_id`, `client_uuid`, `bonus_days`, `campaign_code` |
| `subscriptions` | Подписки. Поля: `user_id`, `devices`, `status` (active/inactive), `sub_url`, `started_at`, `expires_at`, `notified_3d`, `notified_1d`, `notified_expired` |
| `payments` | Платежи. Поля: `user_id`, `provider`, `provider_payment_id`, `amount`, `currency`, `status`, `devices`, `months`, `metadata`, `paid_at`, `receipt_url`, `receipt_status`, `campaign_code` |
| `servers` | VPN-серверы. Поля: `code`, `country_name`, `country_flag`, `country_code`, `panel_url`, `panel_login`, `panel_password`, `api_token` (v3), `inbound_id`, `server_ip`, `server_port`, `public_key`, `short_id`, `sni`, `flow`, `fingerprint`, `is_active`, `sort_order` |
| `user_devices` | Устройства. Поля: `user_id`, `client_uuid`, `device_name`, `device_type` (ios/android/pc), `hwid`, `device_model`, `device_os`, `os_version`, `user_agent`, `ip_address`, `is_active`, `connected_at`, `last_seen` |
| `support_tickets` | Тикеты. Статусы: `open`, `in_progress`, `closed` |
| `support_messages` | Сообщения тикетов. `sender_type`: `user`/`admin`/`system` |
| `support_admins` | Операторы поддержки. `role_id`, `added_permissions`, `removed_permissions`, `is_active` |
| `admin_sessions` | Сессии админки. `session_token`, `tg_id`, `expires_at`, `is_revoked` |
| `admin_login_attempts` | Попытки входа. `login_token`, `status` (pending/confirmed/rejected/expired) |
| `admin_roles` | Роли RBAC. `name`, `permissions` (json array) |
| `referrals` | `referrer_id`, `referred_id` |
| `promocodes` | `code`, `type` (percent/days), `value`, `max_uses`, `uses_count`, `is_active` |
| `promocode_uses` | Использования промокодов |
| `campaigns` | UTM-кампании. `code`, `name`, `bonus_days`, `welcome_text`, `cost`, `is_active` |
| `campaign_clicks` | Клики по кампаниям |
| `server_health` | История проверок доступности серверов |
| `server_installations` | История установок серверов |
| `broadcasts` | История рассылок |
| `system_logs` | Логи событий через `log_event()` |
| `ip_geo` | Кэш геолокации IP |
| `watchlist` | VIP-пользователи для мониторинга |
| `finance_sources` | Источники финансирования |
| `finance_expenses` | Расходы |
| `finance_investments` | Инвестиции |
| `finance_planned` | Плановые расходы |

### Паттерны запросов
```python
sb = create_client(SUPABASE_URL, SUPABASE_KEY)  # всегда переменная sb

# Активные серверы (стандартный запрос)
sb.table("servers").select("*").eq("is_active", True).order("sort_order").execute()

# Активная подписка юзера
sb.table("subscriptions").select("*").eq("user_id", uid).eq("status", "active").execute()

# Устройства юзера активные за последние 7 дней
sb.table("user_devices").select("*").eq("user_id", uid).eq("is_active", True).gte("last_seen", cutoff).execute()
```

---

## 3X-UI API

### v2 (legacy, cookie-сессия)
```python
session, server = xui_session(server)
session.post(f"{url}/panel/api/inbounds/addClient", json=payload)
session.post(f"{url}/panel/api/inbounds/updateClient/{uuid}", json=payload)
```
Payload содержит `settings` как JSON-строку с массивом `clients`.

### v3 (новый, Bearer-токен)
Используется если `server["api_token"]` заполнен.
```python
# Добавить клиента
POST /panel/api/clients/add
{"inboundIds": [iid], "client": {"id": uuid, "email": "user_<uid>", "limitIp": N, "expiryTime": ms, "enable": true, "flow": "xtls-rprx-vision"}}

# Обновить клиента — читаем весь inbound, патчим нужного клиента, отправляем обратно
GET /panel/api/inbounds/get/{iid}
POST /panel/api/inbounds/update/{iid}

# Удалить
DELETE /panel/api/clients/{uuid}
```

**Идемпотентность:** перед `addClient` в v3 проверяется существование UUID через `xui_v3_list_uuids`. Если уже есть — не добавляем повторно.

---

## Подписки — ключевые потоки

### Выдача подписки `issue_subscription(uid, devices, days)`
1. Проверить `bonus_days` у юзера в `users`
2. Найти существующий UUID через `get_existing_client(uid)` — переиспользуем UUID при всех сценариях (триал→покупка, продление, возврат через N дней)
3. Посчитать новую дату истечения: базовая = max(текущая expires_at, now) + days + bonus_days
4. Для каждого активного сервера: `xui_update_client_on_server` (или `add` если action=created)
5. Обновить/создать запись в `subscriptions` + обнулить `bonus_days`
6. `sub_url` формат: `https://sub.tuvpn.ru/sub/{client_uuid}`

### Отслеживание устройств `track_device(uuid, ip, ua, hwid, ...)`
Устройство идентифицируется по: HWID (приоритет) → нормализованный User-Agent.
- Игнорируем `TelegramBot`, `TwitterBot`, `AuditBot` (preview-запросы)
- Знакомое устройство (совпал device_key) → обновляем `last_seen`
- Тот же IP за последние 30 минут → `same_ip_refresh` (не считаем новым)
- Новое устройство → проверяем лимит по активным за последние 7 дней (`DEVICE_ACTIVITY_WINDOW_DAYS`)
- Лимит превышен → 403
- Ошибка БД → разрешаем (lose mode)

### Happ UA-формат
```
Happ/3.20.4/Android/17782185961531805598
Happ/4.9.0/ios/2605051739563
```
Нормализация: берём первые 4 части через `/`. Последний токен — стабильный device-id.

---

## Платежи

### ЮКасса
1. `bot.py`: `yookassa_client.create_payment(...)` → `confirmation_url` → кнопка «Оплатить»
2. Webhook `POST /yookassa/webhook`:
   - Проверка IP ЮКассы
   - Верификация через `get_payment_info(payment_id)` — сверка status/amount/user_id
   - Idempotency: если payment уже `succeeded` в БД — пропускаем
   - Проверка суммы: paid >= expected_price × 0.5 (защита от подмены тарифа)
   - `issue_subscription(uid, devices, days)` + применение промокода + реферальный бонус
   - Уведомление юзера через бот, уведомление суперадмина (784871620)

### Telegram Stars
1. `bot.send_invoice(...)` с `currency="XTR"`
2. `@dp.pre_checkout_query()` → `answer_pre_checkout_query(ok=True)`
3. `@dp.message(lambda m: m.successful_payment is not None)` → `issue_subscription` + уведомления

### Тарифы (рублей)
```python
PRICES = {
    1: {"1": 149, "3": 399, "12": 1399},
    2: {"1": 249, "3": 649, "12": 2299},
    5: {"1": 599, "3": 1599, "12": 5499},
}
# DAYS: "1"→30, "3"→90, "12"→365
```

---

## Система аутентификации AdminPanel

### Вход
1. Фронт: `POST /admin-api/auth/start` → `{login_token, deeplink}`
2. Deeplink открывается в Telegram: `@MaxArtVPN_bot?start=login_admin_<token>`
3. Бот отправляет уведомление суперадмину (784871620) с кнопками «Разрешить»/«Отклонить»
4. Суперадмин нажимает «Разрешить» → запись в `admin_login_attempts` обновляется на `confirmed`, создаётся `admin_sessions`
5. Фронт polling: `GET /admin-api/auth/poll?token=<token>` → при `confirmed` получает cookie `admin_session`

### RBAC
- `SUPERADMIN_ID = 784871620` → все права автоматически
- Остальные: роль (`admin_roles.permissions`) + индивидуальные `added_permissions` − `removed_permissions`
- `require_perm("perm_name")` в начале endpoint → 403 если нет права
- Middleware `before_request` проверяет cookie на всех `/admin-api/*` кроме `/auth/*`

---

## Рассылки (Broadcast)

Аудитории:
- `all` — все юзеры
- `active` — активная подписка
- `inactive` — нет активной подписки
- `expires_6h` — подписка истекает через 6 часов
- `expired_unpaid_14d` — истекла за 14 дней, не платили
- `utm_no_device` — пришли по UTM, не подключились
- `single` / `custom_list` — один или список user_id

Опционально: `bonus_days` — начислить дни всем доставленным.

---

## Конвенции кода

1. **Supabase-клиент всегда называется `sb`:**
   ```python
   sb = create_client(SUPABASE_URL, SUPABASE_KEY)
   ```

2. **Комментарии в коде — на русском языке.** Стиль: короткие поясняющие комментарии, не описательные.

3. **Секреты — только через `.env`.** Новые переменные: добавить в `config.py` через `_req()` или `_opt()`, добавить в `.env.example`.

4. **Ошибки падают громко** (`_req()` кидает `RuntimeError`). Не глотать ошибки молча.

5. **Новые серверы** добавляются через Supabase таблицу `servers`, не через ENV.

6. **3X-UI v3 vs v2:** если у сервера заполнен `api_token` — используем v3 API. Иначе v2 через cookie.

7. **Frontend** (admin panel) хранится прямо на сервере в `/var/www/html/`. Это `app.js`, `index.html`, `styles.css`. Деплой: `scp` или редактирование прямо на сервере.

8. **Подписки** всегда привязаны к конкретному UUID, UUID переиспользуется при продлении/возврате.

---

## Deploy — алгоритм выполнения задач

### Изменение в backend (`proxy.py`)
```bash
# 1. Редактируем локально
# 2. Копируем на сервер
scp proxy.py app:/root/tuvpn/proxy.py
# 3. Перезапускаем сервис
ssh app systemctl restart tuvpn-proxy
# 4. Проверяем логи
ssh app journalctl -u tuvpn-proxy -f --no-pager -n 50
```

### Изменение в bot.py
```bash
scp bot.py app:/root/tuvpn/bot.py
ssh app systemctl restart tuvpn-bot
ssh app journalctl -u tuvpn-bot -f --no-pager -n 50
```

### Изменение в support_bot.py
```bash
scp support_bot.py app:/root/tuvpn/support_bot.py
ssh app systemctl restart tuvpn-support
```

### Изменение в routing_rules.py / subscription_generator.py
Эти файлы импортируются proxy.py и bot.py → рестарт соответствующих сервисов.

### Изменение в admin-panel (app.js, index.html, styles.css)
```bash
scp app.js app:/var/www/html/app.js
# nginx сразу отдаёт новый файл, рестарт не нужен
```

### Изменение в config.py
```bash
scp config.py app:/root/tuvpn/config.py
ssh app systemctl restart tuvpn-proxy tuvpn-bot tuvpn-support
```

### Добавление нового VPN-сервера
1. Вставить запись в таблицу `servers` в Supabase (через панель или скрипт)
2. Либо использовать `/admin-api/install_server` из панели (автоматическая установка)
3. При активации сервера — `backfill_server_clients` стартует автоматически в фоне

---

## Диагностика проблем

### Пользователь не может подключиться (403)
```bash
# В admin-панели: User Audit → user_id → проверить server_checks
# Или через API:
curl -b "admin_session=TOKEN" https://admin.tuvpn.ru/admin-api/user_audit/<uid>

# Если клиент не найден на сервере — user_fix:
curl -X POST -b "..." https://admin.tuvpn.ru/admin-api/user_fix/<uid>/<server_id>
```

### Сервер недоступен
```bash
# Проверить 3X-UI панель напрямую
curl -k https://<server_ip>:<panel_port>/

# Через API (тест соединения):
POST /admin-api/servers/<id>/test
```

### Лимит устройств — сброс
```bash
# Деактивировать устройство через API:
DELETE /admin-api/user_devices/<uid>/<device_id>

# Или через Generic DB proxy:
PATCH /admin-api/db/user_devices?id=eq.<device_id>
{"is_active": false}
```

### Подписка не выдалась после оплаты
```bash
# Проверить webhook-логи:
ssh app journalctl -u tuvpn-proxy -f | grep "yookassa"

# Вручную выдать через admin-панель:
POST /admin-api/grant
{"user_id": <uid>, "extend_days": 30, "set_devices": 1}
```

---

## Стиль работы с Максимом

- Максим — технический владелец и суперадмин (`tg_id: 784871620`), разбирается в деталях
- Предпочитает конкретику: "сделать X через Y в файле Z" лучше чем общие рассуждения
- Если задача неоднозначна — уточнить одним чётким вопросом, не несколькими
- **Все ответы только на русском языке** — сообщения, вопросы, отчёты, описания команд, комментарии к коду. Без исключений.
- Не нужно объяснять очевидные вещи (что такое webhook, как работает asyncio и т.д.)
- Backup-файлы на сервере (`.before_*`) — артефакты предыдущих деплоев, не трогать
- При любом деплое — сначала проверить логи, не считать задачу выполненной без проверки

---

## Структура URL подписки

```
https://sub.tuvpn.ru/sub/{client_uuid}
```

Обрабатывается `GET /sub/<client_uuid>` в `proxy.py`. Возвращает JSON-массив конфигов.
Заголовки ответа: `profile-title`, `profile-update-interval: 1`, `subscription-userinfo`, `announce`.

## Бот-команды пользователей

- `/start [ref_id|campaign_code|login_admin_TOKEN]` — регистрация, реферал, UTM, вход в панель
- `/menu` — главное меню
- `/status` — статус подписки
- Callback: `connect`, `buy`, `profile`, `howto`, `referral`, `channel`, `about`, `support`, `back`
- Callback: `devices_1/2/5`, `period_N_M`, `pay_card_N_M`, `pay_stars_N_M`
- Callback: `have_promo`, `no_promo`, `confirm_buy`, `cancel_buy`
- Callback: `connection_link`, `my_devices`, `add_devices`, `howto_ios`, `howto_android`
