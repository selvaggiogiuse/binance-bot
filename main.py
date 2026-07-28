import os, time, threading, requests, csv
from flask import Flask, Response
from datetime import datetime

app = Flask(__name__)
TOKEN = os.environ.get("TELEGRAM_TOKEN","").strip()
CHAT_ID = os.environ.get("CHAT_ID","").strip()

SIMBOLI = ["BTCEUR", "ETHEUR", "SOLEUR"]
PRE_SOGLIA = 0.2
SOGLIA = 0.5
SOGLIA_FORTE = 1.0
LOG_FILE = "trading_log.csv"

def get_display(s): return s.replace("EUR","")

def get_price(symbol):
    try:
        url = f"https://api.kraken.com/0/public/Ticker?pair={symbol}"
        r = requests.get(url, timeout=10).json()
        k = list(r['result'].keys())[0]
        return float(r['result'][k]['c'][0])
    except: return None

def get_ohlc(symbol, interval=15):
    try:
        url = f"https://api.kraken.com/0/public/OHLC?pair={symbol}&interval={interval}"
        r = requests.get(url, timeout=10).json()
        key = [x for x in r['result'].keys() if x!= 'last'][0]
        return r['result'][key] # [time, open, high, low, close, vwap, volume, count]
    except: return []

def get_rsi(symbol, interval=15, period=14):
    try:
        data = get_ohlc(symbol, interval)
        closes = [float(c[4]) for c in data]
        if len(closes) < period + 2: return None
        deltas = [closes[i]-closes[i-1] for i in range(1,len(closes))]
        gains = [d if d>0 else 0 for d in deltas]
        losses = [-d if d<0 else 0 for d in deltas]
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        for i in range(period, len(gains)):
            avg_gain = (avg_gain*(period-1) + gains[i]) / period
            avg_loss = (avg_loss*(period-1) + losses[i]) / period
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return round(100 - (100/(1+rs)), 1)
    except: return None

def get_volume_info(symbol, interval=1, lookback=20):
    try:
        data = get_ohlc(symbol, interval)
        if len(data) < lookback + 1: return 0, 0, "VOL n/d"
        volumes = [float(c[6]) for c in data]
        last_vol = volumes[-1]
        avg_vol = sum(volumes[-lookback-1:-1]) / lookback
        if avg_vol == 0: return last_vol, avg_vol, "VOL n/d"
        if last_vol > avg_vol * 1.5: label = "🔥 VOL ALTO"
        elif last_vol < avg_vol * 0.7: label = "💤 VOL BASSO"
        else: label = "VOL NORMALE"
        return last_vol, avg_vol, label
    except: return 0, 0, "VOL n/d"

def rsi_text(rsi):
    if rsi is None: return "RSI n/d"
    if rsi >= 75: return f"RSI {rsi} IPERCOMPRATO ⚠️ RISCHIO ALTO"
    if rsi >= 70: return f"RSI {rsi} IPERCOMPRATO ⚠️"
    if rsi <= 25: return f"RSI {rsi} IPERVENDUTO 💰 OCCASIONE"
    if rsi <= 30: return f"RSI {rsi} IPERVENDUTO 💰"
    if rsi <= 40: return f"RSI {rsi} SCONTO"
    if rsi >= 60: return f"RSI {rsi} CARO"
    return f"RSI {rsi} NEUTRO"

def trend_label(var):
    if var >= 1.0: return "📈 RIALZO FORTE"
    if var >= 0.5: return "📈 RIALZO"
    if var >= 0.2: return "📈 RIALZO LEGGERO"
    if var <= -1.0: return "📉 RIBASSO FORTE"
    if var <= -0.5: return "📉 RIBASSO"
    if var <= -0.2: return "📉 RIBASSO LEGGERO"
    return "➡️ FLAT / STABILE"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except: pass

def init_log():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["timestamp","symbol","price","var_1m","var_5m","rsi","vol","vol_avg","vol_label","event"])

def append_log(row):
    try:
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)
    except: pass

