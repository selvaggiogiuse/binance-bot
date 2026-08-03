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
KRAKEN_PAIRS = {"BTCEUR": "XXBTZEUR", "ETHEUR": "XETHZEUR", "SOLEUR": "SOLEUR"}
GIORNI_STORICO = 30 # V10: più storico = più casi
MIN_CASI = 25

app = Flask(__name__)
LOGS = []
bot_thread = None
storico_cache = {}
CACHE_TTL = 3600

def log_msg(msg):
    t = datetime.now().strftime("%H:%M:%S")
    entry = f"[{t}] {msg}"
    print(entry, flush=True)
    LOGS.append(entry)
    if len(LOGS) > 500: LOGS.pop(0)

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=15)
        log_msg(f"TG API -> {r.status_code}")
        return r
    except Exception as e:
        log_msg(f"TG exception: {e}")
        return None

def get_klines_kraken(symbol, interval_str, limit=80):
    pair = KRAKEN_PAIRS.get(symbol, symbol)
    interval = 1 if interval_str == "1m" else 5
    try:
        r = requests.get(KRAKEN_URL, params={"pair": pair, "interval": interval}, timeout=15)
        data = r.json()
        if data.get("error") and len(data["error"]) > 0: return []
        result = data.get("result", {})
        klines = []
        for k, v in result.items():
            if k!= "last": klines = v; break
        conv = [[c[0]*1000, c[1], c[2], c[3], c[4], c[6]] for c in klines]
        return conv[-limit:]
    except Exception as e:
        log_msg(f"Err klines {symbol}: {e}")
        return []

def fetch_storico_kraken(symbol, interval_str, giorni=GIORNI_STORICO):
    cache_key = f"{symbol}_{interval_str}_{giorni}"
    now = time.time()
    if cache_key in storico_cache:
        data, ts = storico_cache[cache_key]
        if now - ts < CACHE_TTL: return data
    log_msg(f"Scarico {giorni}gg {symbol} {interval_str}...")
    pair = KRAKEN_PAIRS.get(symbol, symbol)
    interval = 1 if interval_str == "1m" else 5
    candele_giorno = 1440 if interval_str == "1m" else 288
    tot_candele = giorni * candele_giorno
    tutto = []
    since = int(now - giorni*24*3600)
    while len(tutto) < tot_candele:
        try:
            r = requests.get(KRAKEN_URL, params={"pair": pair, "interval": interval, "since": since}, timeout=20)
            data = r.json()
            if data.get("error") and len(data["error"]) > 0: break
            result = data.get("result", {})
            klines = []; last_ts = None
            for k, v in result.items():
                if k == "last": last_ts = v
                else: klines = v
            if not klines: break
            conv = [[c[0]*1000, c[1], c[2], c[3], c[4], c[6]] for c in klines]
            tutto.extend(conv)
            if last_ts is None: break
            since = int(last_ts)
            if len(klines) < 100: break
            time.sleep(0.3)
        except Exception as e:
            log_msg(f"Err storico {symbol}: {e}"); break
    tutto = sorted(tutto, key=lambda x: x[0])[-tot_candele:]
    storico_cache[cache_key] = (tutto, now)
    log_msg(f"Storico {symbol} {interval_str} caricato: {len(tutto)}")
    return tutto

def calc_rsi(klines, period=14):
    try:
        closes = [float(k[4]) for k in klines]
        if len(closes) < period+1: return 50.0
        gains=[]; losses=[]
        for i in range(1, period+1):
            diff = closes[-i] - closes[-i-1]
            gains.append(max(diff,0)); losses.append(max(-diff,0))
        avg_g=sum(gains)/period; avg_l=sum(losses)/period
        if avg_l==0: return 100.0
        return 100 - (100/(1+avg_g/avg_l))
    except: return 50.0

def calc_ema(closes, period):
    try:
        if len(closes)<period: return mean(closes) if closes else 0
        k=2/(period+1)
        ema=mean(closes[:period])
        for price in closes[period:]: ema=price*k + ema*(1-k)
        return ema
    except: return closes[-1] if closes else 0

