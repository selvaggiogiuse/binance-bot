# -*- coding: utf-8 -*-
from flask import Flask, jsonify, Response, request
import os, requests, time, threading
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
VERSION = "V61 LOOSE STABLE - NO FUTURE BUG + STABLE ENTRA"
COOLDOWN = 300
# V61: niente file persistente, solo memoria - così il bug futuro non torna mai
LAST_TELEGRAM = {}
LAST_ENTRA = {}  # key -> {time, data} per stabilizzare ENTRA 3 min
STABLE_SECONDS = 180  # ENTRA rimane visibile 3 min anche se scende a QUASI

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
        return [{"close":float(k[4]),"low":float(k[3]),"high":float(k[2]),"volume":float(k[5])} for k in r.json()]
    except: return []
def fetch_kraken(name, interval, limit=200):
    try:
        km={"BTC":"XXBTZUSD","ETH":"XETHZUSD","ORO":"PAXGUSD"}[name]
        imap={"5m":1,"15m":15,"1h":60,"4h":240,"1d":1440}
        r=requests.get(f"https://api.kraken.com/0/public/OHLC?pair={km}&interval={imap.get(interval,1)}",timeout=5)
        if r.status_code!=200: return []
        res=r.json().get("result",{})
        if not res: return []
        fk=[k for k in res.keys() if k!="last"][0]
        return [{"close":float(k[4]),"low":float(k[2]),"high":float(k[3]),"volume":float(k[6])} for k in res[fk][-limit:]]
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

def send_tg(coin, tf, signal, conf, price, sl, tp, sl_pct, tp_pct, source, rsi, extra, force=False):
    global LAST_TELEGRAM
    if not TELEGRAM_ENABLED: return {"ok":False,"error":"no token"}
    if not force and conf < TELEGRAM_MIN_CONF: return {"ok":False,"error":f"conf {conf}<{TELEGRAM_MIN_CONF}"}
    key=f"{coin}_{tf}"
    now=time.time()
    last=LAST_TELEGRAM.get(key,0)
    # FIX DEFINITIVO: se timestamp futuro, resetta subito
    if last > now + 10:
        print(f"V61 FUTURE FIX RESET {key} {last} -> 0")
        last=0
        LAST_TELEGRAM[key]=0
    if not force and now - last < COOLDOWN:
        return {"ok":False,"error":f"cooldown {int(COOLDOWN-(now-last))}s","key":key,"remaining":int(COOLDOWN-(now-last))}
    emoji="🚀" if signal=="COMPRA" else "🔻"
    rr=tp_pct/sl_pct if sl_pct>0 else 0
    tv_sym={"BTC":"BINANCE:BTCUSDT","ETH":"BINANCE:ETHUSDT","ORO":"BINANCE:PAXGUSDT"}[coin]
    chart=f"https://www.tradingview.com/chart/?symbol={tv_sym}"
    text=f"""{emoji} *{signal} {coin} {conf}%* ⚡ {tf} V61 STABLE

💰 Entry: ${price:.2f} ({source})
🎯 SL: ${sl:.2f} (-{sl_pct:.2f}%) | TP: ${tp:.2f} (+{tp_pct:.2f}%) R:R 1:{rr:.1f}
📊 RSI {rsi} | {extra}
📈 {chart}
⏰ {rome_now().strftime('%H:%M:%S')}"""
    try:
        r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id":TELEGRAM_CHAT_ID,"text":text,"parse_mode":"Markdown","disable_web_page_preview":True}, timeout=5)
        if r.status_code==200:
            LAST_TELEGRAM[key]=now
            print(f"V61 TG SENT {coin} {tf} {conf}%")
            return {"ok":True,"sent":True,"key":key}
        return {"ok":False,"error":r.text[:300]}
    except Exception as e:
        return {"ok":False,"error":str(e)}

