import os, requests, time, json
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
    def rome_now():
        return datetime.now(ZoneInfo("Europe/Rome"))
except:
    def rome_now():
        return datetime.now(timezone.utc) + timedelta(hours=2)

from flask import Flask, jsonify

app = Flask(__name__)

# CONFIG TELEGRAM - metti in ENV su Render per sicurezza
# Su Render: Environment -> TELEGRAM_BOT_TOKEN = 123456:ABC..., TELEGRAM_CHAT_ID = 123456789
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")  # da BotFather
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")  # tuo chat ID
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
# NUOVO: soglia configurabile da Render, default 75%
TELEGRAM_MIN_CONF = int(os.getenv("TELEGRAM_MIN_CONFIDENCE", "75"))

PAIRS_LIVE = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "ORO": "PAXGUSDT"}
PAIRS_OHLC = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "ORO": "PAXGUSDT"}
TF_MAP = {"5m": "5m", "15m": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}
VERSION = "V57 - TELEGRAM SCALPING - 75%"

LAST_TELEGRAM = {}  # coin_TF -> timestamp
TELEGRAM_COOLDOWN = 900  # 15 min per scalping 5m

def calc_rsi(prices, period=14):
    try:
        import numpy as np
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    except:
        return 50

def get_binance_klines(symbol, interval, limit=100):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        data = requests.get(url, timeout=10).json()
        closes = [float(x[4]) for x in data]
        highs = [float(x[2]) for x in data]
        lows = [float(x[3]) for x in data]
        return closes, highs, lows
    except:
        return None, None, None

def send_telegram_signal(coin, tf, signal, conf, price, rsi, stoch, sl, tp, sl_pct, tp_pct, source):
    if not TELEGRAM_ENABLED:
        return {"ok": False, "error": "Telegram non configurato - manca TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID in ENV Render"}

    # FILTRO PRINCIPALE MODIFICATO: prima era 85, ora 75%
    if conf < TELEGRAM_MIN_CONF:
        return {"ok": False, "error": f"Confidenza {conf}% < soglia {TELEGRAM_MIN_CONF}%"}

    key = f"{coin}_{tf}"
    now = time.time()
    last = LAST_TELEGRAM.get(key, 0)
    if now - last < TELEGRAM_COOLDOWN:
        return {"ok": False, "error": f"Tempo di raffreddamento {int((TELEGRAM_COOLDOWN - (now-last))/60)} min per {key}"}

    ora = rome_now().strftime("%H:%M:%S Europe/Rome")
    emoji = "🚀" if "VENDI" in signal else "🟢"
    
    text = f"""{emoji} {signal} {coin} COMPRA {conf}% ⚡️ {tf} SCALP

💰 Prezzo: ${price:.2f}
📊 RSI: {int(rsi)} | Stoch: {int(stoch)}
🎯 SL: ${sl:.2f} ({sl_pct})
🎯 TP: ${tp:.2f} ({tp_pct})
⏰ {ora}

Confluenza: {source}
Versione: {VERSION}"""

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
        r = requests.post(url, json=payload, timeout=10)
        j = r.json()
        if j.get("ok"):
            LAST_TELEGRAM[key] = now
            return {"ok": True, "sent": text}
        else:
            return {"ok": False, "error": j}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# LOGICA V57 - SCANNER
def check_v57_signal():
    results = []
    for coin, symbol in PAIRS_OHLC.items():
        closes, highs, lows = get_binance_klines(symbol, "5m", 100)
        if closes is None:
            continue
        
        price = closes[-1]
        rsi = calc_rsi(closes, 14)
        
        # Stoch semplificato
        k_period = 14
        lowest = min(lows[-k_period:])
        highest = max(highs[-k_period:])
        stoch = 100 * ((price - lowest) / (highest - lowest)) if highest != lowest else 50

        # Calcolo confidenza V57
        conf = 0
        if rsi > 60: conf += 20
        if rsi > 68: conf += 20
        if rsi > 72: conf += 15
        if stoch > 70: conf += 20
        if stoch > 80: conf += 15
        conf = min(conf, 95)

        # Segnale VENDI se ipercomprato
        if conf >= TELEGRAM_MIN_CONF and rsi > 65 and stoch > 70:
            sl = price * 0.992
            tp = price * 1.015
            source = f"Multi-TF: 5m RSI {int(rsi)} + Stoch {int(stoch)} - Soglia {TELEGRAM_MIN_CONF}%"
            res = send_telegram_signal(coin, "5m", "VENDI", int(conf), price, rsi, stoch, sl, tp, "-0.80%", "+1.50%", source)
            results.append({coin: res})
    return results

@app.route("/")
def home():
    return jsonify({
        "version": VERSION,
        "pairs": PAIRS_LIVE,
        "telegram_enabled": TELEGRAM_ENABLED,
        "min_confidence": TELEGRAM_MIN_CONF,
        "cooldown_sec": TELEGRAM_COOLDOWN,
        "time": rome_now().isoformat(),
        "last_telegram": LAST_TELEGRAM
    })

@app.route("/api/telegram_config")
def telegram_config():
    return jsonify({
        "enabled": TELEGRAM_ENABLED,
        "has_token": bool(TELEGRAM_BOT_TOKEN),
        "has_chat_id": bool(TELEGRAM_CHAT_ID),
        "min_confidence": TELEGRAM_MIN_CONF,
        "cooldown": TELEGRAM_COOLDOWN,
        "last": LAST_TELEGRAM
    })

@app.route("/api/telegram_test")
def telegram_test():
    # Test forza 85% così passa sempre anche con soglia 75%
    res = send_telegram_signal("BTC", "5m", "VENDI", 85, 80168.00, 58, 62, 79500.00, 81300.00, "-0.80%", "+1.50%", "TEST - Controlla app per multi-TF")
    return jsonify(res)

@app.route("/api/scan")
def scan_now():
    res = check_v57_signal()
    return jsonify({"scanned": PAIRS_LIVE, "results": res, "threshold": TELEGRAM_MIN_CONF})

# Loop background ogni 60 sec
def background_loop():
    while True:
        try:
            check_v57_signal()
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(60)

threading = __import__("threading")
threading.Thread(target=background_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
