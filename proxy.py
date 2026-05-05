import sys
sys.path.insert(0, '/root')
from flask import Flask, request, jsonify, Response
import requests, json, uuid, base64
from datetime import datetime, timedelta
from config import PANEL_URL, PANEL_USER, PANEL_PASS, INBOUND_ID, SERVER_IP
import urllib3
urllib3.disable_warnings()

app = Flask(__name__)
PUBLIC_KEY = "9q2JxVMnpr1nvhK407R0ymy5k-W_tyE_iEvSLJTXWg8"
SHORT_ID = "d1a247d5a8"

def get_client_expire(client_uuid):
    try:
        s = requests.Session()
        s.verify = False
        s.post(f"{PANEL_URL}/login", json={"username": PANEL_USER, "password": PANEL_PASS})
        r = s.get(f"{PANEL_URL}/xui/API/inbounds/list")
        data = r.json()
        inbound = data["obj"][0]
        settings = json.loads(inbound["settings"])
        for client in settings.get("clients", []):
            if client.get("id") == client_uuid:
                return client.get("expiryTime", 0) // 1000
    except:
        pass
    return 0

@app.route('/sub/<client_uuid>')
def subscription(client_uuid):
    vless = (
        f"vless://{client_uuid}@{SERVER_IP}:443"
        f"?type=tcp&security=reality"
        f"&pbk={PUBLIC_KEY}"
        f"&fp=chrome&sni=www.bing.com"
        f"&sid={SHORT_ID}&spx=%2F"
        f"&flow=xtls-rprx-vision"
        f"#\U0001f1eb\U0001f1ee Finland"
    )
    encoded = base64.b64encode(vless.encode()).decode()
    expire_ts = get_client_expire(client_uuid)

    announcement_b64 = "4pqg77iPINCd0LUg0YDQsNCx0L7RgtCw0LXRgj8g0J3QsNC20LzQuCDwn5SEINC4INCy0YvQsdC10YDQuCDQtNGA0YPQs9GD0Y4g0LvQvtC60LDRhtC40Y4uIPCfk4Ug0J/RgNC+0LTQu9C10LLQsNC5INC30LDRgNCw0L3QtdC1IOKAlCBUZWxlZ3JhbSDQt9Cw0LzQtdC00LvRj9GO0YIh"

    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "profile-title": "TuVPN",
        "profile-update-interval": "6",
        "support-url": "https://t.me/MaxArtVPN_bot",
        "subscription-userinfo": f"upload=0; download=0; total=0; expire={expire_ts}",
        "announce": "base64:" + announcement_b64,
    }
    return Response(encoded, headers=headers)

@app.route('/admin-api/grant', methods=['POST', 'OPTIONS'])
def grant():
    if request.method == 'OPTIONS':
        resp = app.make_default_options_response()
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        return resp
    try:
        data = request.json
        uid = data['user_id']
        devices = data['devices']
        days = data['days']
        s = requests.Session()
        s.verify = False
        s.post(f"{PANEL_URL}/login", json={"username": PANEL_USER, "password": PANEL_PASS})
        client_uuid = str(uuid.uuid4())
        expire_ms = int((datetime.now() + timedelta(days=days)).timestamp() * 1000)
        ts = int(datetime.now().timestamp())
        payload = {
            "id": INBOUND_ID,
            "settings": json.dumps({"clients": [{
                "id": client_uuid,
                "email": f"user_{uid}_{ts}",
                "limitIp": devices,
                "totalGB": 0,
                "expiryTime": expire_ms,
                "enable": True,
                "flow": "xtls-rprx-vision"
            }]})
        }
        r = s.post(f"{PANEL_URL}/panel/api/inbounds/addClient", json=payload)
        result = r.json()
        if result.get("success"):
            sub_url = f"https://{SERVER_IP}:8443/sub/{client_uuid}"
            resp = jsonify({"success": True, "uuid": client_uuid, "sub_url": sub_url})
        else:
            resp = jsonify({"success": False, "error": str(result)})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    except Exception as e:
        resp = jsonify({"success": False, "error": str(e)})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000)