def analyze(name, tf, do_tg=False, force_tg=False):
    global LAST_ENTRA
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
    rsi=rsi_calc(closes,14)
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

    key=f"{name}_{tf}"
    now=time.time()
    extra=f"{h1_text} • Vol x{vol_ratio:.1f} • {source} • V61 STABLE"
    # STABILIZZAZIONE: se ora è QUASI ma 1-2 min fa era ENTRA, mantieni ENTRA per 3 min
    if key in LAST_ENTRA:
        prev=LAST_ENTRA[key]
        if now - prev["time"] < STABLE_SECONDS and prev["data"]["quality_color"]=="entra" and color!="entra":
            # Mantieni ENTRA precedente per stabilità
            prev_data=prev["data"]
            prev_data["extra"] = prev_data["extra"] + f" • STABILE ({int(now-prev['time'])}s fa era {prev_data['conf']}%)"
            # Ma non rimandare Telegram se già inviato
            return prev_data, None

    data={"price":price,"source":source,"signal":signal,"conf":conf,"quality_color":color,"quality_label":label,"rsi":int(rsi),"stoch_k":stoch,"vol_ratio":round(vol_ratio,2),"sl":sl,"tp":tp,"sl_pct":sl_pct,"tp_pct":tp_pct,"rr":round(tp_pct/sl_pct,1) if sl_pct>0 else 0,"support":swing_low,"resistance":swing_high,"spark":closes[-30:],"extra":extra,"h1":h1_text}
    # Salva se ENTRA
    if color=="entra":
        LAST_ENTRA[key]={"time":now,"data":data}

    tg_res=None
    if do_tg and color=="entra":
        tg_res=send_tg(name, tf, signal, conf, price, sl, tp, sl_pct, tp_pct, source, int(rsi), extra, force=force_tg)
    return data, tg_res

@app.route("/")
def home(): return Response(f"{VERSION} - {rome_now()} - STABLE", mimetype="text/plain")
@app.route("/health")
def health(): return jsonify({"ok":True,"version":VERSION,"time":rome_now().isoformat(),"telegram":TELEGRAM_ENABLED,"last":LAST_TELEGRAM,"last_entra":list(LAST_ENTRA.keys()),"now":time.time()})

@app.route("/api/nuke")
def nuke():
    global LAST_TELEGRAM, LAST_ENTRA
    LAST_TELEGRAM={}
    LAST_ENTRA={}
    # cancella anche file vecchio se esiste
    for f in ["last_telegram.json","last_telegram.json.bak"]:
        try:
            if os.path.exists(f): os.remove(f)
        except: pass
    return jsonify({"ok":True,"nuked":True,"msg":"Tutti i cooldown e file futuri cancellati - ora V61 non usa più file","now":time.time()})

@app.route("/api/clear_telegram")
def clear_tg():
    global LAST_TELEGRAM
    LAST_TELEGRAM={}
    for f in ["last_telegram.json"]:
        try:
            if os.path.exists(f): os.remove(f)
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
        if d is None: d={"price":0,"source":"LOADING","signal":"LOADING","conf":0,"quality_color":"loading","quality_label":"CARICO...","rsi":50,"stoch_k":50,"vol_ratio":1,"sl":0,"tp":0,"sl_pct":0.8,"tp_pct":1.5,"rr":1.8,"spark":[],"extra":"Carico..."}
        res[name]=d
        if tr: tg[name]=tr
    return jsonify({"ok":True,"tf":tf,"coins":res,"telegram_results":tg,"telegram_enabled":TELEGRAM_ENABLED,"version":VERSION,"time":rome_now().isoformat()})

@app.route("/api/telegram_test")
def tg_test():
    r=send_tg("BTC","5m","COMPRA",81,80000,79400,81200,0.7,1.5,"TEST",35,"Test V61 STABLE",force=True)
    return jsonify(r)

@app.route("/api/force_telegram")
def force_tg():
    out={}
    for name in PAIRS.keys():
        p,_=get_price(name)
        if p is None: p=80000
        out[name]=send_tg(name,"5m","COMPRA",81,p,p*0.995,p*1.01,0.5,0.9,"FORCE V61",35,"Force V61 STABLE",force=True)
    return jsonify(out)

@app.route("/api/telegram_config")
def tg_config():
    now=time.time()
    future=[k for k,v in LAST_TELEGRAM.items() if v>now+10]
    return jsonify({"enabled":TELEGRAM_ENABLED,"threshold":TELEGRAM_MIN_CONF,"cooldown":COOLDOWN,"last":LAST_TELEGRAM,"now":now,"future_keys":future,"stable_keys":list(LAST_ENTRA.keys())})

