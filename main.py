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

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except: pass

@app.route("/")
def home(): return "Bot RIALZO/RIBASSO online"
@app.route("/test")
def test():
    send_telegram("Test Bot RIALZO/RIBASSO ✅")
    return "ok"

def loop_bot():
    last = {}; pre_sent = {}
    txt = "Bot KRAKEN RIALZO/RIBASSO partito ✅\n"
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

            if abs_var >= SOGLIA_FORTE:
                trend = "📈 RIALZO FORTE" if var>0 else "📉 RIBASSO FORTE"
                send_telegram(f"🚨🚨 FORTE {d}: {price:,.2f} € ({var:+.2f}%) {trend}\n💡 RISCHIO MEDIO")
                last[s]=price; pre_sent[s]=False

            elif abs_var >= SOGLIA:
                trend = "📈 RIALZO" if var>0 else "📉 RIBASSO"
                send_telegram(f"🚨 ALLARME {d}: {price:,.2f} € ({var:+.2f}%) {trend}\n💡 RISCHIO BASSO")
                last[s]=price; pre_sent[s]=False

            elif abs_var >= PRE_SOGLIA and not pre_sent[s]:
                trend = "📈 RIALZO LEGGERO" if var>0 else "📉 RIBASSO LEGGERO"
                send_telegram(f"⚠️ PRE {d}: {price:,.2f} € ({var:+.2f}%) {trend}\n💡 Solo INFO")
                pre_sent[s]=True

            elif abs_var < 0.1:
                pre_sent[s]=False
        time.sleep(60)

threading.Thread(target=loop_bot, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
