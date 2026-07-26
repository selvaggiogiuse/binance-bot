import os, time, threading, requests
from flask import Flask

app = Flask(__name__)
TOKEN = os.environ.get("TELEGRAM_TOKEN","").strip()
CHAT_ID = os.environ.get("CHAT_ID","").strip()

SIMBOLI = ["BTCEUR", "ETHEUR", "SOLEUR"]
PRE_SOGLIA = 0.2
SOGLIA = 1.0

def get_display(symbol):
    return symbol.replace("EUR","")

def get_price(symbol):
    try:
        # ORA PRENDE DA KRAKEN, NON PIU' DA BINANCE
        url = f"https://api.kraken.com/0/public/Ticker?pair={symbol}"
        r = requests.get(url, timeout=10).json()
        # Kraken risponde con chiave tipo XXBTZEUR
        ticker_key = list(r['result'].keys())[0]
        price = float(r['result'][ticker_key]['c'][0])
        return price
    except Exception as e:
        print(f"Errore prezzo {symbol}: {e}")
        return None

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": msg}
        resp = requests.post(url, data=data, timeout=10)
        print(f"Telegram API {resp.status_code} -> {resp.text[:300]}")
    except Exception as e:
        print(f"Eccezione telegram: {e}")

@app.route("/")
def home(): return "Bot 0.2% / 1% online - KRAKEN EURO"

@app.route("/test")
def test():
    send_telegram("Test KRAKEN EURO ✅ - Se leggi questo funziona")
    return "test inviato"

def loop_bot():
    last = {}
    pre_sent = {}
    msg = "Bot KRAKEN EURO partito ✅\nPre 0.2% / Allarme 1%\n"
    for s in SIMBOLI:
        pr = get_price(s)
        if pr:
            last[s] = pr
            pre_sent[s] = False
            msg += f"{get_display(s)}: {pr:,.2f} €\n"
    send_telegram(msg)

    while True:
        for s in SIMBOLI:
            price = get_price(s)
            if not price or s not in last: continue
            var = ((price - last[s]) / last[s]) * 100
            abs_var = abs(var)

            if abs_var >= SOGLIA:
                send_telegram(f"🚨 ALLARME {get_display(s)}: {price:,.2f} € ({var:+.2f}%)")
                last[s] = price
                pre_sent[s] = False
            elif abs_var >= PRE_SOGLIA and not pre_sent[s]:
                send_telegram(f"⚠️ PRE {get_display(s)}: {price:,.2f} € ({var:+.2f}%)")
                pre_sent[s] = True
            elif abs_var < 0.1:
                pre_sent[s] = False
        time.sleep(60)

threading.Thread(target=loop_bot, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
