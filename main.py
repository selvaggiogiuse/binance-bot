import os
import time
import threading
import requests
from flask import Flask, jsonify, render_template_string
from datetime import datetime
from statistics import mean
try:
    from zoneinfo import ZoneInfo
    TZ_ITALY = ZoneInfo("Europe/Rome")
except:
    TZ_ITALY = None

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or "8929501488:AAHOiVk16EjOVefpLRLVYRQgxdeBgzctxkY"
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "423945798"
SYMBOLS = ["BTCEUR", "ETHEUR", "SOLEUR"]
BINANCE_KLINES = "https://data-api.binance.vision/api/v3/klines"
BINANCE_KLINES2 = "https://api1.binance.com/api/v3/klines"

app = Flask(__name__)
LOGS = []
bot_thread = None
storico_cache = {}
CACHE_TTL = 1800
LAST_SIGNALS = []
MIN_CASI_START = 10

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

def fetch_storico_binance(symbol, interval):
    cache_key = f"{symbol}_{interval}"
    now = time.time()
    if cache_key in storico_cache:
        data, ts = storico_cache[cache_key]
        if now - ts < CACHE_TTL:
            return data
    all_klines = []
    end_time = int(now*1000)
    for _ in range(5):
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
    return all_klines

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

def get_storico_stats(klines_lunghi, rsi_now, trend_now, klines_now, candele_dopo=5):
    if len(klines_lunghi)<200:
        return "In caricamento...", 0, 0, "D"
    try:
        closes_now=[float(k[4]) for k in klines_now]
        prezzo_now=closes_now[-1]
        soglia_flat_now=max(0.04, (calc_atr(klines_now,14)/prezzo_now*100 if prezzo_now else 0.12)*0.25)
    except:
        soglia_flat_now=0.05
    simili=[]
    trend_cat_now=trend_cat(trend_now)
    for i in range(100, len(klines_lunghi)-candele_dopo-1):
        finestra=klines_lunghi[i-50:i]
        if len(finestra)<50: continue
        try:
            rsi_pass=calc_rsi(finestra)
            if abs(rsi_pass-rsi_now)>4.0: continue
            trend_pass=get_trend(finestra)
            if trend_cat(trend_pass)!=trend_cat_now and trend_cat_now!="FLAT":
                if not (trend_cat(trend_pass)=="FLAT" and trend_cat_now in ["UP","DOWN"]):
                    continue
            p_ora=float(klines_lunghi[i][4]); p_dopo=float(klines_lunghi[i+candele_dopo][4])
            simili.append((p_dopo-p_ora)/p_ora*100)
        except: continue
    if len(simili)<MIN_CASI_START:
        return f"{len(simili)} casi -> INCERTO", 0, soglia_flat_now, "D"
    media=mean(simili)
    up=len([x for x in simili if x>soglia_flat_now])
    down=len([x for x in simili if x<-soglia_flat_now])
    pct_up=up/len(simili)*100; pct_down=down/len(simili)*100
    if len(simili)>=25 and abs(media)>=0.12 and (pct_up>=65 or pct_down>=65):
        conf="A"; tipo="FORTE"
    elif len(simili)>=15 and abs(media)>=0.08 and (pct_up>=60 or pct_down>=60):
        conf="B"; tipo="BUONO"
    elif len(simili)>=10 and abs(media)>=0.05 and (pct_up>=55 or pct_down>=55):
        conf="C"; tipo="SCALP"
    else:
        conf="D"; tipo="INCERTO"
    if pct_up>=55: segnale=f"SALE {tipo}"
    elif pct_down>=55: segnale=f"SCENDE {tipo}"
    else: segnale=f"FLAT/INCERTO"
    txt=f"{len(simili)} casi: {media:+.2f}% dopo 25m | {segnale} {pct_up:.0f}%up {pct_down:.0f}%down | Conf {conf}"
    return txt, media, soglia_flat_now, conf

