import os, time, threading, requests
from flask import Flask

app = Flask(__name__)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT = os.getenv("TELEGRAM_CHAT_ID")

def get_price():
    urls = [
        "https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT",
        "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=10).json()
            print(f"Risposta {url}: {r}")
            if "price" in r:
                return r["price"]
        except Exception as e:
            print(f"Errore {url}: {e}")
    # fallback se Binance non va
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=10).json()
        return str(r["bitcoin"]["usd"])
    except Exception as e:
        print(f"Errore coingecko: {e}")
        return None

def check_btc():
    time.sleep(5)
    print("BOT LOOP PARTITO")
    while True:
        price = get_price()
        print(f"Prezzo preso: {price}")
        if price and TOKEN and CHAT:
            msg = f"BTC: ${float(price):,.2f}"
            requests.get(f"https://api.telegram.org/bot{TOKEN}/sendMessage?chat_id={CHAT}&text={msg}", timeout=10)
            print(f"Inviato: {msg}")
        else:
            print("Non invio: manca price o TOKEN/CHAT")
        time.sleep(300)

@app.route("/")
def home():
    return "OK"

@app.route("/health")
def health():
    return "ok", 200

threading.Thread(target=check_btc, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
