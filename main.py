# -*- coding: utf-8 -*-
from flask import Flask, jsonify, Response, request
import os, requests, time, threading, json
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
    def rome_now(): return datetime.now(ZoneInfo("Europe/Rome"))
except:
    def rome_now(): return datetime.now(timezone.utc) + timedelta(hours=2)

app = Flask(__name__)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
TELEGRAM_MIN_CONF = 75
PAIRS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "ORO": "PAXGUSDT"}
VERSION = "V59 LIGHT PRO FIX ORO - FUTURE TIMESTAMP FIX"
COOLDOWN = 300
LAST_FILE = "last_telegram.json"

def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path,"r") as f:
                data=json.load(f)
                # FIX: pulisci timestamp futuri
                now=time.time()
                cleaned={k:v for k,v in data.items() if v <= now and v > now-86400*7}
                if len(cleaned)!=len(data):
                    print(f"CLEANED future timestamps: {data} -> {cleaned}")
                    save_json(path, cleaned)
                return cleaned
    except: pass
    return default
def save_json(path, data):
    try:
        with open(path,"w") as f: json.dump(data,f)
    except Exception as e: print(f"Save {e}")

LAST_TELEGRAM = load_json(LAST_FILE, {})
# Pulisci subito eventuali futuri in memoria
_now=time.time()
for k in list(LAST_TELEGRAM.keys()):
    if LAST_TELEGRAM[k] > _now:
        print(f"REMOVING FUTURE {k} {LAST_TELEGRAM[k]}")
        del LAST_TELEGRAM[k]
save_json(LAST_FILE, LAST_TELEGRAM)

def ema_calc(data, p):
    if len(data) < p: return sum(data)/len(data) if data else 0
    k=2/(p+1); ema=sum(data[:p])/p
    for v in data[p:]: ema=v*k+ema*(1-k)
    return ema
def rsi_calc(closes, period=14):
    if len(closes) < period+1: return 50
    g=0; l=0
    for i in range(1, period+1):
        d=closes[-i]-closes[-i-1]
        if d>0: g+=d
        else: l-=d
    if l==0: return 70 if g>0 else 50
    rs=g/l if l!=0 else 0
    return 100-(100/(1+rs))
def adx_calc(ohlc, period=14):
    if len(ohlc) < period+5: return 25
    tr_list=[]; plus_dm=[]; minus_dm=[]
    for i in range(1, len(ohlc)):
        h=ohlc[i]["high"]; l=ohlc[i]["low"]; c_prev=ohlc[i-1]["close"]
        h_prev=ohlc[i-1]["high"]; l_prev=ohlc[i-1]["low"]
        up=h-h_prev; down=l_prev-l
        plus=up if up>down and up>0 else 0
        minus=down if down>up and down>0 else 0
        tr=max(h-l, abs(h-c_prev), abs(l-c_prev))
        plus_dm.append(plus); minus_dm.append(minus); tr_list.append(tr)
    def wilder_smooth(data, p):
        smoothed=[]; first=sum(data[:p]); smoothed.append(first)
        for i in range(p, len(data)): smoothed.append(smoothed[-1] - smoothed[-1]/p + data[i])
        return smoothed
    if len(tr_list) < period: return 25
    tr_s=wilder_smooth(tr_list, period)
    plus_s=wilder_smooth(plus_dm, period)
    minus_s=wilder_smooth(minus_dm, period)
    dx=[]
    for i in range(len(tr_s)):
        if tr_s[i]==0: dx.append(0)
        else:
            plus_di=100*plus_s[i]/tr_s[i]
            minus_di=100*minus_s[i]/tr_s[i]
            sum_di=plus_di+minus_di
            dx.append(0 if sum_di==0 else 100*abs(plus_di-minus_di)/sum_di)
    if len(dx) < period: return int(sum(dx)/len(dx)) if dx else 25
    adx_first=sum(dx[:period])/period; adx_vals=[adx_first]
    for i in range(period, len(dx)): adx_vals.append((adx_vals[-1]*(period-1)+dx[i])/period)
    return int(adx_vals[-1]) if adx_vals else 25