def genera_segnali():
    global LAST_SIGNALS
    now_str=now_italy().strftime("%H:%M:%S")
    msg=f"AGG 1m/5m - {now_str} [V12 EUR APP]\n"
    signals=[]
    for sym in SYMBOLS:
        kl_1m=get_klines_binance(sym, "1m", 80)
        kl_5m=get_klines_binance(sym, "5m", 80)
        if not kl_1m or not kl_5m: continue
        prezzo=float(kl_1m[-1][4])
        var_5m=(float(kl_5m[-1][4])-float(kl_5m[-2][4]))/float(kl_5m[-2][4])*100 if len(kl_5m)>=2 else 0
        trend_1m=get_trend(kl_1m); trend_5m=get_trend(kl_5m)
        rsi_1m=calc_rsi(kl_1m)
        vol_1m=get_vol_label(kl_1m)
        closes=[float(k[4]) for k in kl_1m]; ema50=calc_ema(closes,50)
        atr=calc_atr(kl_1m,14); atr_perc=(atr/prezzo*100) if prezzo else 0
        ema_side="sopra EMA50" if prezzo>ema50 else "sotto EMA50"
        storico_1m=fetch_storico_binance(sym, "1m")
        txt_1m, media_1m, soglia_1m, conf_1m = get_storico_stats(storico_1m, rsi_1m, trend_1m, kl_1m)
        storico_5m=fetch_storico_binance(sym, "5m")
        txt_5m, media_5m, soglia_5m, conf_5m = get_storico_stats(storico_5m, rsi_1m, trend_5m, kl_5m)
        consiglio="FERMO"
        dove="Attendi prossimo aggiornamento 5m"
        if "SALE" in txt_1m and conf_1m in ["A","B"]:
            consiglio="COMPRA"
            target=prezzo*(1+abs(media_1m)/100)
            dove=f"Compra ora, vendi a {target:.2f} EUR (+{abs(media_1m):.2f}% previsto in 25m)"
        elif "SCENDE" in txt_1m and conf_1m in ["A","B","C"]:
            consiglio="VENDI"
            target=prezzo*(1+media_1m/100)
            dove=f"Vendi ORA a {prezzo:.2f}, target {target:.2f} ({media_1m:+.2f}%)"
        elif rsi_1m>70:
            consiglio="VENDI"; dove="RSI >70 ipercomprato - prendi profitto ORA"
        elif rsi_1m<30:
            consiglio="COMPRA"; dove="RSI <30 ipervenduto - occasione COMPRA"
        allineamento = "CONFLITTO" if trend_cat(trend_1m)!=trend_cat(trend_5m) and trend_1m!="FLAT" and trend_5m!="FLAT" else "ALLINEATO"
        nome=sym.replace("EUR","")
        msg+=f"\n{nome}: {prezzo:.2f} EUR ({var_5m:+.2f}% 5m) {trend_1m} | RSI {rsi_1m:.0f} | {ema_side}\n └─ 1m: {txt_1m}\n └─ 5m: {txt_5m}\n 👉 {consiglio}: {dove}\n"
        signals.append({
            "symbol": nome, "pair": sym, "prezzo": prezzo, "var_5m": var_5m,
            "trend_1m": trend_1m, "trend_5m": trend_5m, "allineamento": allineamento,
            "rsi": rsi_1m, "vol": vol_1m, "ema_side": ema_side, "atr_perc": atr_perc,
            "media_25m": media_1m, "conf": conf_1m, "consiglio": consiglio, "dove": dove,
            "dettaglio_1m": txt_1m, "dettaglio_5m": txt_5m
        })
    LAST_SIGNALS = signals
    return msg

@app.route("/api/signals")
def api_signals():
    return jsonify({"time": now_italy().isoformat(), "signals": LAST_SIGNALS, "logs": LOGS[-20:]})

@app.route("/api/full")
def api_full():
    genera_segnali()
    return jsonify({"time": now_italy().isoformat(), "signals": LAST_SIGNALS})

