import os
import time
import threading
import requests
from flask import Flask
from datetime import datetime, timedelta
from statistics import mean

# Usa variabili Render se ci sono, altrimenti quelli vecchi
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or "8929501488:AAHOiVk16EjOVefpLRLVYRQgxdeBgzctxkY"
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "423945798"

SYMBOLS = ["BTCEUR", "ETHEUR", "SOLEUR"]
KRAKEN_URL = "https://api.kraken.com/0/public/OHLC"
KRAKEN_PAIRS = {"BTCEUR":"XXBTZEUR","ETHEUR":"XETHZEUR","SOLEUR":"SOLEUR"}

app = Flask(__name__)
LOGS = []
bot_thread = None

def log_msg(msg):
    t = datetime.now().strftime("%H:%M:%S")
    entry = f"[{t}] {msg}"
    print(entry, flush=True)
    LOGS.append(entry)
    if len(LOGS) > 400:
        LOGS.pop(0)

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=15)
        log_msg(f"TG API -> {r.status_code} | {r.text[:300]}")
        return r
    except Exception as e:
        log_msg(f"TG error: {e}")
        return None

def get_klines_kraken(symbol, interval_str, limit=50):
    pair = KRAKEN_PAIRS.get(symbol, symbol)
    interval = 1 if interval_str == "1m" else 5
    try:
        r = requests.get(KRAKEN_URL, params={"pair": pair, "interval": interval}, timeout=15)
        data = r.json()
        if data.get("error") and len(data["error"]) > 0:
            log_msg(f"Kraken err {symbol}: {data['error']}")
            return []
        result = data.get("result", {})
        klines = []
        for k,v in result.items():
            if k != "last":
                klines = v
                break
        conv = [[c[0]*1000,c[1],c[2],c[3],c[4],c[6]] for c in klines]
        return conv[-limit:]
    except Exception as e:
        log_msg(f"Err klines {symbol}: {e}")
        return []

def calc_rsi(klines, period=14):
    try:
        closes=[float(k[4]) for k in klines]
        if len(closes)<period+1: return 50.0
        gains=[];losses=[]
        for i in range(1,period+1):
            diff=closes[-i]-closes[-i-1]
            gains.append(max(diff,0));losses.append(max(-diff,0))
        avg_g=sum(gains)/period; avg_l=sum(losses)/period
        if avg_l==0: return 100.0
        return 100-(100/(1+avg_g/avg_l))
    except: return 50.0

def get_trend(klines):
    try:
        closes=[float(k[4]) for k in klines[-10:]]
        var=(closes[-1]-closes[0])/closes[0]*100
        if var>0.5: return "RIALZO"
        if var>0.15: return "RIALZO DEBOLE"
        if var<-0.5: return "RIBASSO"
        if var<-0.15: return "RIBASSO DEBOLE"
        return "FLAT"
    except: return "FLAT"

def get_vol_label(klines):
    try:
        vols=[float(k[5]) for k in klines[-21:]]
        if len(vols)<21: return "VOL NORMALE"
        curr=vols[-1]; avg=mean(vols[:-1])
        if avg==0: return "VOL NORMALE"
        if curr<avg*0.5: return "zZ VOL BASSO"
        if curr>avg*2.0: return "VOL ALTO"
        return "VOL NORMALE"
    except: return "VOL NORMALE"

def genera_messaggio(interval):
    now_str = datetime.now().strftime("%H:%M:%S")
    msg = f"⏱️ AGG {interval} - {now_str} (Kraken EUR)\n"
    for sym in SYMBOLS:
        k=get_klines_kraken(sym, interval, 50)
        if len(k)<10: continue
        prezzo=float(k[-1][4])
        var=(prezzo-float(k[-6][4]))/float(k[-6][4])*100 if len(k)>=6 else 0
        msg+=f"\n{sym.replace('EUR','')}: {prezzo:,.2f}€ ({var:+.2f}%) -> {get_trend(k)} | {get_vol_label(k)} | RSI {calc_rsi(k):.0f}\n"
    return msg

def loop_bot():
    log_msg("Bot V9.4 LEGGERO ALLINEATO avviato")
    send_telegram("✅ TEST - Bot V9.4 allineato partito! Se leggi questo, Telegram funziona. Prossimo AGG alle :05")
    ultimo_5m=-1
    def aspetta():
        ora=datetime.now()
        prossimo=(ora+timedelta(minutes=1)).replace(second=5,microsecond=0)
        attesa=(prossimo-ora).total_seconds()
        if attesa>0: time.sleep(attesa)
    while True:
        try:
            aspetta()
            ora=datetime.now()
            m1=genera_messaggio("1m")
            send_telegram(m1)
            log_msg(f"[1m] Inviato alle {ora.strftime('%H:%M:%S')}")
            if ora.minute%5==0 and ora.minute!=ultimo_5m:
                time.sleep(1)
                m5=genera_messaggio("5m")
                send_telegram(m5)
                ultimo_5m=ora.minute
                log_msg(f"[5m] Inviato alle {ora.strftime('%H:%M:%S')}")
        except Exception as e:
            log_msg(f"Loop err: {e}")
            time.sleep(10)

@app.route("/")
def home():
    global bot_thread
    if bot_thread is None or not bot_thread.is_alive():
        bot_thread=threading.Thread(target=loop_bot,daemon=True)
        bot_thread.start()
        return "Bot riavviato",200
    return f"Bot vivo - logs: /log",200

@app.route("/log")
def show_log():
    return "<br>".join(LOGS[-300:])

bot_thread=threading.Thread(target=loop_bot,daemon=True)
bot_thread.start()

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",10000)))