def get_price(name):
    sym=PAIRS.get(name,"BTCUSDT")
    try:
        r=requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}",timeout=2,headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code==200: return float(r.json()['price']), "BINANCE"
    except: pass
    try:
        km={"BTC":"XXBTZUSD","ETH":"XETHZUSD","ORO":"PAXGUSD"}[name]
        r=requests.get(f"https://api.kraken.com/0/public/Ticker?pair={km}",timeout=3)
        if r.status_code==200:
            res=r.json().get("result",{})
            if res:
                k=list(res.keys())[0]
                return float(res[k]["c"][0]), "KRAKEN"
    except: pass
    try:
        cg={"BTC":"bitcoin","ETH":"ethereum","ORO":"pax-gold"}[name]
        r=requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={cg}&vs_currencies=usd",timeout=4)
        if r.status_code==200: return float(r.json()[cg]["usd"]), "COINGECKO"
    except: pass
    return None, "FAIL"

def fetch_binance(sym, interval, limit=200):
    try:
        r=requests.get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}",timeout=4,headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code!=200: return []
        data=r.json()
        return [{"close":float(k[4]),"low":float(k[3]),"high":float(k[2]),"volume":float(k[5])} for k in data]
    except: return []
def fetch_kraken(name, interval, limit=200):
    try:
        km={"BTC":"XXBTZUSD","ETH":"XETHZUSD","ORO":"PAXGUSD"}[name]
        imap={"5m":1,"15m":15,"1h":60,"4h":240,"1d":1440}
        iv=imap.get(interval,1)
        r=requests.get(f"https://api.kraken.com/0/public/OHLC?pair={km}&interval={iv}",timeout=5)
        if r.status_code!=200: return []
        res=r.json().get("result",{})
        if not res: return []
        fk=[k for k in res.keys() if k!="last"][0]
        data=res[fk]
        return [{"close":float(k[4]),"low":float(k[2]),"high":float(k[3]),"volume":float(k[6])} for k in data[-limit:]]
    except: return []
def fetch_ohlc(name, tf, limit=200):
    sym=PAIRS[name]
    tfm={"5m":"5m","15m":"15m","1H":"1h","4H":"4h","1D":"1d"}
    interval=tfm.get(tf,"5m")
    ohlc=fetch_binance(sym, interval, limit)
    if ohlc and len(ohlc)>=20: return ohlc, "BINANCE"
    ohlc2=fetch_kraken(name, interval, limit)
    if ohlc2 and len(ohlc2)>=20: return ohlc2, "KRAKEN"
    return [], "FAIL"

def send_tg(coin, tf, signal, conf, price, sl, tp, sl_pct, tp_pct, source, rsi, adx, extra, force=False):
    global LAST_TELEGRAM
    if not TELEGRAM_ENABLED: return {"ok":False,"error":"no token"}
    if not force and conf < TELEGRAM_MIN_CONF: return {"ok":False,"error":f"conf {conf}<{TELEGRAM_MIN_CONF}"}
    key=f"{coin}_{tf}"
    now=time.time()
    last=LAST_TELEGRAM.get(key,0)
    # FIX FUTURO: se timestamp nel futuro, resetta
    if last > now:
        print(f"FUTURE FIX for {key}: {last} > {now}, resetting")
        last=0
        LAST_TELEGRAM[key]=0
        save_json(LAST_FILE, LAST_TELEGRAM)
    if not force and now - last < COOLDOWN:
        return {"ok":False,"error":f"cooldown {int(COOLDOWN-(now-last))}s","key":key,"last":last,"now":now}
    emoji="🚀" if signal=="COMPRA" else "🔻"
    rr=tp_pct/sl_pct if sl_pct>0 else 0
    tv_sym={"BTC":"BINANCE:BTCUSDT","ETH":"BINANCE:ETHUSDT","ORO":"BINANCE:PAXGUSDT"}[coin]
    chart_link=f"https://www.tradingview.com/chart/?symbol={tv_sym}"
    text=f"""{emoji} *{signal} {coin} {conf}%* ⚡ {tf} V59

💰 Entry: ${price:.2f} ({source})
🎯 SL: ${sl:.2f} (-{sl_pct:.2f}%) | TP: ${tp:.2f} (+{tp_pct:.2f}%) R:R 1:{rr:.1f}
📊 RSI {rsi} | ADX {adx} | {extra}
📈 {chart_link}
⏰ {rome_now().strftime('%H:%M:%S')}"""
    try:
        r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id":TELEGRAM_CHAT_ID,"text":text,"parse_mode":"Markdown","disable_web_page_preview":True}, timeout=5)
        if r.status_code==200:
            LAST_TELEGRAM[key]=now
            save_json(LAST_FILE, LAST_TELEGRAM)
            print(f"TG SENT {coin} {tf} {conf}%")
            return {"ok":True,"sent":True,"key":key}
        return {"ok":False,"error":r.text[:300]}
    except Exception as e:
        return {"ok":False,"error":str(e)}

