import os
import time
import threading
import traceback
import requests
from flask import Flask
from datetime import datetime

# --- CONFIG ---
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
        log_msg("Manca TELEGRAM_TOKEN o CHAT_ID nelle Environment Variables")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        log_msg(f"Telegram error: {e}")

def get_klines(symbol, interval_str, limit=21):
    # Endpoint che funziona da Render USA (quello vecchio api.binance.com è bloccato)
    urls = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval_str}&limit={limit}",
        f"https://api1.binance.com/api/v3/klines?symbol={symbol}&interval={interval_str}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval_str}&limit={limit}"
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
    """
    FIX DEFINITIVO - ritorna sempre 3 valori
    """
    try:
        int_str = f"{interval}m"
        klines = get_klines(symbol, int_str, limit=lookback+1)

        if not klines:
            return 0, 0, "💧 VOL NORMALE"

        volumes = [float(c[5]) for c in klines]
        vol_now = volumes[-1]
        vol_avg = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else vol_now

        if vol_avg == 0:
            return vol_now, vol_avg, "💧 VOL NORMALE"

        if vol_now < vol_avg * 0.7:
            label = "💤 VOL BASSO"
        elif vol_now > vol_avg * 1.9:
            label = "🔥 VOL ALTO"
        else:
            label = "💧 VOL NORMALE"

        return vol_now, vol_avg, label
    except Exception as e:
        log_msg(f"Vol error {symbol} {interval}m: {e}")
        return 0, 0, "💧 VOL NORMALE"

def get_price_info(symbol):
    try:
        url = f"https://data-api.binance.vision/api/v3/ticker/24hr?symbol={symbol}"
        data = requests.get(url, timeout=10).json()
        price = float(data['lastPrice'])
        change = float(data['priceChangePercent'])
        return price, change
    except:
        return 0, 0

def loop_bot():
    log_msg("Bot KRAKEN v5.3
