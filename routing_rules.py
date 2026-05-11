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