def calc_atr(klines, period=14):
    try:
        trs=[]
        for i in range(1,len(klines)):
            high=float(klines[i][2]); low=float(klines[i][3]); prev=float(klines[i-1][4])
            trs.append(max(high-low, abs(high-prev), abs(low-prev)))
        return mean(trs[-period:]) if len(trs)>=period else mean(trs) if trs else 0
    except: return 0

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

def trend_cat(trend):
    if "RIALZO" in trend: return "UP"
    if "RIBASSO" in trend: return "DOWN"
    return "FLAT"

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

def get_storico_stats(klines_lunghi, rsi_now, vol_now, candele_dopo=5, giorni=GIORNI_STORICO, interval="1m", klines_now=None, trend_now=None):
    if len(klines_lunghi)<200: return f"Storico {giorni}gg: in caricamento..."
    if vol_now=="zZ VOL BASSO": return f"Storico {giorni}gg: VOL BASSO -> SKIP"
    if klines_now is None or trend_now is None:
        klines_now=klines_lunghi[-50:]; trend_now=get_trend(klines_now)
    try:
        closes_now=[float(k[4]) for k in klines_now]
        prezzo_now=closes_now[-1]
        ema50_now=calc_ema(closes_now,50)
        atr_now=calc_atr(klines_now,14)
        atr_perc_now=(atr_now/prezzo_now*100) if prezzo_now!=0 else 0.15
        ema_side_now="sopra" if prezzo_now>ema50_now else "sotto"
        soglia_flat_now=max(0.08, atr_perc_now*0.4)
        if 47<rsi_now<53 and trend_now=="FLAT": return f"Storico {giorni}gg: RSI neutro + FLAT -> SKIP"
    except Exception as e: return f"Storico {giorni}gg: errore {e}"

    simili=[]; trend_cat_now=trend_cat(trend_now)
    for i in range(100, len(klines_lunghi)-candele_dopo-1):
        finestra=klines_lunghi[i-50:i]
        if len(finestra)<50: continue
        try:
            rsi_pass=calc_rsi(finestra)
            vol_pass=get_vol_label(finestra)
            if vol_pass=="zZ VOL BASSO": continue
            if abs(rsi_pass-rsi_now)>2.5: continue
            trend_pass=get_trend(finestra)
            if trend_cat(trend_pass)!=trend_cat_now: continue
            closes_pass=[float(k[4]) for k in finestra]
            ema50_pass=calc_ema(closes_pass,50)
            ema_side_pass="sopra" if closes_pass[-1]>ema50_pass else "sotto"
            if ema_side_pass!=ema_side_now: continue
            atr_pass=calc_atr(finestra,14)
            atr_perc_pass=(atr_pass/closes_pass[-1]*100) if closes_pass[-1]!=0 else 0
            if atr_perc_now>0 and abs(atr_perc_pass-atr_perc_now)>atr_perc_now*0.7: continue
            p_ora=float(klines_lunghi[i][4]); p_dopo=float(klines_lunghi[i+candele_dopo][4])
            simili.append((p_dopo-p_ora)/p_ora*100)
        except: continue

    if len(simili)<MIN_CASI: return f"Storico {giorni}gg ({len(simili)} casi): DATI INSUFFICIENTI -> SKIP"

    media=mean(simili)
    minuti_dopo=candele_dopo if interval=="1m" else candele_dopo*5
    up=len([x for x in simili if x>soglia_flat_now])
    down=len([x for x in simili if x<-soglia_flat_now])
    flat=len(simili)-up-down
    pct_up=up/len(simili)*100; pct_down=down/len(simili)*100; pct_flat=flat/len(simili)*100
    sopra=len([x for x in simili if x>0])

    confidenza="C"; forza=""
    if len(simili)>=30 and abs(media)>=0.15:
        if pct_up>=70 or pct_down>=70: confidenza="A"; forza=" FORTE"
        elif pct_up>=65 or pct_down>=65: confidenza="B"; forza=" BUONO"
    elif len(simili)>=25 and (pct_up>=65 or pct_down>=65) and abs(media)>=0.12: confidenza="B"

    if pct_up>=60: segnale=f"SALE{forza}"
    elif pct_down>=60: segnale=f"SCENDE{forza}"
    elif pct_flat>=50: segnale=f"FLAT"
    else: segnale=f"INCERTO"

    base=f"{giorni}gg ({len(simili)} casi): {media:+.2f}% dopo {minuti_dopo}m | {sopra/len(simili)*100:.0f}% sopra | soglia {soglia_flat_now:.2f}%"
    extra=f"{segnale} {pct_up:.0f}%up {pct_down:.0f}%down {pct_flat:.0f}%flat | Conf {confidenza} | EMA50 {ema_side_now} | {trend_now}"
    extra+=" -> ENTRA" if confidenza=="A" else " -> ENTRA cautela" if confidenza=="B" else " -> SKIP"
    return base+" | "+extra