DASHBOARD_HTML = """
<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Crypto Vendi App</title>
<script src='https://cdn.tailwindcss.com'></script>
</head><body class='bg-slate-900 text-white min-h-screen'>
<div class='max-w-md mx-auto p-4'>
<h1 class='text-2xl font-black text-center mt-4'>CRYPTO VENDI APP</h1>
<p class='text-center text-slate-400 text-xs mt-1'>LIVE 5m - collegata al bot Telegram</p>
<div id='time' class='text-center text-xs text-slate-500 mt-2'></div>
<button onclick='load()' class='w-full mt-4 bg-blue-600 py-3 rounded-xl font-bold'>🔄 Aggiorna Ora</button>
<div id='cards' class='mt-4 space-y-4'></div>
<div class='mt-6 text-xs text-slate-500 text-center'>API: /api/signals - Auto-refresh 60s - GitHub collegato</div>
</div>
<script>
async function load(){
  try{
    const r = await fetch('/api/signals');
    const j = await r.json();
    document.getElementById('time').innerText = 'Ultimo: ' + new Date(j.time).toLocaleString('it-IT');
    const container = document.getElementById('cards');
    container.innerHTML='';
    j.signals.forEach(s=>{
      let color = s.consiglio==='COMPRA' ? 'bg-green-500' : s.consiglio==='VENDI' ? 'bg-red-500' : 'bg-slate-600';
      container.innerHTML+=`
        <div class='bg-slate-800 rounded-2xl p-4 border border-slate-700'>
          <div class='flex justify-between items-center'>
            <div class='text-xl font-black'>${s.symbol}</div>
            <div class='text-xs px-2 py-1 rounded bg-slate-700'>${s.conf} | ${s.allineamento}</div>
          </div>
          <div class='mt-2 text-3xl font-bold'>${s.prezzo.toFixed(2)} € <span class='text-sm ${s.var_5m>=0?"text-green-400":"text-red-400"}'>${s.var_5m>=0?"+":""}${s.var_5m.toFixed(2)}% 5m</span></div>
          <div class='mt-3 w-full py-3 rounded-xl text-center font-black text-xl ${color}'>${s.consiglio}</div>
          <div class='mt-2 p-3 rounded-xl text-sm font-bold bg-yellow-300 text-black'>📍 ${s.dove}</div>
          <div class='mt-3 grid grid-cols-2 gap-2 text-xs'>
            <div>Trend 1m: <b>${s.trend_1m}</b></div>
            <div>Trend 5m: <b>${s.trend_5m}</b></div>
            <div>RSI: <b>${s.rsi.toFixed(0)}</b></div>
            <div>VOL: <b>${s.vol}</b></div>
            <div>EMA: <b>${s.ema_side}</b></div>
            <div>ATR: <b>${s.atr_perc.toFixed(2)}%</b></div>
          </div>
          <div class='mt-2 text-[10px] text-slate-400'>${s.dettaglio_1m}<br>${s.dettaglio_5m}</div>
        </div>`;
    });
  }catch(e){ document.getElementById('cards').innerHTML='<div class="text-red-400 text-center">Errore: '+e+'</div>'; }
}
load(); setInterval(load, 60000);
</script>
</body></html>
"""

@app.route("/app")
def app_page():
    return render_template_string(DASHBOARD_HTML)

@app.route("/dashboard")
def dashboard():
    return render_template_string(DASHBOARD_HTML)

def loop_bot():
    log_msg("Bot V12 EUR APP partito - collegato a /app e /api/signals")
    send_telegram("✅ Bot V12 EUR APP partito - App: /app API: /api/signals - COMPRA/VENDI/FERMO")
    for s in SYMBOLS:
        fetch_storico_binance(s, "1m")
    while True:
        try:
            m=genera_segnali()
            send_telegram(m)
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
        return "Bot V12 riavviato - Vai su /app per l'app - /api/signals per API", 200
    return f"Bot V12 vivo - /app - /api/signals - {len(LOGS)} log", 200

@app.route("/log")
def show_log():
    return "<br>".join(LOGS[-300:])

bot_thread=threading.Thread(target=loop_bot, daemon=True)
bot_thread.start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
