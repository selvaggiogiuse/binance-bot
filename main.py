import os, time, threading, requests
from flask import Flask

app = Flask(__name__)
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

SIMBOLI = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
PRE_SOGLIA = 0.2 # preavviso a 0.2%
SOGLIA = 1.0 # allarme vero a 1%

def get_price(symbol):
    try:
        url = f"https://data-api.binance.vision/api/v3/ticker/price?symbol={symbol}"
        r = requests.get(url, timeout=10)
        return float(r.json()['price'])
    except:
        return None

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
        print(f"Inviato: {msg}")
    except Exception as e:
        print(f"Errore telegram: {e}")

@app.route("/")
def home():
    return "Bot 0.2% / 1% online - BTC ETH SOL"

@app.route("/test")
def test():
    p = get_price("BTCUSDT")
    send_telegram(f"Test OK - BTC: {p:.2f}$")
    return "test inviato"

def loop_bot():
    last = {}
    pre_sent = {}

    # Messaggio di avvio
    msg = "Bot partito ✅\nPre 0.2% / Allarme 1%\n"
    for s in SIMBOLI:
        pr = get_price(s)
        if pr:
            last[s] = pr
            pre_sent[s] = False
            msg += f"{s}: ${pr:,.2f}\n"
    send_telegram(msg)

    while True:
        for s in SIMBOLI:
            price = get_price(s)
            if not price or s not in last:
                continue

            var = ((price - last[s]) / last[s]) * 100
            abs_var = abs(var)

            # ALLARME VERO 1%
            if abs_var >= SOGLIA:
                send_telegram(f"🚨 ALLARME {s}: ${price:,.2f} ({var:+.2f}%)")
                last[s] = price
                pre_sent[s] = False

            # PREAVVISO 0.2%
            elif abs_var >= PRE_SOGLIA and not pre_sent[s]:
                send_telegram(f"⚠️ PREAVVISO {s}: ${price:,.2f} ({var:+.2f}%) - si sta muovendo!")
                pre_sent[s] = True

            # Reset se torna indietro
            elif abs_var < 0.1:
                pre_sent[s] = False
            else:
                print(f"{s} {var:+.2f}% - sotto soglia")

        time.sleep(60) # controlla ogni 60 secondi

threading.Thread(target=loop_bot, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
