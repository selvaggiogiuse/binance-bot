import os
import time
import threading
import requests
from flask import Flask
from datetime import datetime, timedelta
from statistics import mean

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or "8929501488:AAHOiVk16EjOVefpLRLVYRQgxdeBgzctxkY"
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "423945798"

SYMBOLS = ["BTCEUR", "ETHEUR", "SOLEUR"]
KRAKEN_URL = "https://api.kraken.com/0/public/OHLC"
KRAKEN_PAIRS = {"BTCEUR":"XXBTZEUR","ETHEUR":"XETHZEUR","SOLEUR":"SOLEUR"}
GIORNI_STORICO = 14

app = Flask(__name__)
LOGS = []
bot_thread = None

storico_cache = {}
CACHE_TTL = 3600  # 1 ora

def log_msg(msg):
    t = datetime.now().strftime("%H:%M:%S")
    entry = f"[{t}] {msg}"
    print(entry, flush=True)
    LOGS.append(entry)
    if len(LOGS) > 500:
        LOGS.pop(0)

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=15)
        log_msg(f"TG API -> {r.status_code}")
        if r.status_code != 200:
            log_msg(f"TG errore: {r.text[:400]}")
        return r
    except Exception as e:
        log_msg(f"TG exception: {e}")
        return None

def get_klines_kraken(symbol, interval_str, limit=50):
    pair = KRAKEN_PAIRS.get(symbol, symbol)
    interval = 1 if interval_str == "1m" else 5
    try:
        r = requests.get(KRAKEN_URL, params={"pair": pair, "interval": interval}, timeout=15)
        data = r.json()
        if data.get("error") and len(data["error"]) > 0:
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

def fetch_storico_kraken(symbol, interval_str, giorni=GIORNI_STORICO):
    cache_key = f"{symbol}_{interval_str}_{giorni}"
    now = time.time()
    if cache_key in storico_cache:
        data, ts = storico_cache[cache_key]
        if now - ts < CACHE_TTL:
            return data

    log_msg(f"Scarico {giorni}gg {symbol} {interval_str} - solo 1 volta/ora...")
    pair = KRAKEN_PAIRS.get(symbol, symbol)
    interval = 1 if interval_str == "1m" else 5
    candele_giorno = 1440 if interval_str == "1m" else 288
    tot_candele = giorni * candele_giorno
    tutto = []
    since = int(now - giorni*24*3600)

    while len(tutto) < tot_candele:
        params = {"pair": pair, "interval": interval, "since": since}
        try:
            r = requests.get(KRAKEN_URL, params=params, timeout=20)
            data = r.json()
            if data.get("error") and len(data["error"]) > 0:
                break
            result = data.get("result", {})
            klines = []
            last_ts = None
            for k,v in result.items():
                if k == "last":
                    last_ts = v
                else:
                    klines = v
            if not klines:
                break
            conv = [[c[0]*1000,c[1],c[2],c[3],c[4],c[6]] for c in klines]
            tutto.extend(conv)
            if last_ts is None:
                break
            since = int(last_ts)
            if len(klines) < 100:
                break
            time.sleep(0.3)
        except Exception as e:
            log_msg(f"Err storico {symbol}: {e}")
            break

    tutto = sorted(tutto, key=lambda x: x[0])[-tot_candele:]
    storico_cache[cache_key] = (tutto, now)
    log_msg(f"Storico {symbol} {interval_str} caricato: {len(tutto)} candele")
    return tutto

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

def get_rsi_label(rsi):
    if rsi<30: return "IPERVENDUTO"
    if rsi>70: return "IPERCOMPRATO"
    return "NEUTRO"

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

