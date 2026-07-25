import os, time, threading, requests
from flask import Flask

app = Flask(__name__)
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

SIMBOLI = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
PRE_SOGLIA = 0.5 # pre-allarme
SOGLIA = 1.0 # allarme vero

def get_price(symbol):
    try:
        url = f"https://data-api.binance.vision/api/v3/ticker/price?symbol={symbol}"
        return float(requests.get(url, timeout=10).json()['price'])
    except:
        return None

def send_telegram(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
        print(f"Inviato: {msg}")
    except Exception as e:
        print(f"Errore: {e}")

@app.route("/")
def home(): return "Bot 0.5% / 1% online"
@app.route("/test")
def test():
    p = get_price("BTCUSDT")
    send_telegram(f"Test OK - BTC: {p:.2f}$")
    return "ok"

def loop_bot():
    last = {}
    pre_sent = {}
    # avvio
    msg_avvio = "Bot partito ✅ (pre 0.5% / allarme 1%)\n"
    for s in SIMBOLI:
        pr = get_price(s)
        if pr:
            last[s] = pr
            pre_sent[s] = False
            msg_avvio += f"{s}: ${pr:,.2f}\n"
    send_telegram(msg_avvio)

    while True:
        for s in SIMBOLI:
            price = get_price(s)
            if not price or s not in last: continue

            var = ((price - last[s]) / last[s]) * 100
            abs_var = abs(var)

            if abs_var >= SOGLIA:
                send_telegram(f"🚨 ALLARME {s}: ${price:,.2f} ({var:+.2f}%) - ha fatto 1%!")
                last[s] = price
                pre_sent[s] = False

            elif abs_var >= PRE_SOGLIA and not pre_sent[s]:
                send_telegram(f"⚠️ PRE-ALLARME {s}: ${price:,.2f} ({var:+.2f}%) - si sta muovendo!")
                pre_sent[s] = True

            elif abs_var < 0.3: # se torna indietro resetta il pre-allarme
                pre_sent[s] = False

            else:
                print(f"{s} {var:+.2f}% - sotto soglia")

        time.sleep(60) # 1 minuto

threading.Thread(target=loop_bot, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
