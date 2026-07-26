import os, time, threading, requests
from flask import Flask

app = Flask(__name__)
TOKEN = os.environ.get("TELEGRAM_TOKEN","").strip()
CHAT_ID = os.environ.get("CHAT_ID","").strip()

SIMBOLI = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
PRE_SOGLIA = 0.2
SOGLIA = 1.0

def get_price(symbol):
    try:
        url = f"https://data-api.binance.vision/api/v3/ticker/price?symbol={symbol}"
        r = requests.get(url, timeout=10)
        return float(r.json()['price'])
    except Exception as e:
        print(f"Errore prezzo {symbol}: {e}")
        return None

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": msg}
        resp = requests.post(url, data=data, timeout=10)
        # QUESTO è il fix: controlla cosa risponde Telegram
        print(f"Telegram API {resp.status_code} -> {resp.text[:300]}")
        if resp.status_code!= 200:
            print(f"ERRORE INVIO: {msg}")
        else:
            print(f"Inviato OK: {msg}")
    except Exception as e:
        print(f"Eccezione telegram: {e}")

@app.route("/")
def home(): return "Bot 0.2% / 1% online"

@app.route("/test")
def test():
    send_telegram("Test manuale dal bot - se leggi questo, Telegram funziona ✅")
    return "test inviato, guarda i log"

def loop_bot():
    last = {}
    pre_sent = {}
    msg = "Bot partito FIX ✅\nPre 0.2% / Allarme 1%\n"
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
            if not price or s not in last: continue
            var = ((price - last[s]) / last[s]) * 100
            abs_var = abs(var)

            if abs_var >= SOGLIA:
                send_telegram(f"🚨 ALLARME {s}: ${price:,.2f} ({var:+.2f}%)")
                last[s] = price
                pre_sent[s] = False
            elif abs_var >= PRE_SOGLIA and not pre_sent[s]:
                send_telegram(f"⚠️ PRE {s}: ${price:,.2f} ({var:+.2f}%)")
                pre_sent[s] = True
            elif abs_var < 0.1:
                pre_sent[s] = False

        time.sleep(60)

threading.Thread(target=loop_bot, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
