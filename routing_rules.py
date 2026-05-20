"""
TuVPN — правила маршрутизации трафика.

ВАЖНО: используем только проверенные geosite-категории.
Категории отсутствующие в стандартном geosite.dat (meta, openai, torrent и т.д.)
заменены на ручные domain: правила.
"""

DIRECT_DOMAINS = [
    # === БАНКИ ===
    "domain:sberbank.ru", "domain:sber.ru", "domain:sberbank-online.ru",
    "domain:sbrf.ru", "domain:sbi.sberbank.ru",
    "domain:tinkoff.ru", "domain:tbank.ru", "domain:ftc.ru",
    "domain:vtb.ru", "domain:vtb24.ru", "domain:vtbcapital.com",
    "domain:alfabank.ru", "domain:alfabank.com",
    "domain:raiffeisen.ru", "domain:raif.ru",
    "domain:gazprombank.ru", "domain:gpb.ru",
    "domain:open.ru",
    "domain:rshb.ru",
    "domain:sovcombank.ru", "domain:halvacard.ru",
    "domain:ozonbank.ru", "domain:finance.ozon.ru",
    "domain:rncb.ru",
    "domain:wbbank.ru",
    "domain:yoomoney.ru", "domain:money.yandex.ru",
    "domain:qiwi.ru", "domain:qiwi.com",
    "domain:sbp.nspk.ru", "domain:nspk.ru", "domain:mironline.ru",
    "domain:cbr.ru",
    # === ГОС ===
    "domain:gosuslugi.ru", "domain:esia.gosuslugi.ru",
    "domain:nalog.ru", "domain:lkfl2.nalog.ru", "domain:lknpd.nalog.ru",
    "domain:mfc.ru",
    "domain:emias.info", "domain:emias.mos.ru",
    "domain:mos.ru",
    "domain:pochta.ru", "domain:russianpost.ru",
    "domain:rzd.ru", "domain:rzd-bonus.ru",
    "domain:aeroflot.ru", "domain:s7.ru", "domain:pobeda.aero", "domain:utair.ru",
    "domain:fssp.gov.ru", "domain:gibdd.ru",
    # === МАРКЕТПЛЕЙСЫ ===
    "domain:wildberries.ru", "domain:wb.ru", "domain:wbstatic.net",
    "domain:ozon.ru",
    "domain:market.yandex.ru", "domain:yandex.ru", "domain:ya.ru", "domain:yandex.com",
    "domain:avito.ru",
    "domain:aliexpress.ru",
    "domain:sbermarket.ru", "domain:sbermegamarket.ru", "domain:samokat.ru",
    "domain:delivery-club.ru", "domain:eda.yandex.ru", "domain:kuper.ru",
    # === СОЦ.СЕТИ И КОНТЕНТ РФ ===
    "domain:vk.com", "domain:vk.ru",
    "domain:ok.ru",
    "domain:max.ru", "domain:oneme.ru",
    # === VPN-DETECT FIX 2026-05 ===
    # Полная инфраструктура МАКС / VK (мессенджер дёргает много поддоменов)
    "domain:platform-api.max.ru", "domain:api.oneme.ru",
    "domain:okcdn.ru", "domain:calls.okcdn.ru",
    "domain:mycdn.me", "domain:userapi.com",
    "domain:vk-cdn.net", "domain:vkuser.net", "domain:vkuseraudio.net",
    "domain:vk-portal.net", "domain:vkcdn.ru",
    # === IP-ОПРЕДЕЛИТЕЛИ — КРИТИЧНО ===
    # Российские приложения (МАКС, Озон Банк, Яндекс) проверяют внешний IP
    # через эти сервисы. Если идут через VPN → видят зарубежный IP → "у вас VPN".
    # Направляя DIRECT, приложение видит реальный российский IP.
    "domain:ipify.org", "domain:api.ipify.org", "domain:api64.ipify.org",
    "domain:ifconfig.me", "domain:ifconfig.co", "domain:ifconfig.io",
    "domain:checkip.amazonaws.com", "domain:checkip.dyndns.org",
    "domain:myip.com", "domain:api.myip.com",
    "domain:ipinfo.io", "domain:ip-api.com", "domain:pro.ip-api.com",
    "domain:icanhazip.com", "domain:wtfismyip.com",
    "domain:ipecho.net", "domain:myexternalip.com",
    "domain:whatismyipaddress.com", "domain:whatismyip.com",
    "domain:2ip.ru", "domain:2ip.io", "domain:ip.me",
    "domain:ipaddress.com", "domain:iplogger.org", "domain:iplogger.ru",
    "domain:geoplugin.net", "domain:freegeoip.app", "domain:ipapi.co",
    "domain:getip.pro", "domain:ipwho.is", "domain:ipwhois.app",
    "domain:seeip.org", "domain:api.seeip.org",
    "domain:ipdata.co", "domain:ipgeolocation.io",
    "domain:rutube.ru",
    "domain:yappy.media",
    "domain:dzen.ru", "domain:zen.yandex.ru",
    "domain:tenchat.ru",
    "domain:livejournal.com",
    "domain:habr.com", "domain:habrahabr.ru",
    "domain:pikabu.ru",
    "domain:kinopoisk.ru", "domain:hd.kinopoisk.ru",
    "domain:ivi.ru",
    "domain:okko.tv",
    "domain:wink.rt.ru",
    "domain:premier.one",
    "domain:music.yandex.ru", "domain:music.vk.com",
    # === EXTENDED RU DOMAINS 2026-05 ===
    # Госуслуги — расширение (главный домен уже выше, эти строки для надёжности)
    "domain:epgu.gosuslugi.ru", "domain:do.gosuslugi.ru",
    "domain:docs.gosuslugi.ru", "domain:cabinet.gosuslugi.ru",
    "domain:lk.gosuslugi.ru", "domain:web.gosuslugi.ru",
    "domain:pos.gosuslugi.ru",
    "domain:oms.ru", "domain:vetrf.ru", "domain:mvd.ru",
    "domain:cdek.ru", "domain:dpd.ru", "domain:boxberry.ru",
    "domain:rusprofile.ru", "domain:nalog.gov.ru",
    # Ozon — расширение
    "domain:ozby.ru", "domain:ozon.travel", "domain:ozon-cdn.com",
    "domain:ozon.tech", "domain:o3.ru",
    # Яндекс сервисы — полное покрытие (yandex.ru уже есть = ловит все *.yandex.ru,
    # но дополнительно прописываем альтернативные домены и CDN)
    "domain:yandex.net", "domain:ya.cc",
    "domain:taxi.yandex.ru", "domain:go.yandex",
    "domain:maps.yandex.ru", "domain:disk.yandex.ru",
    "domain:cloud.yandex.ru", "domain:cloud.yandex.com",
    "domain:practicum.yandex.ru",
    "domain:kassa.yandex.ru", "domain:metrika.yandex.ru",
    "domain:direct.yandex.ru", "domain:webmaster.yandex.ru",
    "domain:dialogs.yandex.ru", "domain:passport.yandex.ru",
    "domain:id.yandex.ru", "domain:mail.yandex.ru",
    "domain:afisha.yandex.ru", "domain:plus.yandex.ru",
    "domain:auto.ru", "domain:realty.yandex.ru",
    # T2 Mobile (бывший Tele2)
    # T2 EXPLICIT SUBDOMAINS
    "domain:t2.ru", "domain:tele2.ru",
    "domain:auth.t2.ru", "domain:appseller.t2.ru", "domain:appseller.tele2.ru",
    "domain:lk.t2.ru", "domain:msk.t2.ru",
    # Фастфуд / доставка
    "domain:rostics.ru", "domain:burgerkingrus.ru",
    "domain:dodopizza.ru", "domain:dodois.io",
    "domain:tanuki.ru", "domain:papajohns.ru",
    "domain:macdonalds.ru", "domain:vkusno-i-tochka.ru",
    "domain:teremok.ru", "domain:shokoladnitsa.ru",
    # Мобильные операторы
    "domain:mts.ru", "domain:mts-bank.ru", "domain:mtsbank.ru",
    "domain:mts.tv", "domain:mtsmusic.ru",
    "domain:megafon.ru", "domain:megafon.tv",
    "domain:beeline.ru", "domain:beeline.tv",
    "domain:rt.ru",
    # Каршеринг и такси
    "domain:delimobil.ru", "domain:belkacar.ru",
    "domain:citydrive.ru", "domain:carsharing.ru",
    # Сбер услуги
    "domain:sberprime.ru", "domain:sberlogistics.ru",
    "domain:sberhealth.ru", "domain:sberauto.com",
    "domain:sbol.ru", "domain:sber.ru",
    "domain:sberdevices.ru", "domain:salutejazz.ru",
    "domain:sberid.ru", "domain:sberbusiness.live",
    # Тинькофф расширенно
    "domain:tinkoff.travel", "domain:tinkoff.club",
    "domain:tinkoff-mobile.ru", "domain:tinkoffjournal.ru",
    # Стриминги и видео РФ (для надёжности, многие уже есть)
    "domain:start.ru", "domain:more.tv", "domain:kion.ru",
    "domain:smotrim.ru", "domain:1tv.ru", "domain:ren.tv",
    # СМИ РФ
    "domain:ria.ru", "domain:tass.ru", "domain:rbc.ru",
    "domain:lenta.ru", "domain:kommersant.ru",
    "domain:gazeta.ru", "domain:vedomosti.ru",
    "domain:meduza.io",
    # Прочее популярное
    "domain:hh.ru", "domain:superjob.ru", "domain:rabota.ru",
    "domain:cian.ru", "domain:irr.ru",
    "domain:drom.ru",
    "domain:2gis.ru", "domain:zoon.ru",
]