def analyze(name, tf, do_tg=False, force_tg=False):
    ohlc, src = fetch_ohlc(name, tf, 200)
    ohlc_1h, _ = fetch_ohlc(name, "1H", 100)
    price, price_src = get_price(name)
    if not ohlc:
        if price is None: return None, None
        ohlc=[{"close":price,"low":price*0.998,"high":price*1.002,"volume":1}]*20
    closes=[c["close"] for c in ohlc]
    close_price=closes[-1]
    if price is None: price=close_price
    source=price_src
    ema9=ema_calc(closes,9); ema21=ema_calc(closes,21)
    rsi=rsi_calc(closes,14); adx=adx_calc(ohlc,14)
    lows=[c["low"] for c in ohlc]; highs=[c["high"] for c in ohlc]
    vols=[c["volume"] for c in ohlc]
    avg_vol=sum(vols[-20:])/20 if vols else 1
    cur_vol=vols[-1] if vols else 1
    vol_ratio=cur_vol/avg_vol if avg_vol>0 else 1
    try: stoch=int((close_price-min(lows[-14:]))/(max(highs[-14:])-min(lows[-14:]))*100)
    except: stoch=50
    h1_text="1H --"
    if ohlc_1h and len(ohlc_1h)>=21:
        c1h=[c["close"] for c in ohlc_1h]
        e21_1h=ema_calc(c1h,21); rsi_1h=rsi_calc(c1h,14)
        h1_up=c1h[-1]>e21_1h
        h1_text=f"1H {'UP' if h1_up else 'DOWN'} RSI{int(rsi_1h)}"
    points=0
    if 50<=rsi<=65: points+=25
    elif 45<=rsi<70: points+=18
    else: points+=5
    if close_price>ema9 and ema9>ema21: points+=30
    elif close_price>ema9: points+=15
    else: points+=5
    if 30<=stoch<=70: points+=20
    else: points+=8
    if vol_ratio>=0.8: points+=15
    else: points+=5
    if close_price>ema21: points+=10
    if adx>=25: points+=10
    elif adx>=20: points+=5
    conf=max(15,min(95,int(points)))
    swing_low=min(lows[-10:]); swing_high=max(highs[-10:])
    if close_price>ema21:
        sl_pct_raw=(price-swing_low*0.998)/price*100
        sl_pct=max(0.5,min(2.0,sl_pct_raw))
        sl=price*(1-sl_pct/100); tp_pct=sl_pct*1.8; tp=price*(1+tp_pct/100)
        signal="COMPRA"
    else:
        sl_pct_raw=(swing_high*1.002-price)/price*100
        sl_pct=max(0.5,min(2.0,sl_pct_raw))
        sl=price*(1+sl_pct/100); tp_pct=sl_pct*1.8; tp=price*(1-tp_pct/100)
        signal="VENDI"
    if conf>=70 and vol_ratio>=0.7:
        color="entra"; label="ENTRA"
    elif conf>=60:
        color="quasi"; label="QUASI"
    else:
        color="wait"; label="ASPETTA"
        signal="ASPETTA"; sl=price*0.992; tp=price*1.015; sl_pct=0.8; tp_pct=1.5
    filter_reason=""
    if adx < 18 and color=="entra" and conf<85:
        color="quasi"; label=f"QUASI - NO TREND ADX{adx}"
        filter_reason=f"ADX{adx}<18"
    if signal=="COMPRA" and rsi>75 and color=="entra" and conf<85:
        color="quasi"; label=f"QUASI - RSI ALTO {rsi}"
        filter_reason=f"RSI {rsi}"
    if signal=="VENDI" and rsi<25 and color=="entra" and conf<85:
        color="quasi"; label=f"QUASI - RSI BASSO {rsi}"
        filter_reason=f"RSI {rsi}"
    extra=f"{h1_text} • Vol x{vol_ratio:.1f} • ADX {adx} • {source}"
    if filter_reason: extra+=f" • ⛔ {filter_reason}"
    data={"price":price,"source":source,"signal":signal,"conf":conf,"quality_color":color,"quality_label":label,"rsi":int(rsi),"stoch_k":stoch,"adx":adx,"vol_ratio":round(vol_ratio,2),"sl":sl,"tp":tp,"sl_pct":sl_pct,"tp_pct":tp_pct,"rr":round(tp_pct/sl_pct,1) if sl_pct>0 else 0,"support":swing_low,"resistance":swing_high,"spark":closes[-30:],"extra":extra,"h1":h1_text,"filter":filter_reason}
    tg_res=None
    if do_tg and color=="entra":
        tg_res=send_tg(coin, tf, signal, conf, price, sl, tp, sl_pct, tp_pct, source, int(rsi), adx, extra, force=force_tg)
    return data, tg_res