@app.route("/")
def home(): return "Bot v5 online - Volume + Log"
@app.route("/test")
def test():
    send_telegram("Test v5 ✅ Volume + Log attivi")
    return "ok"
@app.route("/log")
def view_log():
    if not os.path.exists(LOG_FILE): return "Log vuoto"
    with open(LOG_FILE, "r", encoding="utf-8") as f: content = f.read()[-10000:]
    return Response(content, mimetype="text/plain")

def loop_bot():
    init_log()
    last = {}
    last_5m_price = {}
    rsi_cache = {}
    last_trend_time = time.time()

    txt = "Bot KRAKEN v5 partito ✅\n- Filtro VOLUME attivo\n- Log CSV attivo su /log\n"
    for s in SIMBOLI:
        p = get_price(s)
        if p:
            last[s]=p
            last_5m_price[s]=p
            rsi_cache[s]=get_rsi(s) or 50
            txt+=f"{get_display(s)}: {p:,.2f}€\n"
    send_telegram(txt)

    while True:
        now_str = datetime.now().strftime("%H:%M:%S")
        now_iso = datetime.now().isoformat()
        status_msg = f"⏱️ AGG 1m - {now_str}\n"

        for s in SIMBOLI:
            price = get_price(s)
            if not price or s not in last: continue

            if time.time() - last_trend_time >= 290:
                r = get_rsi(s)
                if r: rsi_cache[s]=r

            var = ((price-last[s])/last[s])*100
            vol, vol_avg, vol_label = get_volume_info(s, interval=1, lookback=20)
            p_old_5m = last_5m_price.get(s, price)
            var5 = ((price - p_old_5m)/p_old_5m)*100 if p_old_5m else 0

            d = get_display(s)
            rsi = rsi_cache.get(s)
            t_label = trend_label(var)

            status_msg += f"{d}: {price:,.2f}€ ({var:+.2f}%) {t_label} | {vol_label} | {rsi_text(rsi)}\n"

            # LOG ogni minuto
            append_log([now_iso, d, round(price,2), round(var,3), round(var5,3), rsi, round(vol,4), round(vol_avg,4), vol_label, "STATUS"])

            # ALLARMI con filtro volume
            if abs(var) >= SOGLIA_FORTE:
                send_telegram(f"🚨🚨 FORTE {d}: {price:,.2f}€ ({var:+.2f}%) {t_label}\n{vol_label}\n{rsi_text(rsi)}")
                append_log([now_iso, d, round(price,2), round(var,3), round(var5,3), rsi, round(vol,4), round(vol_avg,4), vol_label, "FORTE"])
                last[s]=price
            elif abs(var) >= SOGLIA:
                if "BASSO" in vol_label:
                    # falso movimento, non allarmare ma logga
                    append_log([now_iso, d, round(price,2), round(var,3), round(var5,3), rsi, round(vol,4), round(vol_avg,4), vol_label, "SKIP_VOL_BASSO"])
                else:
                    send_telegram(f"🚨 ALLARME {d}: {price:,.2f}€ ({var:+.2f}%) {t_label}\n{vol_label}\n{rsi_text(rsi)}")
                    append_log([now_iso, d, round(price,2), round(var,3), round(var5,3), rsi, round(vol,4), round(vol_avg,4), vol_label, "ALLARME"])
                    last[s]=price

        send_telegram(status_msg)

        if time.time() - last_trend_time >= 300:
            msg_trend = "📊 TREND 5m:\n"
            for s in SIMBOLI:
                p = get_price(s)
                if not p: continue
                p_old = last_5m_price.get(s, p)
                var5 = ((p - p_old)/p_old)*100 if p_old else 0
                t_label_5m = trend_label(var5)
                _, vol_label_5m = get_volume_info(s, interval=5, lookback=20)
                msg_trend += f"{get_display(s)}: {var5:+.2f}% in 5m {t_label_5m} | {vol_label_5m} | {rsi_text(rsi_cache.get(s))}\n"
                last_5m_price[s]=p
            send_telegram(msg_trend)
            last_trend_time = time.time()

        time.sleep(60)

threading.Thread(target=loop_bot, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