def genera_messaggio(interval):
    now_str=datetime.now().strftime("%H:%M:%S")
    msg=f"AGG {interval} - {now_str} (Kraken EUR) [V10]\n"
    for sym in SYMBOLS:
        klines=get_klines_kraken(sym, interval, 80)
        if len(klines)<50: continue
        prezzo=float(klines[-1][4])
        var=(prezzo-float(klines[-6][4]))/float(klines[-6][4])*100 if len(klines)>=6 else 0
        trend=get_trend(klines); rsi=calc_rsi(klines); rsi_lbl=get_rsi_label(rsi); vol=get_vol_label(klines)
        closes=[float(k[4]) for k in klines]; ema50=calc_ema(closes,50); atr=calc_atr(klines,14)
        atr_perc=(atr/prezzo*100) if prezzo else 0
        ema_side="sopra EMA50" if prezzo>ema50 else "sotto EMA50"
        klines_lunghi=fetch_storico_kraken(sym, interval, GIORNI_STORICO)
        storico_txt=get_storico_stats(klines_lunghi, rsi, vol, 5, GIORNI_STORICO, interval, klines_now=klines, trend_now=trend)
        nome=sym.replace("EUR","")
        msg+=f"\n{nome}: {prezzo:,.2f}E ({var:+.2f}%) {trend} | {vol} | RSI {rsi:.1f} {rsi_lbl} | {ema_side} | ATR {atr_perc:.2f}%\n"
        msg+=f" └─ {storico_txt}\n"
        if interval=="1m":
            klines_5m=get_klines_kraken(sym, "5m", 50)
            if klines_5m:
                trend_5m=get_trend(klines_5m)
                if trend_cat(trend)!=trend_cat(trend_5m) and trend!="FLAT" and trend_5m!="FLAT":
                    msg+=f" CONFLITTO: 1m {trend} vs 5m {trend_5m} -> SKIP\n"
                elif trend_cat(trend)==trend_cat(trend_5m) and trend!="FLAT":
                    msg+=f" ALLINEATO con 5m ({trend_5m})\n"
    return msg

def loop_bot():
    log_msg("Bot V10 PRECISIONE avviato - 30gg...")
    for sym in SYMBOLS:
        fetch_storico_kraken(sym, "1m", GIORNI_STORICO)
        fetch_storico_kraken(sym, "5m", GIORNI_STORICO)
    log_msg("Storico caricato")
    send_telegram("Bot V10 PRECISIONE partito! 30gg | EMA + ATR dinamico + min 25 casi + doppia conferma 1m/5m | Conf A/B/C")
    ultimo_5m=-1
    def aspetta():
        ora=datetime.now()
        prossimo=(ora+timedelta(minutes=1)).replace(second=5, microsecond=0)
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
            log_msg(f"Loop err: {e}"); time.sleep(10)

@app.route("/")
def home():
    global bot_thread
    if bot_thread is None or not bot_thread.is_alive():
        bot_thread=threading.Thread(target=loop_bot, daemon=True)
        bot_thread.start()
        return "Bot riavviato", 200
    return f"Bot V10 vivo - /log", 200

@app.route("/log")
def show_log():
    return "<br>".join(LOGS[-400:])

bot_thread=threading.Thread(target=loop_bot, daemon=True)
bot_thread.start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
