
import os
import time
import threading
import requests
from flask import Flask
from datetime import datetime, timedelta
from statistics import mean
try:
    from zoneinfo import ZoneInfo
    TZ_ITALY = ZoneInfo("Europe/Rome")
except:
    TZ_ITALY = None

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or "8929501488:AAHOiVk16EjOVefpLRLVYRQgxdeBgzctxkY"
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "423945798"

# Per iniziare meglio USDT (piu volume), poi puoi rimettere EUR
SYMBOLS = ["BTCEUR", "ETHEUR", "SOLEUR"]
BINANCE_KLINES = "https://data-api.binance.vision/api/v3/klines"
BINANCE_KLINES2 = "https://api1.binance.com/api/v3/klines"
GIORNI_STORICO = 7  # per scalping bastano 7 giorni, cosi e piu reattivo
MIN_CASI_START = 10  # prima era 25, ora 10 per farti avere piu segnali

app = Flask(__name__)
LOGS = []
bot_thread = None
storico_cache = {}
CACHE_TTL = 1800

def now_italy():
    return datetime.now(TZ_ITALY) if TZ_ITALY else datetime.now()

def log_msg(msg):
    t = now_italy().strftime("%H:%M:%S")
    entry = f"[{t}] {msg}"
    print(entry, flush=True)
    LOGS.append(entry)
    if len(LOGS) > 400:
        LOGS.pop(0)

def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        log_msg(f"TG err {e}")

def get_klines_binance(symbol, interval, limit=100):
    for base in [BINANCE_KLINES, BINANCE_KLINES2]:
        try:
            r = requests.get(f"{base}?symbol={symbol}&interval={interval}&limit={limit}", timeout=10).json()
            if isinstance(r, list) and len(r) >= 10:
                return r
        except:
            continue
    return []

def fetch_storico_binance(symbol, interval, giorni=7):
    cache_key = f"{symbol}_{interval}_{giorni}"
    now = time.time()
    if cache_key in storico_cache:
        data, ts = storico_cache[cache_key]
        if now - ts < CACHE_TTL:
            return data
    # Scarico fino a 5000 candele per avere storico
    all_klines = []
    end_time = int(now*1000)
    for _ in range(5):  # 5 x 1000 = 5000 candele
        try:
            url = f"{BINANCE_KLINES}?symbol={symbol}&interval={interval}&limit=1000&endTime={end_time}"
            r = requests.get(url, timeout=15).json()
            if not isinstance(r, list) or len(r)==0:
                break
            all_klines = r + all_klines
            end_time = int(r[0][0]) - 1
            if len(r) < 1000:
                break
            time.sleep(0.2)
        except:
            break
    storico_cache[cache_key] = (all_klines, now)
    log_msg(f"Storico {symbol} {interval} caricato: {len(all_klines)}")
    return all_klines

def calc_rsi_klines(klines, period=14):
    try:
        closes = [float(k[4]) for k in klines]
        if len(closes) < period+1:
            return 50.0
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
        for p in closes[period:]: ema=p*k+ema*(1-k)
        return ema
    except: return closes[-1] if closes else 0

def calc_atr(klines, period=14):
    try:
        trs=[]
        for i in range(1,len(klines)):
            h=float(klines[i][2]); l=float(klines[i][3]); pc=float(klines[i-1][4])
            trs.append(max(h-l, abs(h-pc), abs(l-pc)))
        return mean(trs[-period:]) if len(trs)>=period else mean(trs) if trs else 0
    except: return 0

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

def trend_cat(t):
    if "RIALZO" in t: return "UP"
    if "RIBASSO" in t: return "DOWN"
    return "FLAT"

def get_vol_label(klines):
    try:
        vols=[float(k[5]) for k in klines[-21:]]
        if len(vols)<21: return "VOL NORMALE"
        curr=vols[-1]; avg=mean(vols[:-1])
        if avg==0: return "VOL NORMALE"
        if curr<avg*0.5: return "VOL BASSO"
        if curr>avg*1.9: return "VOL ALTO"
        return "VOL NORMALE"
    except: return "VOL NORMALE"