@app.route("/")
def home(): return Response(f"{VERSION} - {rome_now()} - FIX FUTURE", mimetype="text/plain")

@app.route("/health")
def health(): return jsonify({"ok":True,"version":VERSION,"time":rome_now().isoformat(),"telegram":TELEGRAM_ENABLED,"last":LAST_TELEGRAM,"now":time.time()})

@app.route("/api/clear_telegram")
def clear_tg():
    global LAST_TELEGRAM
    LAST_TELEGRAM={}
    save_json(LAST_FILE, {})
    if os.path.exists(LAST_FILE):
        try: os.remove(LAST_FILE)
        except: pass
    return jsonify({"ok":True,"cleared":True,"now":time.time()})

@app.route("/api/signals")
def api_signals():
    tf=request.args.get("tf","5m")
    do_tg=request.args.get("telegram","0")=="1"
    force=request.args.get("force","0")=="1"
    res={}; tg={}
    for name in PAIRS.keys():
        d,tr=analyze(name, tf, do_tg, force_tg=force)
        if d is None: d={"price":0,"source":"LOADING","signal":"LOADING","conf":0,"quality_color":"loading","quality_label":"CARICO...","rsi":50,"stoch_k":50,"adx":25,"vol_ratio":1,"sl":0,"tp":0,"sl_pct":0.8,"tp_pct":1.5,"rr":1.8,"spark":[],"extra":"Carico..."}
        res[name]=d
        if tr: tg[name]=tr
    return jsonify({"ok":True,"tf":tf,"coins":res,"telegram_results":tg,"telegram_enabled":TELEGRAM_ENABLED,"version":VERSION,"time":rome_now().isoformat()})

@app.route("/api/telegram_test")
def tg_test():
    r=send_tg("BTC","5m","COMPRA",85,80000,79400,81200,0.7,1.5,"TEST",58,28,"Test V59 FIX FUTURE",force=True)
    return jsonify(r)

@app.route("/api/force_telegram")
def force_tg():
    out={}
    for name in PAIRS.keys():
        p,_=get_price(name)
        if p is None: p=80000
        out[name]=send_tg(name,"15m","COMPRA",93,p,p*0.995,p*1.01,0.5,0.9,"FORCE ORO FIX",53,30,"Force ORO 93% - FIX FUTURE",force=True)
    return jsonify(out)

@app.route("/api/telegram_config")
def tg_config():
    now=time.time()
    future=[k for k,v in LAST_TELEGRAM.items() if v>now]
    return jsonify({"enabled":TELEGRAM_ENABLED,"threshold":TELEGRAM_MIN_CONF,"cooldown":COOLDOWN,"last":LAST_TELEGRAM,"now":now,"future_keys":future,"file_exists":os.path.exists(LAST_FILE)})

