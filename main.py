import os, time, threading, requests
from flask import Flask, jsonify
app = Flask(__name__)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
@app.route("/")
def home():
    return jsonify({"status":"ok"})
@app.route("/health")
def health():
    return jsonify({"status":"healthy"})
def check_btc():
    while True:
        try:
            r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=10).json()
            price = r["price"]
            msg = f"BTC: ${float(price):,.2f}"
            if TELEGRAM_TOKEN and CHAT_ID:
                requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={msg}")
            print(msg)
        except Exception as e:
            print(e)
        time.sleep(300)
threading.Thread(target=check_btc, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
