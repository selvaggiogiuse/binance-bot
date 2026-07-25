import os, time, threading, requests
from flask import Flask

app = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT = os.getenv("TELEGRAM_CHAT_ID")

@app.route("/")
def home():
    return "OK"

@app.route("/health")
def health():
    return "ok", 200

def check_btc():
    while True:
        try:
            r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=10).json()
            price = r.get("price")
            if price and TOKEN and CHAT:
                msg = f"BTC: ${float(price):,.2f}"
                requests.get(f"https://api.telegram.org/bot{TOKEN}/sendMessage?chat_id={CHAT}&text={msg}", timeout=10)
                print(msg)
        except Exception as e:
            print(e)
        time.sleep(60)

threading.Thread(target=check_btc, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
