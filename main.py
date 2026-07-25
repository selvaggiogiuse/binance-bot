import os, time, threading, requests
from flask import Flask

app = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT = os.getenv("TELEGRAM_CHAT_ID")

def check_btc():
    time.sleep(10)
    print("BOT LOOP PARTITO")
    while True:
        try:
            r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=10).json()
            price = r.get("price")
            print(f"Prezzo preso: {price}")
            if price and TOKEN and CHAT:
                msg = f"BTC: ${float(price):,.2f}"
                requests.get(f"https://api.telegram.org/bot{TOKEN}/sendMessage?chat_id={CHAT}&text={msg}", timeout=10)
                print(f"Inviato: {msg}")
        except Exception as e:
            print(f"ERRORE: {e}")
        time.sleep(60)

@app.route("/")
def home():
    return "OK"

@app.route("/health")
def health():
    return "ok", 200

# QUESTA RIGA ORA È FUORI, così parte anche con gunicorn
threading.Thread(target=check_btc, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