@app.route("/app")
def app_page():
    html="""
<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VENDI V61 STABLE</title>
<style>
*{box-sizing:border-box;font-family:Inter,system-ui,sans-serif}
body{margin:0;background:#020617;color:#e2e8f0}
.header{padding:14px 16px;display:flex;align-items:center;gap:12px;background:#0f172a;border-bottom:1px solid #1e293b;position:sticky;top:0;z-index:10}
.logo{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#22c55e,#16a34a);display:flex;align-items:center;justify-content:center;font-weight:900;color:#052e16}
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
<div class="header"><div class="logo">V61</div><div style="flex:1"><div style="font-weight:800">VENDI V61 <span style="background:#22c55e;color:#052e16;padding:2px 6px;border-radius:6px;font-size:10px">STABLE + NO FUTURE BUG</span></div><div style="font-size:10px;color:#94a3b8">Fix Telegram + ENTRA stabile 3 min • Max trade</div></div><div><button onclick="testTG()" style="background:#0088cc;color:white;border:none;padding:6px 10px;border-radius:20px;font-size:11px;font-weight:700">📱 Test</button></div></div>
<div id="banner" class="banner b-off">Verifico V61 STABLE...</div>
<div class="tfs"><button id="b5m" class="active" onclick="loadTF('5m')">⚡ 5m STABLE</button><button id="b15m" onclick="loadTF('15m')">15m</button><button id="b1H" onclick="loadTF('1H')">1H</button><button onclick="loadTF(curTF,true,true)" style="background:#22c55e;color:#052e16">📱 Forza TG</button><button onclick="nuke()" style="background:#dc2626;color:white">💣 NUKE</button></div>
<div id="coins"><div style="padding:20px;text-align:center;color:#94a3b8">Carico V61 STABLE...</div></div>
<div id="modal" class="modal" onclick="if(event.target==this)closeM()"><div class="box"><div style="display:flex;justify-content:space-between"><b id="mCoin">BTC</b><button onclick="closeM()" style="background:#1e293b;color:white;border:none;padding:8px 12px;border-radius:10px">X</button></div><div id="mPrice" style="font-size:11px;color:#94a3b8;margin:6px 0"></div><div id="mBig" style="border-radius:14px;padding:16px;margin:10px 0;text-align:center;font-weight:900;font-size:20px"></div><div id="mExtra" style="font-size:11px;background:#1e293b;padding:10px;border-radius:10px;border:1px solid #334155;margin:8px 0"></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px"><div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">STOP LOSS</span><br><b id="mSL">-</b><br><span id="mSLpct" style="font-size:10px"></span></div><div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">TAKE PROFIT</span><br><b id="mTP">-</b><br><span id="mTPpct" style="font-size:10px"></span><br><span id="mRR" style="font-size:10px;color:#86efac"></span></div></div><button class="btn btn-green" onclick="copySLTP()">📋 Copia SL/TP</button><button class="btn btn-blue" onclick="openChart()">📈 TradingView</button><button class="btn btn-blue" onclick="sendNow()">📱 Manda Telegram ORA</button></div></div>
<script>
var curTF='5m';var lastData=null;var curCoin=null;
function badge(c,l){if(c=='entra')return '<span class="badge badge-entra">'+l+'</span>';if(c=='quasi')return '<span class="badge badge-quasi">'+l+'</span>';return '<span class="badge badge-wait">'+l+'</span>';}
async function checkTG(){try{let r=await fetch('/api/telegram_config');let j=await r.json();let b=document.getElementById('banner');if(j.enabled){let warn=j.future_keys&&j.future_keys.length>0?' ⚠️ FUTURO: '+j.future_keys.join(',')+' - Premi NUKE!':'';b.className='banner '+(warn?'b-off':'b-on');b.innerHTML='✅ V61 STABLE ON - Soglia 75% - Fix futuro + ENTRA stabile 3min - Ultimo: '+JSON.stringify(j.last)+warn+' - Stabili: '+j.stable_keys.length;}else{b.className='banner b-off';b.innerHTML='❌ Telegram OFF';}}catch{}}
async function nuke(){if(!confirm('💣 NUKE: cancello tutto, file e cooldown? Così BTC 80% partirà subito su Telegram!'))return;try{let r=await fetch('/api/nuke');let j=await r.json();alert('✅ NUKE fatto! Ora premi Forza TG');checkTG();loadTF(curTF);}catch(e){alert(e.message);}}
async function loadTF(tf,withTG=false,force=false){
curTF=tf;
document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active'));
let el=document.getElementById('b'+tf); if(el) el.classList.add('active');
document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center;color:#94a3b8">⚡ Carico '+tf+' V61 STABLE...'+(withTG?' + TG':'')+'</div>';
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
html+=`<div class="coin"><div class="coin-row" onclick="openM('${name}')"><div style="display:flex;gap:10px;align-items:center"><div class="icon ${iclass}">${name=='BTC'?'B':name=='ETH'?'E':'Au'}</div><div><b>${name}</b> - ${price}<div style="font-size:11px;color:#94a3b8">${info.extra}</div><div style="font-size:11px;color:#64748b">${action}</div></div></div><div style="text-align:right">${b}<div style="font-size:11px;color:#64748b;margin-top:4px">${info.signal} ${info.conf}%<br>SL ${info.sl_pct.toFixed(2)}% TP ${info.tp_pct.toFixed(2)}%<br>R:R 1:${info.rr}</div></div></div></div>`;
}
if(d.telegram_results && Object.keys(d.telegram_results).length>0){html+=`<div style="background:#052e16;padding:8px 12px;font-size:11px;color:#86efac;text-align:center">📱 TG: ${JSON.stringify(d.telegram_results)}</div>`;}
document.getElementById('coins').innerHTML=html;
}catch(e){document.getElementById('coins').innerHTML='<div style="padding:20px;color:#ef4444">Errore: '+e.message+'</div>';}
}
function openM(coin){if(!lastData) return; let info=lastData.coins[coin]; curCoin=coin; document.getElementById('mCoin').textContent=coin+' - $'+info.price.toFixed(2); document.getElementById('mPrice').textContent=info.source+' - '+info.signal+' '+info.conf+'% - TF '+curTF; let big=document.getElementById('mBig'); big.style.cssText='border-radius:14px;padding:16px;margin:10px 0;text-align:center;font-weight:900;font-size:20px;'; if(info.quality_color=='entra'){big.style.background='#052e16';big.style.border='2px solid #22c55e';big.style.color='#22c55e';} else if(info.quality_color=='quasi'){big.style.background='#422006';big.style.border='2px solid #facc15';big.style.color='#facc15';} else{big.style.background='#1e293b';big.style.border='1px solid #334155';} big.innerHTML=info.quality_label+' - '+info.signal+' '+info.conf+'%'; document.getElementById('mSL').textContent='$'+info.sl.toFixed(2); document.getElementById('mSLpct').textContent='-'+info.sl_pct.toFixed(2)+'%'; document.getElementById('mTP').textContent='$'+info.tp.toFixed(2); document.getElementById('mTPpct').textContent='+'+info.tp_pct.toFixed(2)+'%'; document.getElementById('mRR').textContent='R:R 1:'+info.rr; document.getElementById('mExtra').textContent=info.extra; document.getElementById('modal').classList.add('show');}
function closeM(){document.getElementById('modal').classList.remove('show');}
function copySLTP(){if(!curCoin||!lastData) return; let info=lastData.coins[curCoin]; let txt=`${curCoin} Entry ${info.price.toFixed(2)} SL ${info.sl.toFixed(2)} (${info.sl_pct.toFixed(2)}%) TP ${info.tp.toFixed(2)} (${info.tp_pct.toFixed(2)}%) R:R 1:${info.rr}`; navigator.clipboard.writeText(txt).then(()=>alert('Copiato: '+txt));}
function openChart(){if(!curCoin) return; let sym={BTC:'BINANCE:BTCUSDT',ETH:'BINANCE:ETHUSDT',ORO:'BINANCE:PAXGUSDT'}[curCoin]; window.open('https://www.tradingview.com/chart/?symbol='+sym,'_blank');}
async function sendNow(){if(!curCoin) return; try{let r=await fetch('/api/signals?tf='+curTF+'&telegram=1&force=1'); let j=await r.json(); alert('TG: '+JSON.stringify(j.telegram_results[curCoin]||j.telegram_results));}catch(e){alert(e.message);}}
async function testTG(){try{let r=await fetch('/api/telegram_test'); let j=await r.json(); alert(j.ok?'✅ Test V61 STABLE!':'❌ '+j.error);}catch(e){alert(e.message);}}
checkTG();loadTF('5m');setInterval(()=>loadTF(curTF),15000);
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
            print(f"Loop V61 {e}")
        time.sleep(60)

threading.Thread(target=bg_loop, daemon=True).start()
if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