def get_storico_stats(klines_lunghi, rsi_now, vol_now, candele_dopo=5, giorni=GIORNI_STORICO, interval="1m"):
    if len(klines_lunghi) < 200:
        return f"Storico {giorni}gg: in caricamento..."
    simili=[]
    for i in range(100, len(klines_lunghi)-candele_dopo-1):
        finestra=klines_lunghi[i-30:i]
        rsi_pass=calc_rsi(finestra)
        vol_pass=get_vol_label(finestra)
        if abs(rsi_pass-rsi_now)<3.5 and vol_pass==vol_now:
            try:
                p_ora=float(klines_lunghi[i][4])
                p_dopo=float(klines_lunghi[i+candele_dopo][4])
                simili.append((p_dopo-p_ora)/p_ora*100)
            except: continue
    if len(simili)<5:
        return f"Storico {giorni}gg ({len(simili)} casi): dati insufficienti"
    media=mean(simili)
    sopra=len([x for x in simili if x>0])
    minuti_dopo=candele_dopo if interval=="1m" else candele_dopo*5
    up=len([x for x in simili if x>0.05])
    down=len([x for x in simili if x<-0.05])
    flat=len(simili)-up-down
    pct_up=up/len(simili)*100
    pct_down=down/len(simili)*100
    pct_flat=flat/len(simili)*100
    if pct_up>=60: segnale="🟢 SALE"
    elif pct_down>=60: segnale="🔻 SCENDE"
    elif pct_flat>=50: segnale="➡️ FLAT"
    else: segnale="🔀 INCERTO"
    base=f"Storico {giorni}gg ({len(simili)} casi): {media:+.2f}% dopo {minuti_dopo}m | {sopra/len(simili)*100:.0f}% sopra | "
    extra=f"{segnale} {pct_up:.0f}%↑ {pct_down:.0f}%↓ {pct_flat:.0f}%→"
    return base+extra

def genera_messaggio(interval):
    now_str = datetime.now().strftime("%H:%M:%S")
    msg = f"⏱️ AGG {interval} - {now_str} (Kraken EUR)\n"
    for sym in SYMBOLS:
        klines=get_klines_kraken(sym, interval, 50)
        if len(klines)<10: continue
        prezzo=float(klines[-1][4])
        var=(prezzo-float(klines[-6][4]))/float(klines[-6][4])*100 if len(klines)>=6 else 0
        trend=get_trend(klines)
        rsi=calc_rsi(klines)
        rsi_lbl=get_rsi_label(rsi)
        vol=get_vol_label(klines)
        klines_lunghi=fetch_storico_kraken(sym, interval, GIORNI_STORICO)
        storico_txt=get_storico_stats(klines_lunghi, rsi, vol, 5, GIORNI_STORICO, interval)
        nome=sym.replace("EUR","")
        msg+=f"\n{nome}: {prezzo:,.2f}€ ({var:+.2f}%) ➡️ {trend} | {vol} | RSI {rsi:.1f} {rsi_lbl}\n"
        msg+=f"  └─ 📊 {storico_txt}\n"
    return msg

def loop_bot():
    log_msg("Bot V9.5 CACHE avviato - carico storico iniziale...")
    # Carico iniziale 1 volta sola
    for sym in SYMBOLS:
        fetch_storico_kraken(sym, "1m", GIORNI_STORICO)
        fetch_storico_kraken(sym, "5m", GIORNI_STORICO)
    log_msg("Storico iniziale caricato - parto con allineamento")
    send_telegram("✅ Bot V9.5 CACHE partito!\nStorico 14gg caricato, ora messaggi veloci alle :05 con storico dentro.")

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
            log_msg(f"[1m] Inviato {ora.strftime('%H:%M:%S')}")
            if ora.minute%5==0 and ora.minute!=ultimo_5m:
                time.sleep(1)
                m5=genera_messaggio("5m")
                send_telegram(m5)
                ultimo_5m=ora.minute
                log_msg(f"[5m] Inviato {ora.strftime('%H:%M:%S')}")
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
    return f"Bot vivo - /log",200

@app.route("/log")
def show_log():
    return "<br>".join(LOGS[-400:])

bot_thread=threading.Thread(target=loop_bot,daemon=True)
bot_thread.start()

if __name__=="__main__":
