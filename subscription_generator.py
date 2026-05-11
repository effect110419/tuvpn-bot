"""
TuVPN — генератор JSON-конфигов для Happ Plus / V2RayN.

Возвращает массив JSON-конфигов (по одному на каждый активный сервер) —
формат совместим с Happ Plus (тот же что у ONEOK и других серьёзных VPN).
"""
import json
from routing_rules import (
    DIRECT_DOMAINS, DIRECT_GEOSITE, DIRECT_GEOIP,
    PROXY_DOMAINS, PROXY_GEOSITE,
    BLOCK_GEOSITE, DNS_HOSTS,
)


def build_server_config(server: dict, client_uuid: str) -> dict:
    """
    Собирает один JSON-конфиг для одного сервера (одной страны).

    server — запись из таблицы servers (dict с keys: country_flag, country_name,
             server_ip, server_port, public_key, short_id, sni, flow, fingerprint).
    client_uuid — UUID пользователя в 3X-UI.
    """
    remarks = f"{server['country_flag']} {server['country_name']}"

    return {
        "remarks": remarks,
        "dns": _build_dns(),
        "inbounds": _build_inbounds(),
        "outbounds": _build_outbounds(server, client_uuid),
        "routing": _build_routing(),
        "policy": _build_policy(),
        "stats": {},
        "log": {"loglevel": "warning"},
    }


def build_subscription(servers: list, client_uuid: str) -> list:
    """
    Главная функция: собирает массив конфигов для всех активных серверов.
    Возвращает list[dict] — потом сериализуется в JSON и отдаётся клиенту.
    """
    return [build_server_config(s, client_uuid) for s in servers]


# ============================================================
# Внутренние строители
# ============================================================

def _build_dns() -> dict:
    return {
        "hosts": dict(DNS_HOSTS),
        "queryStrategy": "UseIPv4",
        "servers": [
            "https://8.8.8.8/dns-query",
            {
                "address": "https://8.8.8.8/dns-query",
                "domains": PROXY_GEOSITE,
            },
            {
                "address": "https://77.88.8.8/dns-query",
                "domains": DIRECT_GEOSITE + DIRECT_DOMAINS,
            },
        ],
    }


def _build_inbounds() -> list:
    return [
        {
            "tag": "socks",
            "listen": "127.0.0.1",
            "port": 10808,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True, "userLevel": 8},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
        },
        {
            "tag": "http",
            "listen": "127.0.0.1",
            "port": 10809,
            "protocol": "http",
            "settings": {"userLevel": 8},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
        },
    ]


def _build_outbounds(server: dict, client_uuid: str) -> list:
    return [
        {
            "tag": "proxy",
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": server["server_ip"],
                    "port": int(server["server_port"]),
                    "users": [{
                        "id": client_uuid,
                        "encryption": "none",
                        "flow": server.get("flow") or "xtls-rprx-vision",
                    }],
                }],
            },
            "streamSettings": {
                "network": "tcp",
                "security": "reality",
                "tcpSettings": {},
                "realitySettings": {
                    "fingerprint": server.get("fingerprint") or "chrome",
                    "publicKey": server["public_key"],
                    "serverName": server.get("sni") or "www.bing.com",
                    "shortId": server["short_id"],
                },
            },
        },
        {"tag": "direct", "protocol": "freedom"},
        {"tag": "block", "protocol": "blackhole"},
        {"tag": "dns-out", "protocol": "dns", "proxySettings": {"tag": "proxy"}},
    ]


def _build_routing() -> dict:
    rules = []
    # 1. DNS — через VPN
    rules.append({"outboundTag": "dns-out", "port": "53"})
    # 2. Блок
    if BLOCK_GEOSITE:
        rules.append({"outboundTag": "block", "domain": BLOCK_GEOSITE})
    # 3. Конкретные DNS-серверы
    rules.append({"outboundTag": "direct", "ip": ["77.88.8.8"]})
    rules.append({"outboundTag": "proxy", "ip": ["8.8.8.8"]})
    # 4. DIRECT — российские домены (явные)
    if DIRECT_DOMAINS:
        rules.append({"outboundTag": "direct", "domain": DIRECT_DOMAINS})
    # 5. DIRECT — категории geosite
    if DIRECT_GEOSITE:
        rules.append({"outboundTag": "direct", "domain": DIRECT_GEOSITE})
    # 6. PROXY — явные домены (Claude, 18+)
    if PROXY_DOMAINS:
        rules.append({"outboundTag": "proxy", "domain": PROXY_DOMAINS})
    # 7. PROXY — категории geosite (YouTube, Telegram, заблокированные в РФ)
    if PROXY_GEOSITE:
        rules.append({"outboundTag": "proxy", "domain": PROXY_GEOSITE})
    # 8. DIRECT — приватные/локальные IP
    if DIRECT_GEOIP:
        rules.append({"outboundTag": "direct", "ip": DIRECT_GEOIP})
    return {"domainStrategy": "IPIfNonMatch", "rules": rules}


def _build_policy() -> dict:
    return {
        "levels": {
            "8": {
                "connIdle": 300,
                "downlinkOnly": 1,
                "handshake": 4,
                "uplinkOnly": 1,
            }
        },
        "system": {
            "statsOutboundDownlink": True,
            "statsOutboundUplink": True,
        },
    }


if __name__ == "__main__":
    # Тестовый запуск с фейковым сервером
    test_server = {
        "country_flag": "🇫🇮",
        "country_name": "Финляндия",
        "server_ip": "89.125.53.210",
        "server_port": 443,
        "public_key": "9q2JxVMnpr1nvhK407R0ymy5k-W_tyE_iEvSLJTXWg8",
        "short_id": "d1a247d5a8",
        "sni": "www.bing.com",
        "flow": "xtls-rprx-vision",
        "fingerprint": "chrome",
    }
    test_uuid = "85e168a1-6d41-4a02-a9a6-0ec46d3e8f0f"
    result = build_subscription([test_server], test_uuid)
    print(json.dumps(result, indent=2, ensure_ascii=False))
