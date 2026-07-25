import os
import time
import threading
import requests
from flask import Flask

app = Flask(__name__)

# --- CONFIG ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SOGLIA = 1.0 # 1% = ti avvisa solo se si muove di almeno 1%

ultimo_prezzo = None

def get_btc_price():
    url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
    r = requests.get(url, timeout=10)
    return float(r.json()["price"])

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg})

def bot_loop():
    global ultimo_prezzo
    while True:
        try:
            prezzo = get_btc_price()
            if ultimo_prezzo is None:
                send_telegram(f"Bot partito ✅ BTC: {prezzo:.2f}$")
                ultimo_prezzo = prezzo
            else:
                variazione = (prezzo - ultimo_prezzo) / ultimo_prezzo * 100
                if abs(variazione) >= SOGLIA:
                    send_telegram(f"BTC: {prezzo:.2f}$ ({variazione:+.2f}%)")
                    ultimo_prezzo = prezzo
                else:
                    print(f"Variazione piccola {variazione:.2f}% - non invio")
        except Exception as e:
            print(f"Errore: {e}")
        
        time.sleep(900) # controlla ogni 15 min

@app.route("/")
def home():
    return "Bot is alive"

@app.route("/health")
def health():
    return "ok"

# fa partire il bot in background
threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
