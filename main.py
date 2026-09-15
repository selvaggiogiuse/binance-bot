# -*- coding: utf-8 -*-
# V95 TELEGRAM ONLY - TEST MESSAGGI - Cancella tutto il resto
from flask import Flask, jsonify, request
import os, requests, time, threading
from datetime import datetime

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

PAIRS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "ORO": "PAXGUSDT"}
VERSION = "V95 TELEGRAM ONLY - TEST MESSAGGI"
COOLDOWN = 60
LAST_TELEGRAM = {}

def rome_now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Rome"))
    except:
        from datetime import timezone, timedelta
        return datetime.now(timezone.utc) + timedelta(hours=2)

def get_price(name):
    sym = PAIRS.get(name, "BTCUSDT")
    for url in [
        f"https://data-api.binance.vision/api/v3/ticker/price?symbol={sym}",
        f"https://api.binance.com/api/v3/ticker/price?symbol={sym}"
    ]:
        try:
            r = requests.get(url, timeout=5, headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code == 200:
                return float(r.json()['price']), "BINANCE"
        except:
            continue
    fallback = {"BTC": 75000.0, "ETH": 2500.0, "ORO": 2650.0}
    return fallback.get(name, 2500.0), "FALLBACK"

def send_tg(coin, signal, price, force=False, text_extra=""):
    global LAST_TELEGRAM
    if not TELEGRAM_ENABLED:
        return {"ok": False, "error": "no token - controlla TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID su Render > Environment"}
    now = time.time()
    key = f"{coin}_TEST"
    if not force and key in LAST_TELEGRAM and now - LAST_TELEGRAM[key] < COOLDOWN:
        return {"ok": False, "error": f"cooldown {int(COOLDOWN - (now - LAST_TELEGRAM[key]))}s"}
    
    emoji = "🚀" if signal == "COMPRA" else "🔻" if signal == "VENDI" else "🧪"
    msg = f"""{emoji} *{signal} {coin} TEST* V95 TELEGRAM ONLY

💰 Price: ${price:.2f}
⏰ {rome_now().strftime('%d/%m %H:%M:%S')}
🤖 {VERSION}
{text_extra}

✅ Se ricevi questo, Telegram funziona - poi rimettiamo il resto del codice"""

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10
        )
        data = r.json()
        if r.status_code == 200 and data.get("ok"):
            LAST_TELEGRAM[key] = now
            return {"ok": True, "sent": True, "price": price}
        else:
            return {"ok": False, "error": f"Telegram API error: {data}", "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.route("/")
def home():
    return f"""
    <h1>{VERSION}</h1>
    <p>TELEGRAM_ENABLED: {TELEGRAM_ENABLED}</p>
    <p>TOKEN presente: {bool(TELEGRAM_BOT_TOKEN)} | CHAT_ID presente: {bool(TELEGRAM_CHAT_ID)}</p>
    <p>Ora: {rome_now()}</p>
    <hr>
    <a href="/api/telegram_config"><button>1. Controlla Config Telegram</button></a><br><br>
    <a href="/api/telegram_test"><button>2. Test Telegram BTC COMPRA</button></a><br><br>
    <a href="/api/force_telegram"><button>3. Forza Telegram per tutti (BTC/ETH/ORO)</button></a><br><br>
    <a href="/api/send_msg?text=Ciao+test+custom"><button>4. Manda messaggio custom</button></a>
    <hr>
    <p>Quando ricevi messaggi, rimettiamo il codice completo V94.</p>
    """

@app.route("/api/telegram_config")
def tg_config():
    return jsonify({
        "version": VERSION,
        "enabled": TELEGRAM_ENABLED,
        "has_token": bool(TELEGRAM_BOT_TOKEN),
        "has_chat_id": bool(TELEGRAM_CHAT_ID),
        "token_len": len(TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else 0,
        "chat_id": TELEGRAM_CHAT_ID[:4]+"****" if TELEGRAM_CHAT_ID else "",
        "cooldown": COOLDOWN,
        "last": LAST_TELEGRAM,
        "pairs": list(PAIRS.keys())
    })

@app.route("/api/telegram_test")
def tg_test():
    price, src = get_price("BTC")
    res = send_tg("BTC", "COMPRA", price, force=True, text_extra=f"Source: {src} - Test singolo")
    return jsonify(res)

@app.route("/api/force_telegram")
def force_tg():
    out = {}
    for name in PAIRS.keys():
        price, src = get_price(name)
        out[name] = send_tg(name, "COMPRA", price, force=True, text_extra=f"Source: {src} - Force all")
    return jsonify(out)

@app.route("/api/send_msg")
def send_custom():
    txt = request.args.get("text", "Test custom V95")
    if not TELEGRAM_ENABLED:
        return jsonify({"ok": False, "error": "no token"})
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": f"🧪 {txt}\n{VERSION} - {rome_now()}"},
            timeout=10
        )
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

def bg_loop():
    # Loop leggero che ogni 5 minuti manda heartbeat se vuoi - disattivato di default
    while True:
        time.sleep(60)

threading.Thread(target=bg_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