@app.route("/app")
def app_page():
    html="""
<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VENDI V59 FIX ORO</title>
<style>
*{box-sizing:border-box;font-family:Inter,system-ui,sans-serif}
body{margin:0;background:#020617;color:#e2e8f0}
.header{padding:14px 16px;display:flex;align-items:center;gap:12px;background:#0f172a;border-bottom:1px solid #1e293b;position:sticky;top:0;z-index:10}
.logo{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#22c55e,#facc15);display:flex;align-items:center;justify-content:center;font-weight:900;color:#052e16}
.badge{padding:4px 10px;border-radius:20px;font-size:11px;font-weight:800}
.badge-entra{background:#22c55e;color:#052e16;animation:glow 1s infinite alternate}
.badge-quasi{background:#facc15;color:#422006}
.badge-wait{background:#1e293b;color:#94a3b8}
@keyframes glow{0%{box-shadow:0 0 5px #22c55e}100%{box-shadow:0 0 12px #22c55e}}
.tfs{display:flex;gap:6px;padding:10px 12px;background:#020617;overflow-x:auto}
.tfs button{border:1px solid #1e293b;background:#1e293b;color:#cbd5e1;padding:8px 14px;border-radius:20px;font-weight:700;cursor:pointer}
.tfs button.active{background:#22c55e;color:#052e16}
.banner{margin:8px 12px;padding:10px 12px;border-radius:10px;font-size:12px;text-align:center}
.b-on{background:#052e16;border:1px solid #16a34a;color:#86efac}
.b-off{background:#450a0a;border:1px solid #dc2626;color:#fca5a5}
.coin{background:#0f172a;border:1px solid #1e293b;border-radius:14px;margin:8px 10px;overflow:hidden}
.coin-row{display:flex;justify-content:space-between;align-items:center;padding:14px;cursor:pointer}
.icon{width:38px;height:38px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:900;color:white}
.icon.btc{background:#f7931a}.icon.eth{background:#8b5cf6}.icon.oro{background:#ca8a04}
.modal{position:fixed;inset:0;background:rgba(0,0,0,0.7);display:none;align-items:flex-end;justify-content:center;z-index:50}
.modal.show{display:flex}
.box{background:#0f172a;width:100%;max-width:480px;border-radius:20px 20px 0 0;padding:20px;max-height:90vh;overflow:auto;border:1px solid #1e293b}
.btn{width:100%;padding:12px;border-radius:10px;border:none;font-weight:800;cursor:pointer;margin-top:8px}
.btn-blue{background:#0088cc;color:white}
.btn-green{background:#16a34a;color:white}
.btn-red{background:#dc2626;color:white}
</style></head><body>
<div class="header"><div class="logo">V59</div><div style="flex:1"><div style="font-weight:800">VENDI V59 <span style="background:#22c55e;color:#052e16;padding:2px 6px;border-radius:6px;font-size:10px">FIX ORO 93%</span></div><div style="font-size:10px;color:#94a3b8">Fix timestamp futuro + Clear + ADX + Chart</div></div><div><button onclick="testTG()" style="background:#0088cc;color:white;border:none;padding:6px 10px;border-radius:20px;font-size:11px;font-weight:700">📱 Test</button></div></div>
<div id="banner" class="banner b-off">Verifico V59 FIX...</div>
<div class="tfs"><button id="b5m" onclick="loadTF('5m')">⚡ 5m</button><button id="b15m" class="active" onclick="loadTF('15m')">15m</button><button id="b1H" onclick="loadTF('1H')">1H</button><button onclick="loadTF(curTF,true,true)" style="background:#22c55e;color:#052e16">📱 Forza TG 93%</button><button onclick="clearTG()" style="background:#dc2626;color:white">🗑️ Clear Cooldown</button></div>
<div id="coins"><div style="padding:20px;text-align:center;color:#94a3b8">Carico V59 FIX ORO...</div></div>
<div id="modal" class="modal" onclick="if(event.target==this)closeM()"><div class="box"><div style="display:flex;justify-content:space-between"><b id="mCoin">BTC</b><button onclick="closeM()" style="background:#1e293b;color:white;border:none;padding:8px 12px;border-radius:10px">X</button></div><div id="mPrice" style="font-size:11px;color:#94a3b8;margin:6px 0"></div><div id="mBig" style="border-radius:14px;padding:16px;margin:10px 0;text-align:center;font-weight:900;font-size:20px"></div><div id="mExtra" style="font-size:11px;background:#1e293b;padding:10px;border-radius:10px;border:1px solid #334155;margin:8px 0"></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px"><div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">STOP LOSS</span><br><b id="mSL">-</b><br><span id="mSLpct" style="font-size:10px"></span></div><div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">TAKE PROFIT</span><br><b id="mTP">-</b><br><span id="mTPpct" style="font-size:10px"></span><br><span id="mRR" style="font-size:10px;color:#86efac"></span></div></div><button class="btn btn-green" onclick="copySLTP()">📋 Copia SL/TP</button><button class="btn btn-blue" onclick="openChart()">📈 Apri TradingView</button><button class="btn btn-blue" onclick="sendNow()">📱 Manda Telegram ORA</button></div></div>
<script>
var curTF='15m';var lastData=null;var curCoin=null;
function badge(c,l){if(c=='entra')return '<span class="badge badge-entra">'+l+'</span>';if(c=='quasi')return '<span class="badge badge-quasi">'+l+'</span>';return '<span class="badge badge-wait">'+l+'</span>';}
async function checkTG(){try{let r=await fetch('/api/telegram_config');let j=await r.json();let b=document.getElementById('banner');if(j.enabled){let warn=j.future_keys&&j.future_keys.length>0?' ⚠️ TIMESTAMP FUTURO BLOCCANTE: '+j.future_keys.join(',')+' - Premi Clear!':'';b.className='banner '+(warn?'b-off':'b-on');b.innerHTML='✅ V59 Telegram ON - Soglia 75% - Fix futuro attivo - Cooldown 5m - Ultimo: '+JSON.stringify(j.last)+warn;}else{b.className='banner b-off';b.innerHTML='❌ Telegram OFF';}}catch{}}
async function clearTG(){if(!confirm('Cancello tutto il cooldown bloccante? Così ORO 93% partirà subito.'))return;try{let r=await fetch('/api/clear_telegram');let j=await r.json();alert('✅ Cooldown cancellato! Ora premi Forza TG 93%');checkTG();loadTF(curTF);}catch(e){alert(e.message);}}
async function loadTF(tf,withTG=false,force=false){
curTF=tf;
document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active'));
let el=document.getElementById('b'+tf); if(el) el.classList.add('active');
document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center;color:#94a3b8">⚡ Carico '+tf+' V59 FIX...'+(withTG?' + TG':'')+'</div>';
try{
let url='/api/signals?tf='+tf+(withTG?'&telegram=1':'')+(force?'&force=1':'');
let r=await fetch(url); let d=await r.json(); lastData=d; checkTG();
let html='';
for(let name in d.coins){
let info=d.coins[name];
let iclass=name=='BTC'?'btc':name=='ETH'?'eth':'oro';
let b=badge(info.quality_color, info.quality_label);
let price='$'+info.price.toFixed(2);
let action=info.quality_color=='entra'?(info.signal=='COMPRA'?'🚀 COMPRA ORA':'🔻 VENDI ORA'):'⏸️ Aspetta';
let adxBadge=info.adx<18?'⛔':'✅';
html+=`<div class="coin"><div class="coin-row" onclick="openM('${name}')"><div style="display:flex;gap:10px;align-items:center"><div class="icon ${iclass}">${name=='BTC'?'B':name=='ETH'?'E':'Au'}</div><div><b>${name}</b> - ${price}<div style="font-size:11px;color:#94a3b8">${adxBadge} ADX ${info.adx} • ${info.extra}</div><div style="font-size:11px;color:#64748b">${action}</div></div></div><div style="text-align:right">${b}<div style="font-size:11px;color:#64748b;margin-top:4px">${info.signal} ${info.conf}%<br>SL ${info.sl_pct.toFixed(2)}% TP ${info.tp_pct.toFixed(2)}%<br>R:R 1:${info.rr}</div></div></div></div>`;
}
if(d.telegram_results && Object.keys(d.telegram_results).length>0){html+=`<div style="background:#052e16;padding:8px 12px;font-size:11px;color:#86efac;text-align:center">📱 Inviato TG: ${JSON.stringify(d.telegram_results)}</div>`;}
document.getElementById('coins').innerHTML=html;
}catch(e){document.getElementById('coins').innerHTML='<div style="padding:20px;color:#ef4444">Errore: '+e.message+'</div>';}
}
function openM(coin){if(!lastData) return; let info=lastData.coins[coin]; curCoin=coin; document.getElementById('mCoin').textContent=coin+' - $'+info.price.toFixed(2); document.getElementById('mPrice').textContent=info.source+' - '+info.signal+' '+info.conf+'% - ADX '+info.adx+' - TF '+curTF; let big=document.getElementById('mBig'); big.style.cssText='border-radius:14px;padding:16px;margin:10px 0;text-align:center;font-weight:900;font-size:20px;'; if(info.quality_color=='entra'){big.style.background='#052e16';big.style.border='2px solid #22c55e';big.style.color='#22c55e';} else if(info.quality_color=='quasi'){big.style.background='#422006';big.style.border='2px solid #facc15';big.style.color='#facc15';} else{big.style.background='#1e293b';big.style.border='1px solid #334155';} big.innerHTML=info.quality_label+' - '+info.signal+' '+info.conf+'%'; document.getElementById('mSL').textContent='$'+info.sl.toFixed(2); document.getElementById('mSLpct').textContent='-'+info.sl_pct.toFixed(2)+'%'; document.getElementById('mTP').textContent='$'+info.tp.toFixed(2); document.getElementById('mTPpct').textContent='+'+info.tp_pct.toFixed(2)+'%'; document.getElementById('mRR').textContent='R:R 1:'+info.rr; document.getElementById('mExtra').textContent=info.extra; document.getElementById('modal').classList.add('show');}
function closeM(){document.getElementById('modal').classList.remove('show');}
function copySLTP(){if(!curCoin||!lastData) return; let info=lastData.coins[curCoin]; let txt=`${curCoin} Entry ${info.price.toFixed(2)} SL ${info.sl.toFixed(2)} (${info.sl_pct.toFixed(2)}%) TP ${info.tp.toFixed(2)} (${info.tp_pct.toFixed(2)}%) R:R 1:${info.rr}`; navigator.clipboard.writeText(txt).then(()=>alert('Copiato: '+txt));}
function openChart(){if(!curCoin) return; let sym={BTC:'BINANCE:BTCUSDT',ETH:'BINANCE:ETHUSDT',ORO:'BINANCE:PAXGUSDT'}[curCoin]; window.open('https://www.tradingview.com/chart/?symbol='+sym,'_blank');}
async function sendNow(){if(!curCoin) return; try{let r=await fetch('/api/signals?tf='+curTF+'&telegram=1&force=1'); let j=await r.json(); alert('TG: '+JSON.stringify(j.telegram_results[curCoin]||j.telegram_results));}catch(e){alert(e.message);}}
async function testTG(){try{let r=await fetch('/api/telegram_test'); let j=await r.json(); alert(j.ok?'✅ Test V59 inviato!':'❌ '+j.error);}catch(e){alert(e.message);}}
checkTG();loadTF('15m');setInterval(()=>loadTF(curTF),15000);
</script></body></html>
"""
    return Response(html, mimetype="text/html; charset=utf-8")

def bg_loop():
    while True:
        try:
            for tf in ["5m","15m","1H"]:
                for name in PAIRS.keys():
                    analyze(name, tf, do_tg=True)
        except Exception as e:
            print(f"Loop V59 FIX {e}")
        time.sleep(60)

threading.Thread(target=bg_loop, daemon=True).start()
if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
