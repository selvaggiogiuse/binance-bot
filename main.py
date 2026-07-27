import os, time, threading, requests
from flask import Flask

app = Flask(__name__)
TOKEN = os.environ.get("TELEGRAM_TOKEN","").strip()
CHAT_ID = os.environ.get("CHAT_ID","").strip()

SIMBOLI = ["BTCEUR", "ETHEUR", "SOLEUR"]
PRE_SOGLIA = 0.2
SOGLIA = 0.8
SOGLIA_FORTE = 2.0

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
    if rsi is None: return ""
    if rsi >= 75: return f"RSI {rsi} IPERCOMPRATO ⚠️ RISCHIO ALTO"
    if rsi >= 70: return f"RSI {rsi} IPERCOMPRATO ⚠️"
    if rsi <= 25: return f"RSI {rsi} IPERVENDUTO 💰 OCCASIONE"
    if rsi <= 30: return f"RSI {rsi} IPERVENDUTO 💰"
    if rsi <= 40: return f"RSI {rsi} SCONTO"
    if rsi >= 60: return f"RSI {rsi} CARO"
    return f"RSI {rsi}"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except: pass

@app.route("/")
def home(): return "Bot RSI online"
@app.route("/test")
def test():
    send_telegram("Test Bot con RSI ✅")
    return "ok"

def loop_bot():
    last = {}; pre_sent = {}
    txt = "Bot KRAKEN con RSI partito ✅\n"
    for s in SIMBOLI:
        p = get_price(s)
        if p:
            last[s]=p; pre_sent[s]=False
            txt+=f"{get_display(s)}: {p:,.2f} €\n"
    send_telegram(txt)

    while True:
        for s in SIMBOLI:
            price = get_price(s)
            if not price or s not in last: continue
            var = ((price-last[s])/last[s])*100
            abs_var = abs(var)
            d = get_display(s)
            rsi = get_rsi(s)
            rsi_info = rsi_text(rsi)

            if abs_var >= SOGLIA_FORTE:
                trend = "📈 RIALZO FORTE" if var>0 else "📉 RIBASSO FORTE"
                send_telegram(f"🚨🚨 FORTE {d}: {price:,.2f} € ({var:+.2f}%) {trend}\n{rsi_info}")
                last[s]=price; pre_sent[s]=False

            elif abs_var >= SOGLIA:
                trend = "📈 RIALZO" if var>0 else "📉 RIBASSO"
                send_telegram(f"🚨 ALLARME {d}: {price:,.2f} € ({var:+.2f}%) {trend}\n{rsi_info}")
                last[s]=price; pre_sent[s]=False

            elif abs_var >= PRE_SOGLIA and not pre_sent[s]:
                trend = "📈 RIALZO LEGGERO" if var>0 else "📉 RIBASSO LEGGERO"
                send_telegram(f"⚠️ PRE {d}: {price:,.2f} € ({var:+.2f}%) {trend}\n{rsi_info}")
                pre_sent[s]=True

            elif abs_var < 0.1:
                pre_sent[s]=False
        time.sleep(60)

threading.Thread(target=loop_bot, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
