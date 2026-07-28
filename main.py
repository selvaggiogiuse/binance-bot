import os
import time
import threading
import requests
from flask import Flask
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

app = Flask(__name__)
LOGS = []
bot_thread = None

def log_msg(msg):
    t = datetime.now().strftime("%H:%M:%S")
    entry = f"[{t}] {msg}"
    print(entry, flush=True)
    LOGS.append(entry)
    if len(LOGS) > 300:
        LOGS.pop(0)

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        log_msg(f"TG error: {e}")

def get_klines(symbol, interval_str, limit=21):
    urls = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval_str}&limit={limit}",
        f"https://api1.binance.com/api/v3/klines?symbol={symbol}&interval={interval_str}&limit={limit}"
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=10).json()
            if isinstance(r, list) and len(r) >= 5:
                return r
        except:
            continue
    return []

def get_volume_info(symbol, interval=1, lookback=20):
    try:
        klines = get_klines(symbol, f"{interval}m", lookback+1)
        if not klines:
            return 0, 0, "VOL NORMALE"
        volumes = [float(c[5]) for c in klines]
        vol_now = volumes[-1]
        vol_avg = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else vol_now
        if vol_avg == 0:
            return vol_now, vol_avg, "VOL NORMALE"
        if vol_now < vol_avg * 0.7:
            label = "VOL BASSO"
        elif vol_now > vol_avg * 1.9:
            label = "VOL ALTO"
        else:
            label = "VOL NORMALE"
        return vol_now, vol_avg, label
    except:
        return 0, 0, "VOL NORMALE"

def get_price_info(symbol):
    try:
        url = f"https://data-api.binance.vision/api/v3/ticker/24hr?symbol={symbol}"
        d = requests.get(url, timeout=10).json()
        return float(d['lastPrice']), float(d['priceChangePercent'])
    except:
        return 0, 0

def loop_bot():
    log_msg("Bot KRAKEN v5.5 NO-SKIP partito - invia tutto")
    send_telegram("Bot KRAKEN v5.5 partito - ora mando TUTTI i messaggi anche VOL BASSO")

    while True:
        try:
            for s in SYMBOLS:
                try:
                    price, change = get_price_info(s)
                    v1, a1, l1 = get_volume_info(s, 1, 20)
                    v5, a5, l5 = get_volume_info(s, 5, 20)

                    log_line = f"AGG 1m - {s}: {price:.2f} ({change:+.2f}%) | {l1} ({v1:.1f} vs {a1:.1f})"
                    log_msg(log_line)

                    now = datetime.now().strftime("%H:%M:%S")
                    msg = "AGG 1m - " + now + "\n" + s + f": {price:.2f} ({change:+.2f}%)\n1m: {l1} ({v1:.1f} vs {a1:.1f})\n5m: {l5} ({v5:.1f} vs {a5:.1f})"
                    send_telegram(msg)

                except Exception as e:
                    log_msg(f"Errore {s}: {e}")
                    continue
            time.sleep(60)
        except Exception as e:
            log_msg(f"Loop error: {e}")
            time.sleep(10)

@app.route("/")
def home():
    global bot_thread
    if bot_thread is None or not bot_thread.is_alive():
        bot_thread = threading.Thread(target=loop_bot, daemon=True)
        bot_thread.start()
        return "Bot riavviato", 200
    return f"Bot vivo - {len(LOGS)} log", 200

@app.route("/log")
def show_log():
    return "<br>".join(LOGS[-200:])

bot_thread = threading.Thread(target=loop_bot, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
