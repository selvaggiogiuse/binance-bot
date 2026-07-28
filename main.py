import os, time, threading, requests
from flask import Flask
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or ""
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or ""
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

app = Flask(__name__)
LOGS = []
COUNTER = 0

def log_msg(m):
    t = datetime.now().strftime("%H:%M:%S")
    s = "[" + t + "] " + m
    print(s, flush=True)
    LOGS.append(s)
    if len(LOGS) > 200:
        LOGS.pop(0)

def send_tg(txt):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": txt}, timeout=15)
    except:
        pass

def get_klines(sym, interval, lim):
    urls = [
        "https://data-api.binance.vision/api/v3/klines?symbol=" + sym + "&interval=" + interval + "&limit=" + str(lim),
        "https://api1.binance.com/api/v3/klines?symbol=" + sym + "&interval=" + interval + "&limit=" + str(lim)
    ]
    for u in urls:
        try:
            r = requests.get(u, timeout=10).json()
            if isinstance(r, list) and len(r) >= 10:
                return r
        except:
            pass
    return []

def get_price_data(sym):
    try:
        u = "https://data-api.binance.vision/api/v3/ticker/24hr?symbol=" + sym
        d = requests.get(u, timeout=10).json()
        return float(d['lastPrice']), float(d['priceChangePercent'])
    except:
        return 0, 0

def get_eur_price(sym):
    eur_sym = sym.replace("USDT", "EUR")
    try:
        u = "https://data-api.binance.vision/api/v3/ticker/price?symbol=" + eur_sym
        d = requests.get(u, timeout=10).json()
        return float(d['price'])
    except:
        try:
            u = "https://data-api.binance.vision/api/v3/ticker/price?symbol=EURUSDT"
            d = requests.get(u, timeout=10).json()
            eur_usdt = float(d['price'])
            price_usdt, _ = get_price_data(sym)
            if eur_usdt > 0:
                return price_usdt / eur_usdt
        except:
            pass
    p, _ = get_price_data(sym)
    return p

def calc_rsi(klines, period=14):
    try:
        closes = []
        for c in klines:
            closes.append(float(c[4]))
        if len(closes) < period + 1:
            return 50.0
        gains = 0.0
        losses = 0.0
        for i in range(1, period+1):
            diff = closes[i] - closes[i-1]
            if diff > 0:
                gains += diff
            else:
                losses -= diff
        if losses == 0:
            return 70.0
        rs = gains / losses if losses != 0 else 0
        rsi = 100 - (100 / (1 + rs))
        return round(rsi, 1)
    except:
        return 50.0

def get_vol_label(kl):
    try:
        if not kl:
            return "VOL NORMALE"
        vols = []
        for c in kl:
            vols.append(float(c[5]))
        vn = vols[-1]
        avg = sum(vols[:-1]) / len(vols[:-1]) if len(vols) > 1 else vn
        if avg == 0:
            return "VOL NORMALE"
        if vn < avg * 0.7:
            return "VOL BASSO"
        elif vn > avg * 1.9:
            return "VOL ALTO"
        else:
            return "VOL NORMALE"
    except:
        return "VOL NORMALE"

def get_trend(kl):
    try:
        closes = []
        for c in kl:
            closes.append(float(c[4]))
        if len(closes) < 6:
            return "FLAT / STABILE"
        change_5 = (closes[-1] - closes[-6]) / closes[-6] * 100
        ema_short = sum(closes[-3:]) / 3
        ema_long = sum(closes[-6:]) / 6
        if change_5 > 0.6 and ema_short > ema_long:
            return "RIALZO"
        if change_5 > 0.15 and ema_short >= ema_long:
            return "RIALZO LEGGERO"
        if change_5 < -0.6 and ema_short < ema_long:
            return "RIBASSO"
        if change_5 < -0.15 and ema_short <= ema_long:
            return "RIBASSO LEGGERO"
        return "FLAT / STABILE"
    except:
        return "FLAT / STABILE"

def get_trend_icon(trend):
    if "RIALZO" in trend:
        return "\U0001f4c8 "
    if "RIBASSO" in trend:
        return "\U0001f4c9 "
    return "\u27a1\ufe0f "

def get_rsi_label(rsi):
    if rsi < 30:
        return "IPERVENDUTO"
    if rsi < 40:
        return "SCONTO"
    if rsi > 70:
        return "IPERCOMPRATO"
    if rsi > 65:
        return "CARO"
    return "NEUTRO"

def build_agg_1m():
    klines_map = {}
    for s in SYMBOLS:
        klines_map[s] = get_klines(s, "1m", 30)

    now = datetime.now().strftime("%H:%M:%S")
    msg = "\u23f1\ufe0f AGGIORNAMENTO 1m - " + now + "\n"

    for s in SYMBOLS:
        price_usdt, ch24 = get_price_data(s)
        price_eur = get_eur_price(s)
        kl = klines_map.get(s, [])
        rsi = calc_rsi(kl)
        vol = get_vol_label(kl)
        trend = get_trend(kl)
        icon = get_trend_icon(trend)
        rsi_lab = get_rsi_label(rsi)

        short = s.replace("USDT", "")
        price_str_us = "{:,.2f}".format(price_eur) + "E"

        # aggiungo volume come vuoi tu
        vol_icon = "zZ " if "BASSO" in vol else ""
        line = short + ": " + price_str_us + " (" + ("+" if ch24>=0 else "") + str(round(ch24,2)) + "%) " + icon + trend + " | " + vol_icon + vol + " | RSI " + str(rsi) + " " + rsi_lab + "\n"
        msg += line
    return msg

def build_trend_5m():
    klines_map = {}
    for s in SYMBOLS:
        klines_map[s] = get_klines(s, "5m", 30)

    msg = "\U0001f4ca TREND 5m:\n"

    for s in SYMBOLS:
        kl = klines_map.get(s, [])
        try:
            closes = []
            for c in kl:
                closes.append(float(c[4]))
            if len(closes) >= 6:
                change_5m = (closes[-1] - closes[-6]) / closes[-6] * 100
            else:
                change_5m = 0.0
        except:
            change_5m = 0.0

        rsi = calc_rsi(kl)
        vol = get_vol_label(kl)
        trend = get_trend(kl)
        icon = get_trend_icon(trend)
        rsi_lab = get_rsi_label(rsi)
        short = s.replace("USDT", "")

        sign = "+" if change_5m >= 0 else ""
        vol_icon = "zZ " if "BASSO" in vol else ""
        line = short + ": " + sign + str(round(change_5m,2)) + "% in 5m " + icon + trend + " | " + vol_icon + vol + " | RSI " + str(rsi) + " " + rsi_lab + "\n"
        msg += line

    return msg

def loop_bot():
    global COUNTER
    log_msg("Bot v8 CON VOLUME partito")
    send_tg("Bot v8 CON VOLUME partito - formato foto + volume")

    while True:
        try:
            COUNTER += 1
            msg1 = build_agg_1m()
            log_msg("Invio AGG 1m con volume")
            send_tg(msg1)

            if COUNTER % 5 == 0:
                time.sleep(2)
                msg5 = build_trend_5m()
                log_msg("Invio TREND 5m con volume")
                send_tg(msg5)

            time.sleep(60)
        except Exception as e:
            log_msg("Loop err " + str(e))
            time.sleep(10)

@app.route("/")
def home():
    return "Bot v8 con volume vivo - " + str(len(LOGS)) + " log"

@app.route("/log")
def show_log():
    return "<br>".join(LOGS[-200:])

t = threading.Thread(target=loop_bot, daemon=True)
t.start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
