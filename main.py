import os, time, threading, requests
from flask import Flask
from datetime import datetime

app = Flask(__name__)
TOKEN = os.environ.get("TELEGRAM_TOKEN","").strip()
CHAT_ID = os.environ.get("CHAT_ID","").strip()

SIMBOLI = ["BTCEUR", "ETHEUR", "SOLEUR"]
PRE_SOGLIA = 0.2
SOGLIA = 0.5
SOGLIA_FORTE = 1.0

def get_display(s): return s.replace("EUR","")

def get_price(symbol):
    try:
        url = f"https://api.kraken.com/0/public/Ticker?pair={symbol}"
        r = requests.get(url, timeout=10).json()
        k = list(r['result'].keys())[0]
        return float(r['result'][k]['c'][0])
    except: return None

def get_rsi(symbol, interval=15, period=14):
    try:
        url = f"https://api.kraken.com/0/public/OHLC?pair={symbol}&interval={interval}"
        r = requests.get(url, timeout=10).json()
        key = [x for x in r['result'].keys() if x!= 'last'][0]
        closes = [float(c[4]) for c in r['result'][key]]
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

@app.route("/")
def home(): return "Bot RSI v3 online - 1m status"
@app.route("/test")
def test():
    send_telegram("Test Bot v3 ✅ - status ogni minuto")
    return "ok"

def loop_bot():
    last = {}
    last_5m_price = {}
    rsi_cache = {}
    last_trend_time = time.time()

    txt = "Bot KRAKEN v3 partito ✅\n- Allarmi: 0.2% / 0.5% / 1%\n- Status con TREND+RSI ogni 1m\n- Trend 5m ogni 5m\n"
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
        status_msg = f"⏱️ AGGIORNAMENTO 1m - {now_str}\n"

        for s in SIMBOLI:
            price = get_price(s)
            if not price or s not in last: continue

            # aggiorna RSI ogni 5 min
            if time.time() - last_trend_time >= 290:
                r = get_rsi(s)
                if r: rsi_cache[s]=r

            var = ((price-last[s])/last[s])*100
            abs_var = abs(var)
            d = get_display(s)
            rsi = rsi_cache.get(s)
            t_label = trend_label(var)

            # aggiungi riga allo status di ogni minuto
            status_msg += f"{d}: {price:,.2f}€ ({var:+.2f}%) {t_label} | {rsi_text(rsi)}\n"

            # allarmi classici
            if abs_var >= SOGLIA_FORTE:
                send_telegram(f"🚨🚨 FORTE {d}: {price:,.2f}€ ({var:+.2f}%) {t_label}\n{rsi_text(rsi)}")
                last[s]=price
            elif abs_var >= SOGLIA:
                send_telegram(f"🚨 ALLARME {d}: {price:,.2f}€ ({var:+.2f}%) {t_label}\n{rsi_text(rsi)}")
                last[s]=price

        # manda lo status completo di tutte e 3 ogni minuto
        send_telegram(status_msg)

        # trend 5m ogni 5 min
        if time.time() - last_trend_time >= 300:
            msg_trend = "📊 TREND 5m:\n"
            for s in SIMBOLI:
                p = get_price(s)
                if not p: continue
                p_old = last_5m_price.get(s, p)
                var5 = ((p - p_old)/p_old)*100 if p_old else 0
                msg_trend += f"{get_display(s)}: {var5:+.2f}% in 5m | {rsi_text(rsi_cache.get(s))}\n"
                last_5m_price[s]=p
            send_telegram(msg_trend)
            last_trend_time = time.time()

        time.sleep(60)

threading.Thread(target=loop_bot, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
