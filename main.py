import os, time, threading, requests
from flask import Flask

app = Flask(__name__)
TOKEN = os.environ.get("TELEGRAM_TOKEN","").strip()
CHAT_ID = os.environ.get("CHAT_ID","").strip()

SIMBOLI = ["BTCEUR", "ETHEUR", "SOLEUR"]

# SETUP PER TE
PRE_SOGLIA = 0.2 # solo info
SOGLIA = 0.8 # allarme normale
SOGLIA_FORTE = 2.0 # allarme forte

def get_display(symbol):
    return symbol.replace("EUR","")

def get_price(symbol):
    try:
        url = f"https://api.kraken.com/0/public/Ticker?pair={symbol}"
        r = requests.get(url, timeout=10).json()
        ticker_key = list(r['result'].keys())[0]
        return float(r['result'][ticker_key]['c'][0])
    except Exception as e:
        print(f"Errore prezzo {symbol}: {e}")
        return None

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print(f"Errore telegram: {e}")

@app.route("/")
def home(): return "Bot KRAKEN 0.2 / 0.8 / 2.0 online"

@app.route("/test")
def test():
    send_telegram("Test Bot 0.2/0.8/2.0 ✅")
    return "test inviato"

def loop_bot():
    last = {}
    pre_sent = {}
    msg = "Bot KRAKEN EURO 0.2/0.8/2.0 partito ✅\n"
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
            display = get_display(s)

            if abs_var >= SOGLIA_FORTE:
                direzione = "📈 RIALZO" if var > 0 else "📉 RIBASSO"
                azione = "Vendi 50%" if var > 0 else "Compra 50%"
                send_telegram(f"🚨🚨 FORTE {display}: {price:,.2f} € ({var:+.2f}%) {direzione}\n💡 RISCHIO MEDIO: {azione}. Movimento importante!")
                last[s] = price
                pre_sent[s] = False

            elif abs_var >= SOGLIA:
                direzione = "📈" if var > 0 else "📉"
                azione = "Vendi 30% - Tieni 70%" if var > 0 else "Compra 30%"
                send_telegram(f"🚨 ALLARME {display}: {price:,.2f} € ({var:+.2f}%) {direzione}\n💡 RISCHIO BASSO: {azione}")
                last[s] = price
                pre_sent[s] = False

            elif abs_var >= PRE_SOGLIA and not pre_sent[s]:
                send_telegram(f"⚠️ PRE {display}: {price:,.2f} € ({var:+.2f}%)\n💡 Solo INFO - monitora, non serve agire")
                pre_sent[s] = True

            elif abs_var < 0.1:
                pre_sent[s] = False

        time.sleep(60)

threading.Thread(target=loop_bot, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