def get_storico_stats_start(klines_lunghi, rsi_now, vol_now, trend_now, klines_now, candele_dopo=5):
    """Versione START - molto piu permissiva per chi inizia"""
    if len(klines_lunghi)<200:
        return "Storico: in caricamento...", 0, 0

    try:
        closes_now=[float(k[4]) for k in klines_now]
        prezzo_now=closes_now[-1]
        ema50_now=calc_ema(closes_now,50)
        atr_now=calc_atr(klines_now,14)
        atr_perc_now=(atr_now/prezzo_now*100) if prezzo_now else 0.12
        ema_side_now="sopra" if prezzo_now>ema50_now else "sotto"
        soglia_flat_now=max(0.04, atr_perc_now*0.25)  # prima 0.08, ora 0.04 per prendere anche 0.10%
    except:
        soglia_flat_now=0.05
        ema_side_now="sopra"
        atr_perc_now=0.10

    simili=[]
    trend_cat_now=trend_cat(trend_now)
    # cerchiamo casi simili ma piu larghi
    for i in range(100, len(klines_lunghi)-candele_dopo-1):
        finestra=klines_lunghi[i-50:i]
        if len(finestra)<50: continue
        try:
            rsi_pass=calc_rsi_klines(finestra)
            if abs(rsi_pass-rsi_now)>4.0: continue  # prima 2.5, ora 4.0 piu largo
            trend_pass=get_trend(finestra)
            if trend_cat(trend_pass)!=trend_cat_now and trend_cat_now!="FLAT":
                # permettiamo anche FLAT passato
                if trend_cat(trend_pass)=="FLAT" and trend_cat_now in ["UP","DOWN"]:
                    pass
                elif trend_cat_now=="FLAT":
                    pass
                else:
                    continue
            closes_pass=[float(k[4]) for k in finestra]
            ema50_pass=calc_ema(closes_pass,50)
            ema_side_pass="sopra" if closes_pass[-1]>ema50_pass else "sotto"
            if ema_side_pass!=ema_side_now:
                # in START permettiamo anche lato opposto ma con peso minore
                pass
            p_ora=float(klines_lunghi[i][4]); p_dopo=float(klines_lunghi[i+candele_dopo][4])
            simili.append((p_dopo-p_ora)/p_ora*100)
        except: continue

    if len(simili)<MIN_CASI_START:
        return f"{len(simili)} casi: troppo pochi -> INCERTO (aspetto)", 0, soglia_flat_now

    media=mean(simili)
    up=len([x for x in simili if x>soglia_flat_now])
    down=len([x for x in simili if x<-soglia_flat_now])
    flat=len(simili)-up-down
    pct_up=up/len(simili)*100; pct_down=down/len(simili)*100; pct_flat=flat/len(simili)*100

    # Confidenza START - molto piu facile
    if len(simili)>=25 and abs(media)>=0.12 and (pct_up>=65 or pct_down>=65):
        conf="A"; tipo="FORTE"
    elif len(simili)>=15 and abs(media)>=0.08 and (pct_up>=60 or pct_down>=60):
        conf="B"; tipo="BUONO"
    elif len(simili)>=10 and abs(media)>=0.05 and (pct_up>=55 or pct_down>=55):
        conf="C"; tipo="SCALP"  # questo e quello che vuoi tu per iniziare
    else:
        conf="D"; tipo="INCERTO"

    if pct_up>=55: segnale=f"SALE {tipo}"
    elif pct_down>=55: segnale=f"SCENDE {tipo}"
    else: segnale=f"FLAT/INCERTO"

    # Consiglio per START
    if conf in ["A","B"]: consiglio="ENTRA"
    elif conf=="C" and abs(media)>=0.06: consiglio="SCALP veloce"
    else: consiglio="aspetta"

    txt=f"{len(simili)} casi: {media:+.2f}% dopo {candele_dopo*5 if candele_dopo==5 else candele_dopo}m | soglia {soglia_flat_now:.2f}% | {segnale} {pct_up:.0f}%up {pct_down:.0f}%down | Conf {conf} -> {consiglio} | EMA50 {ema_side_now}"
    return txt, media, soglia_flat_now

