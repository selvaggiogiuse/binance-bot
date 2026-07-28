import os
import time
import threading
import traceback
import requests
from flask import Flask
from datetime import datetime

# --- CONFIG ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

app = Flask(__name__)
LOGS = []
bot_thread = None

def log_msg(msg):
    t = datetime.now().strftime("%H:%M:%S")
    entry = f"[{t}] {msg}"
    print(entry)
    LOGS.append(entry)
    if len(LOGS) > 200:
        LOGS.pop(0)

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        log_msg(f"Telegram error: {e}")

def get_volume_info(symbol, interval=1, lookback=20):
    """
    Ritorna SEMPRE 3 valori: vol_attuale, media, label
    Questo era il bug che ti fermava il bot.
    """
    try:
        # Binance klines: interval = 1m o 5m
        int_str = f"{interval}m"
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={int_str}&limit={lookback+1}"
        r = requests.get(url, timeout=10).json()
        if not r or len(r) < lookback:
            return 0, 0, "💤 VOL BASSO"

        volumes = [float(c[5]) for c in r]
        vol_now = volumes[-1]
        vol_avg = sum(volumes[:-1]) / len(volumes[:-1]) if volumes[:-1] else vol_now

        if vol_now < vol_avg * 0.7:
            label = "💤 VOL BASSO"
        elif vol_now > vol_avg * 1.9:
            label = "🔥 VOL ALTO"
        else:
            label = "💧 VOL NORMALE"

        return vol_now, vol_avg, label
    except Exception as e:
        log_msg(f"Vol error {symbol} {interval}m: {e}")
        return 0, 0, "💤 VOL BASSO"

def get_price_info(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
        data = requests.get(url, timeout=10).json()
        return float(data['lastPrice'])
    except:
        return 0

def loop_bot():
    log_msg("Bot KRAKEN v5.2 partito ✅ con fix volume")
    send_telegram("Bot KRAKEN v5.2 partito ✅ con fix volume + auto-restart")

    while True:
        try:
            for s in SYMBOLS:
                # QUI ERA L'ERRORE - ORA CORRETTO CON 3 VARIABILI
                vol_1m, vol_avg_1m, vol_label_1m = get_volume_info(s, interval=1, lookback=20)
                vol_5m, vol_avg_5m, vol_label_5m = get_volume_info(s, interval=5, lookback=20)

                price = get_price_info(s)

                # ESEMPIO DI LOGICA - puoi tenere la tua
                # Se volume basso, non mandare allarme
                if vol_label_1m == "💤 VOL BASSO" and vol_label_5m == "💤 VOL BASSO":
                    log_msg(f"⏱️ AGG 1m - {s}: {price} | {vol_label_1m} ({vol_1m:.1f} vs avg {vol_avg_1m:.1f}) - SKIP")
                    continue

                msg = f"🚨 ALLARME {s}\nPrice: {price}\n1m: {vol_label_1m} ({vol_1m:.1f} vs {vol_avg_1m:.1f})\n5m: {vol_label_5m} ({vol_5m:.1f} vs {vol_avg_5m:.1f})"
                log_msg(msg.replace("\n", " | "))
                send_telegram(msg)

            time.sleep(60) # manda ogni minuto

        except Exception as e:
            err = traceback.format_exc()
            log_msg(f"ERRORE CRITICO LOOP: {e}\n{err[-500:]}")
            # non muore più, aspetta 15 sec e riparte
            time.sleep(15)

@app.route("/")
def home():
    # Watchdog: se il thread è morto, lo riavvia quando UptimeRobot pinga
    global bot_thread
    if bot_thread is None or not bot_thread.is_alive():
        log_msg("Watchdog: thread morto, riavvio...")
        bot_thread = threading.Thread(target=loop_bot, daemon=True, name="loop_bot")
        bot_thread.start()
        return "Bot riavviato dal watchdog ✅", 200
    return f"Bot vivo ✅ - Log: {len(LOGS)} righe", 200

@app.route("/log")
def show_log():
    return "<br>".join(LOGS[-100:])

# Avvio thread all'inizio
bot_thread = threading.Thread(target=loop_bot, daemon=True, name="loop_bot")
bot_thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