# Только проверенные категории geosite (точно есть в стандартной базе)
DIRECT_GEOSITE = [
    "geosite:private",
    "geosite:category-ru",
    "geosite:apple",
    "geosite:microsoft",
    "geosite:steam",
]

# Через VPN — заменим неподтверждённые geosite на ручные domain:
PROXY_DOMAINS = [
    # Claude / AI
    "domain:claude.ai", "domain:anthropic.com",
    "domain:openai.com", "domain:chatgpt.com", "domain:chat.openai.com",
    # Meta (раньше было geosite:meta — теперь руками)
    "domain:facebook.com", "domain:fbcdn.net", "domain:fb.com",
    "domain:instagram.com", "domain:cdninstagram.com",
    "domain:whatsapp.com", "domain:whatsapp.net",
    "domain:threads.net",
    # Twitter / X
    "domain:twitter.com", "domain:x.com", "domain:t.co", "domain:twimg.com",
    # LinkedIn
    "domain:linkedin.com", "domain:licdn.com",
    # Spotify
    "domain:spotify.com", "domain:scdn.co",
    # Discord (если geosite:discord не работает)
    "domain:discord.com", "domain:discord.gg", "domain:discordapp.com",
    "domain:discordapp.net", "domain:discord.media",
    # Reddit
    "domain:reddit.com", "domain:redditstatic.com", "domain:redditmedia.com",
    "domain:redd.it",
    # 18+
    "domain:pornhub.com", "domain:xvideos.com",
    "domain:redtube.com", "domain:youporn.com",
]

# Только проверенные категории
PROXY_GEOSITE = [
    "geosite:youtube",
    "geosite:telegram",
    "geosite:github",
    "geosite:twitch",
]

# Только проверенная категория для блокировки
BLOCK_GEOSITE = [
    "geosite:category-ads",
]

DNS_HOSTS = {
    "lkfl2.nalog.ru": "213.24.64.175",
    "lknpd.nalog.ru": "213.24.64.181",
}

DIRECT_GEOIP = ["geoip:private"]