def genera_messaggio():
    now_str=now_italy().strftime("%H:%M:%S")
    msg=f"AGG 1m/5m - {now_str} [V11 START]\n"
    for sym in SYMBOLS:
        kl_1m=get_klines_binance(sym, "1m", 80)
        kl_5m=get_klines_binance(sym, "5m", 80)
        if not kl_1m or not kl_5m: continue
        prezzo=float(kl_1m[-1][4])
        # variazione ultima candela 5m e ultime 3 da 1m
        var_5m=(float(kl_5m[-1][4])-float(kl_5m[-2][4]))/float(kl_5m[-2][4])*100 if len(kl_5m)>=2 else 0
        var_1m_3=(float(kl_1m[-1][4])-float(kl_1m[-4][4]))/float(kl_1m[-4][4])*100 if len(kl_1m)>=4 else 0
        trend_1m=get_trend(kl_1m); trend_5m=get_trend(kl_5m)
        rsi_1m=calc_rsi_klines(kl_1m); rsi_5m=calc_rsi_klines(kl_5m)
        vol_1m=get_vol_label(kl_1m); vol_5m=get_vol_label(kl_5m)
        closes=[float(k[4]) for k in kl_1m]; ema20=calc_ema(closes,20); ema50=calc_ema(closes,50)
        atr=calc_atr(kl_1m,14); atr_perc=(atr/prezzo*100) if prezzo else 0
        ema_side="sopra EMA50" if prezzo>ema50 else "sotto EMA50"

        # Storico per scalping - 7 giorni
        storico_1m=fetch_storico_binance(sym, "1m", 7)
        storico_5m=fetch_storico_binance(sym, "5m", 7)
        txt_1m, media_1m, soglia_1m = get_storico_stats_start(storico_1m, rsi_1m, vol_1m, trend_1m, kl_1m, candele_dopo=5)
        txt_5m, media_5m, soglia_5m = get_storico_stats_start(storico_5m, rsi_5m, vol_5m, trend_5m, kl_5m, candele_dopo=5)

        # Alert movimento in corso (quello che hai nello screenshot)
        alert=""
        if abs(var_5m)>=0.25:
            alert+=f"\n   ⚡ MOVIMENTO {var_5m:+.2f}% in 5m - ATTENZIONE!"
        if abs(var_1m_3)>=0.20:
            alert+=f"\n   ⚡ SCALP {var_1m_3:+.2f}% in 3m"
        if rsi_1m>70 or rsi_1m<30:
            alert+=f"\n   ⚠️ RSI {rsi_1m:.0f} {'IPERCOMPRATO' if rsi_1m>70 else 'IPERVENDUTO'}"

        nome=sym.replace("USDT","")
        msg+=f"\n{nome}: {prezzo:.2f} ({var_5m:+.2f}% 5m) {trend_1m} | {vol_1m} | RSI {rsi_1m:.0f} | {ema_side} | ATR {atr_perc:.2f}%{alert}\n"
        msg+=f" └─ 1m: {txt_1m}\n"
        msg+=f" └─ 5m: {txt_5m} | Trend 5m: {trend_5m}\n"
        if trend_cat(trend_1m)!=trend_cat(trend_5m) and trend_1m!="FLAT" and trend_5m!="FLAT":
            msg+=f"   CONFLITTO 1m vs 5m, ma in START puoi fare SCALP piccolo\n"
    return msg

def loop_bot():
    log_msg("Bot V11 START partito - modalita scalping per iniziare")
    send_telegram("✅ Bot V11 START partito! Modalita SCALP - ti avviso anche di movimenti +0.10% / +0.25%, VOL BASSO incluso, min 10 casi")
    for s in SYMBOLS:
        fetch_storico_binance(s, "1m", 7)
        fetch_storico_binance(s, "5m", 7)
    while True:
        try:
            m=genera_messaggio()
            send_telegram(m)
            log_msg("Inviato messaggio V11")
            time.sleep(60)
        except Exception as e:
            log_msg(f"Loop err {e}")
            time.sleep(10)

@app.route("/")
def home():
    global bot_thread
    if bot_thread is None or not bot_thread.is_alive():
        bot_thread=threading.Thread(target=loop_bot, daemon=True)
        bot_thread.start()
        return "Bot V11 START riavviato", 200
    return f"Bot V11 vivo - {len(LOGS)} log", 200

@app.route("/log")
def show_log():
    return "<br>".join(LOGS[-300:])

bot_thread=threading.Thread(target=loop_bot, daemon=True)
bot_thread.start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
