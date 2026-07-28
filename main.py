import os, time, threading, requests
from flask import Flask
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or ""
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or ""
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

app = Flask(__name__)
LOGS = []

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
            if isinstance(r, list) and len(r) >= 15:
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
    # Prova coppia diretta EUR, altrimenti converte da USDT
    eur_sym = sym.replace("USDT", "EUR")
    try:
        u = "https://data-api.binance.vision/api/v3/ticker/price?symbol=" + eur_sym
        d = requests.get(u, timeout=10).json()
        return float(d['price'])
    except:
        try:
            # conversione tramite EURUSDT
            u = "https://data-api.binance.vision/api/v3/ticker/price?symbol=EURUSDT"
            d = requests.get(u, timeout=10).json()
            eur_usdt = float(d['price'])
            price_usdt, _ = get_price_data(sym)
            if eur_usdt > 0:
                return price_usdt / eur_usdt
        except:
            pass
    # fallback usa prezzo USDT
    p, _ = get_price_data(sym)
    return p

def calc_rsi(klines, period=14):
    try:
        closes = []
        for c in klines:
            closes.append(float(c[4]))
        if len(closes) < period + 1:
            return 50
        gains = 0
        losses = 0
        for i in range(1, period+1):
            diff = closes[i] - closes[i-1]
            if diff > 0:
                gains += diff
            else:
                losses -= diff
        if losses == 0:
            return 70
        rs = gains / losses if losses != 0 else 0
        rsi = 100 - (100 / (1 + rs))
        return round(rsi, 1)
    except:
        return 50

def get_vol_label(sym):
    try:
        kl = get_klines(sym, "1m", 21)
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

def get_trend(ch):
    if ch > 0.5:
        return "\U0001f4c8 RIALZO"
    if ch > 0.15:
        return "\U0001f4c8 RIALZO LEGGERO"
    if ch < -0.5:
        return "\U0001f4c9 RIBASSO"
    if ch < -0.15:
        return "\U0001f4c9 RIBASSO LEGGERO"
    return "\u27a1\ufe0f FLAT / STABILE"

def get_rsi_label(rsi):
    if rsi > 70:
        return "IPERCOMPRATO"
    if rsi < 30:
        return "IPERVENDUTO"
    if rsi > 60:
        return "NEUTRO-RB"
    if rsi < 40:
        return "NEUTRO-RI"
    return "NEUTRO"

def loop_bot():
    log_msg("Bot v6 BELLO partito - formato Matrice")
    send_tg("Bot KRAKEN v6 BELLO partito - formato come seconda foto, con fix VOL BASSO")

    while True:
        try:
            klines_map = {}
            for s in SYMBOLS:
                klines_map[s] = get_klines(s, "1m", 30)

            now = datetime.now().strftime("%H:%M:%S")
            msg = "\u23f1\ufe0f AGG 1m - " + now + "\n"

            for s in SYMBOLS:
                price_usdt, ch = get_price_data(s)
                price_eur = get_eur_price(s)
                kl = klines_map.get(s, [])
                rsi = calc_rsi(kl)
                vol = get_vol_label(s)
                trend = get_trend(ch)
                rsi_lab = get_rsi_label(rsi)

                # nome corto BTC ETH SOL
                short = s.replace("USDT", "")
                # formato con punto migliaia e virgola euro come seconda foto
                price_str = "{:,.2f}".format(price_eur).replace(",", "X").replace(".", ",").replace("X", ".") + "E"

                # zZ per vol basso
                vol_icon = "\U0001f4a4 " if "BASSO" in vol else ""
                if "BASSO" in vol:
                    vol_icon = "zZ "

                line = short + ": " + price_str + " (" + ("+" if ch>=0 else "") + str(round(ch,2)) + "%) " + trend + " | " + vol_icon + vol + " | RSI " + str(rsi) + " " + rsi_lab + "\n"
                msg += line

            log_msg("Invio AGG raggruppato")
            send_tg(msg)

            time.sleep(60)
        except Exception as e:
            log_msg("Loop err " + str(e))
            time.sleep(10)

@app.route("/")
def home():
    return "Bot v6 bello vivo - " + str(len(LOGS)) + " log"

@app.route("/log")
def show_log():
    return "<br>".join(LOGS[-200:])

t = threading.Thread(target=loop_bot, daemon=True)
t.start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
