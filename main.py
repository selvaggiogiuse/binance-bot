# -*- coding: utf-8 -*-
from flask import Flask, jsonify, Response, request
import os, requests, time, json
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
    def rome_now():
        return datetime.now(ZoneInfo("Europe/Rome"))
except:
    def rome_now():
        return datetime.now(timezone.utc) + timedelta(hours=2)

app = Flask(__name__)

# CONFIG TELEGRAM - metti in ENV su Render per sicurezza
# Su Render: Environment -> TELEGRAM_BOT_TOKEN = 123456:ABC... , TELEGRAM_CHAT_ID = 123456789
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")  # da BotFather
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")      # tuo chat ID
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

PAIRS_LIVE = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "ORO": "PAXGUSDT"}
PAIRS_OHLC = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "ORO": "PAXGUSDT"}
TF_MAP = {"5m": "5m", "15m": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}
VERSION = "V57 - TELEGRAM SCALPING"

LAST_TELEGRAM = {}  # coin_TF -> timestamp
TELEGRAM_COOLDOWN = 900  # 15 min per scalping 5m

def send_telegram_signal(coin, tf, signal, conf, price, rsi, stoch, sl, tp, sl_pct, tp_pct, source):
    if not TELEGRAM_ENABLED:
        return {"ok": False, "error": "Telegram non configurato - manca TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID in ENV"}
    key = f"{coin}_{tf}"
    now = time.time()
    last = LAST_TELEGRAM.get(key, 0)
    if now - last < TELEGRAM_COOLDOWN:
        return {"ok": False, "error": f"Cooldown {int((TELEGRAM_COOLDOWN - (now-last))/60)} min"}
    
    emoji = "🚀" if signal=="COMPRA" else "🔻" if signal=="VENDI" else "⏸️"
    tf_emoji = "⚡" if tf=="5m" else "🔍"
    
    text = f"""{emoji} *VENDI {coin} {signal} {conf}%* {tf_emoji} {tf} SCALP

💰 Prezzo: ${price:.2f} ({source})
📊 RSI: {rsi} | Stoch: {stoch}
🎯 SL: ${sl:.2f} (-{sl_pct:.2f}%)
🎯 TP: ${tp:.2f} (+{tp_pct:.2f}%)
⏰ {rome_now().strftime('%H:%M:%S')} Europe/Rome

Confluenza: controlla app per multi-TF"""
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code==200:
            LAST_TELEGRAM[key]=now
            return {"ok": True, "telegram": r.json()}
        else:
            return {"ok": False, "error": f"Telegram API {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def ema_calc(data, period):
    if not data: return 0
    if len(data) < period: return sum(data)/len(data)
    k=2/(period+1)
    ema=sum(data[:period])/period
    for price in data[period:]: ema=price*k+ema*(1-k)
    return ema

def rsi_calc(closes, period=14):
    if len(closes) < period+1: return 50
    gains=0; losses=0
    for i in range(1, period+1):
        diff=closes[-i]-closes[-i-1]
        if diff>0: gains+=diff
        else: losses-=diff
    if losses==0: return 70 if gains>0 else 50
    rs=gains/losses if losses!=0 else 0
    return 100-(100/(1+rs))

def get_live_price_ticker(name):
    symbol=PAIRS_LIVE.get(name,"BTCUSDT")
    try:
        r=requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",timeout=2,headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code==200:
            return float(r.json()['price']), f"BINANCE:{symbol}"
    except: pass
    try:
        kraken_map={"BTC":"XXBTZUSD","ETH":"XETHZUSD","ORO":"PAXGUSD"}
        kp=kraken_map.get(name,"XXBTZUSD")
        r=requests.get(f"https://api.kraken.com/0/public/Ticker?pair={kp}",timeout=3)
        if r.status_code==200:
            j=r.json(); result=j.get("result",{})
            if result:
                first_key=list(result.keys())[0]
                return float(result[first_key]["c"][0]), f"KRAKEN:{kp}"
    except: pass
    return None, "CACHE"

def fetch_binance_klines(symbol, interval, limit=200):
    try:
        url=f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        r=requests.get(url,timeout=4,headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code!=200: return []
        data=r.json()
        return [{"time":int(k[0]/1000),"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5])} for k in data]
    except: return []

def fetch_kraken_ohlc(name, interval, limit=200):
    try:
        kraken_map={"BTC":"XXBTZUSD","ETH":"XETHZUSD","ORO":"PAXGUSD"}
        kp=kraken_map.get(name,"XXBTZUSD")
        kraken_interval_map={"5m":1,"15m":15,"1h":60,"4h":240,"1d":1440}
        k_interval=kraken_interval_map.get(interval,60)
        url=f"https://api.kraken.com/0/public/OHLC?pair={kp}&interval={k_interval}"
        r=requests.get(url,timeout=5,headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code!=200: return []
        j=r.json(); result=j.get("result",{})
        if not result: return []
        first_key=[k for k in result.keys() if k!="last"][0]
        data=result[first_key]
        return [{"time":int(k[0]),"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[6])} for k in data[-limit:]]
    except: return []

def fetch_ohlc_with_fallback(name, interval, limit=200):
    symbol=PAIRS_OHLC.get(name,"BTCUSDT")
    ohlc=fetch_binance_klines(symbol,interval,limit)
    if ohlc and len(ohlc)>=20: return ohlc, "binance"
    ohlc2=fetch_kraken_ohlc(name,interval,limit)
    if ohlc2 and len(ohlc2)>=20: return ohlc2, "kraken"
    return [], "fail"

def analyze_coin(name, tf, send_telegram=False):
    interval=TF_MAP.get(tf,"5m")
    live_price, source = get_live_price_ticker(name)
    ohlc, ohlc_src = fetch_ohlc_with_fallback(name, interval, 200)
    
    if not ohlc or len(ohlc)<20:
        if live_price is None: return None, None
        return {
            "price":live_price,"real_price":live_price,"close_price":live_price,
            "source":source,"ohlc_src":ohlc_src,
            "signal":"LOADING","conf":0,"quality_color":"loading","quality_label":"AGGIORNAMENTO",
            "quality_score":0,"quality_simple":f"Scalp {tf} in aggiornamento...",
            "rsi":50,"rsi_fast":50,"ema9":live_price,"ema21":live_price,"ema50":live_price,"st_trend":0,"st_val":live_price,
            "stoch_k":50,"vwap":live_price,"support":live_price*0.998,"resistance":live_price*1.002,
            "adx":20,"vol_ratio":1.0,"sl":live_price*0.992,"tp":live_price*1.008,"sl_pct":0.8,"tp_pct":1.5,
            "spark": [live_price]*20
        }, None
    
    closes=[c["close"] for c in ohlc]
    close_price=closes[-1]
    price = live_price if live_price is not None else close_price
    
    ema9=ema_calc(closes,9); ema21=ema_calc(closes,21); ema50=ema_calc(closes,50)
    rsi=rsi_calc(closes,14); rsi_fast=rsi_calc(closes,7)
    lows=[c["low"] for c in ohlc]; highs=[c["high"] for c in ohlc]
    support=min(lows[-10:]); resistance=max(highs[-10:])
    vwap=sum(closes[-20:])/20
    st_trend=1 if close_price>ema21 else -1; st_val=ema21
    try:
        low_min=min(lows[-14:]); high_max=max(highs[-14:])
        stoch_k=int((close_price-low_min)/(high_max-low_min)*100) if high_max!=low_min else 50
    except: stoch_k=50
    adx=20+int(abs(close_price-ema21)/close_price*1000)%40 if close_price else 20
    
    points=0; max_points=0
    max_points+=20
    if 50<=rsi<=65: points+=20
    elif 45<=rsi<50 or 65<rsi<=70: points+=15
    elif 40<=rsi<45: points+=10
    elif 70<rsi<=75: points+=8
    else: points+=2
    max_points+=20
    if close_price>ema9 and ema9>ema21: points+=20
    elif close_price>ema9: points+=12
    elif close_price>ema21: points+=6
    max_points+=15
    if st_trend==1 and close_price>vwap: points+=15
    elif st_trend==1: points+=8
    else: points+=2
    max_points+=15
    if 30<=stoch_k<=65: points+=15
    elif 20<=stoch_k<30 or 65<stoch_k<=80: points+=8
    else: points+=2
    max_points+=15
    if adx>=25: points+=15
    elif adx>=20: points+=8
    else: points+=3
    max_points+=15
    dist_res=(resistance-close_price)/close_price*100
    dist_sup=(close_price-support)/close_price*100
    if dist_res>0.3 and dist_sup<0.8: points+=15
    elif dist_res>0.15: points+=8
    else: points+=2
    
    conf=int(points/max_points*100) if max_points>0 else 50
    conf=max(15,min(95,conf))
    
    is_scalp = tf=="5m" or tf=="15m"
    sl_pct = 0.008 if is_scalp else 0.02
    tp_pct = 0.015 if is_scalp else 0.04
    
    if conf>=68 and st_trend==1 and close_price>ema9:
        signal="COMPRA"; quality_color="entra" if conf>=78 else "quasi"; quality_label="ENTRA" if conf>=78 else "QUASI PRONTO"
        quality_simple=f"SCALP {tf} LIVE ${price:.2f} RSI{int(rsi)} EMA9>{int(ema9)} {conf}%"
    elif conf<=35 and st_trend==-1:
        signal="VENDI"; quality_color="entra" if conf>=65 else "quasi"; quality_label="ENTRA" if conf>=65 else "QUASI PRONTO"
        quality_simple=f"SCALP SHORT {tf} ${price:.2f} RSI{int(rsi)} {conf}%"
    else:
        if conf>=60:
            signal="COMPRA"; quality_color="quasi"; quality_label="QUASI PRONTO"
            quality_simple=f"SCALP {tf} quasi {conf}% RSI{int(rsi)}"
        else:
            signal="ASPETTA"; quality_color="wait"; quality_label="ASPETTA"
            quality_simple=f"SCALP {tf} {conf}% - RSI{int(rsi)} Stoch{stoch_k}"
    
    sl=price*(1-sl_pct) if signal=="COMPRA" else price*(1+sl_pct)
    tp=price*(1+tp_pct) if signal=="COMPRA" else price*(1-tp_pct)
    
    data={
        "price":price,"real_price":price,"close_price":close_price,"source":source,"ohlc_src":ohlc_src,
        "signal":signal,"conf":int(conf),"quality_color":quality_color,"quality_label":quality_label,"quality_score":int(conf),
        "quality_simple":quality_simple,"rsi":int(rsi),"rsi_fast":int(rsi_fast),"ema9":ema9,"ema21":ema21,"ema50":ema50,"st_trend":st_trend,"st_val":st_val,
        "stoch_k":stoch_k,"vwap":vwap,"support":support,"resistance":resistance,"adx":adx,"vol_ratio":1.0,
        "sl":sl,"tp":tp,"sl_pct":sl_pct*100,"tp_pct":tp_pct*100,"spark":closes[-30:] if len(closes)>=30 else closes
    }
    
    telegram_result=None
    if send_telegram and quality_color=="entra" and conf>=75:
        telegram_result=send_telegram_signal(coin, tf, signal, conf, price, rsi, stoch_k, sl, tp, sl_pct*100, tp_pct*100, source)
    
    return data, telegram_result

@app.route("/")
def home():
    status = "TELEGRAM ON" if TELEGRAM_ENABLED else "TELEGRAM OFF - configura ENV"
    return Response(f"Bot {VERSION} - {status} - {rome_now()}", mimetype="text/plain")

@app.route("/api/signals")
def api_signals():
    tf=request.args.get("tf","5m")
    send_tg = request.args.get("telegram","0")=="1"
    result={}
    tg_results={}
    for name in PAIRS_LIVE.keys():
        data, tg_res = analyze_coin(name,tf, send_telegram=send_tg)
        if data is None:
            data={"price":80000,"real_price":80000,"close_price":80000,"source":"FAIL","ohlc_src":"fail","signal":"LOADING","conf":0,"quality_color":"loading","quality_label":"AGGIORNAMENTO","quality_score":0,"quality_simple":"Aggiornamento...","rsi":50,"ema9":0,"ema21":0,"ema50":0,"st_trend":0,"st_val":0,"stoch_k":50,"vwap":0,"support":0,"resistance":0,"adx":20,"vol_ratio":1.0,"sl":0,"tp":0,"sl_pct":0.8,"tp_pct":1.5,"spark":[]}
        result[name]=data
        if tg_res: tg_results[name]=tg_res
    return jsonify({"ok":True,"tf":tf,"coins":result,"telegram_results":tg_results,"telegram_enabled":TELEGRAM_ENABLED,"time":rome_now().isoformat(),"version":VERSION})

@app.route("/api/telegram_test")
def api_telegram_test():
    if not TELEGRAM_ENABLED:
        return jsonify({"ok":False,"error":"Configura TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nelle variabili ENV di Render"}), 400
    res = send_telegram_signal("BTC", "5m", "COMPRA", 85, 80168.00, 58, 62, 79500, 81300, 0.8, 1.5, "TEST")
    return jsonify(res)

@app.route("/api/telegram_config")
def api_telegram_config():
    return jsonify({
        "enabled": TELEGRAM_ENABLED,
        "has_token": bool(TELEGRAM_BOT_TOKEN),
        "has_chat_id": bool(TELEGRAM_CHAT_ID),
        "cooldown_minutes": TELEGRAM_COOLDOWN/60,
        "last_sent": LAST_TELEGRAM
    })

@app.route("/app")
def app_page():
    html = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VENDI V57 TELEGRAM</title>
<style>
*{box-sizing:border-box;font-family:Inter,system-ui,sans-serif}
body{margin:0;background:#020617;color:#f1f5f9}
.header{background:linear-gradient(135deg,#020617,#1e293b);color:white;padding:12px 16px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:10;border-bottom:1px solid #1e293b}
.logo-img{width:48px;height:48px;border-radius:12px;background:#22c55e;display:flex;align-items:center;justify-content:center;font-weight:900;color:#052e16;font-size:18px}
.badge{padding:4px 10px;border-radius:20px;font-size:11px;font-weight:800;white-space:nowrap;display:inline-block}
.badge-entra{background:#22c55e;color:#052e16;animation:glow 1s infinite alternate}
.badge-quasi{background:#facc15;color:#422006}.badge-wait{background:#1e293b;color:#94a3b8}.badge-loading{background:#334155;color:#cbd5e1}
@keyframes glow{0%{box-shadow:0 0 5px #22c55e}100%{box-shadow:0 0 15px #22c55e}}
.tfs{display:flex;gap:6px;padding:10px 12px;overflow-x:auto;background:#0f172a}
.tfs button{border:1px solid #1e293b;background:#1e293b;color:#cbd5e1;padding:8px 14px;border-radius:20px;font-weight:700;cursor:pointer;white-space:nowrap;font-size:13px}
.tfs button.active{background:#22c55e;color:#052e16;border-color:#22c55e}
.coin-row{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-bottom:1px solid #1e293b;background:#0f172a;cursor:pointer}
.coin-icon{width:38px;height:38px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:900;color:white;flex-shrink:0}
.coin-icon.btc{background:#f7931a}.coin-icon.eth{background:#8b5cf6}.coin-icon.oro{background:#ca8a04}
.spark{width:70px;height:28px;display:inline-block;margin-left:6px}
.modal{position:fixed;inset:0;background:rgba(0,0,0,0.7);display:none;align-items:flex-end;justify-content:center;z-index:50}
.modal.show{display:flex}
.modal-box{background:#0f172a;color:#f1f5f9;width:100%;max-width:500px;border-radius:20px 20px 0 0;padding:20px;max-height:92vh;overflow:auto;border:1px solid #1e293b}
.big-box{border-radius:14px;padding:16px;margin:12px 0;text-align:center}
.entra-big{background:#052e16;border:2px solid #22c55e}.quasi-big{background:#422006;border:2px solid #facc15}.wait-big{background:#1e293b;border:1px solid #334155}
.stat-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin:12px 0}
.stat-card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:8px;text-align:center}
.stat-card b{display:block;font-size:15px;color:#f1f5f9}.stat-card span{font-size:9px;color:#94a3b8}
.tele-banner{margin:8px 12px;padding:10px 12px;border-radius:10px;font-size:12px;display:flex;justify-content:space-between;align-items:center}
.tele-on{background:#052e16;border:1px solid #16a34a;color:#86efac}.tele-off{background:#450a0a;border:1px solid #dc2626;color:#fca5a5}
</style>
</head>
<body>
<div class="header">
<div class="logo-img">VEND</div>
<div style="flex:1">
<div style="font-weight:800;font-size:14px">VENDI - <span style="background:#22c55e;color:#052e16;padding:2px 6px;border-radius:6px;font-size:11px">V57</span> TELEGRAM</div>
<div style="font-size:10px;opacity:0.7">Notifiche Telegram • Scalp 5m</div>
</div>
<div style="text-align:right">
<button onclick="testTelegram()" style="background:#0088cc;color:white;border:none;padding:6px 10px;border-radius:20px;font-size:11px;font-weight:700">📱 Test TG</button>
</div>
</div>

<div id="teleBanner" class="tele-banner tele-off">Verifico Telegram...</div>

<div class="tfs">
<button id="b5m" class="active" onclick="loadTF('5m')">⚡ 5m SCALP</button>
<button id="b15m" onclick="loadTF('15m')">15m</button>
<button id="b1H" onclick="loadTF('1H')">1H filtro</button>
<button id="bConf" onclick="loadTF('5m', true)" style="background:#0088cc;color:white">📱 Con TG</button>
</div>

<div id="coins" style="background:#0f172a;border-radius:12px;margin:0 8px;overflow:hidden;border:1px solid #1e293b;min-height:100px"><div style="padding:20px;text-align:center;color:#94a3b8">Carico scalping con Telegram...</div></div>

<div id="modal" class="modal" onclick="if(event.target==this)closeModal()">
<div class="modal-box">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
<b id="mCoin" style="font-size:18px">BTC</b><button onclick="closeModal()" style="border:none;background:#1e293b;color:white;padding:8px 12px;border-radius:10px;font-weight:700">X</button>
</div>
<div id="mPrice" style="font-size:11px;color:#94a3b8;margin-bottom:10px"></div>
<div id="mQualityBig" class="big-box"></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:10px 0">
<div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">STOP LOSS</span><br><b id="mSL" style="color:#22c55e">-</b><br><span id="mSLpct" style="font-size:9px;color:#94a3b8">-</span></div>
<div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">TAKE PROFIT</span><br><b id="mTP" style="color:#22c55e">-</b><br><span id="mTPpct" style="font-size:9px;color:#94a3b8">-</span></div>
</div>
<div class="stat-grid">
<div class="stat-card"><span>RSI / FAST</span><b id="sRSI">-</b></div>
<div class="stat-card"><span>STOCH K</span><b id="sStoch">-</b></div>
<div class="stat-card"><span>EMA9 / 21</span><b id="sEMA" style="font-size:11px">-</b></div>
<div class="stat-card"><span>SUPERTREND</span><b id="sST" style="font-size:11px">-</b></div>
<div class="stat-card"><span>VWAP</span><b id="sVWAP">-</b></div>
<div class="stat-card"><span>ADX</span><b id="sADX">-</b></div>
</div>
<div id="mSimpleText" style="font-size:11px;color:#cbd5e1;background:#1e293b;padding:12px;border-radius:10px;margin:10px 0;border:1px solid #334155"></div>
<button onclick="sendThisToTelegram()" style="width:100%;background:#0088cc;color:white;border:none;padding:12px;border-radius:10px;font-weight:800;margin-top:8px">📱 MANDA SU TELEGRAM ORA</button>
</div>
</div>

<script>
var curTF='5m';
var lastData=null;

function qualityBadge(info){
  var c=info.quality_color||'wait'; var l=info.quality_label||'ASPETTA';
  if(c=='entra') return '<span class="badge badge-entra">'+l+'</span>';
  if(c=='quasi') return '<span class="badge badge-quasi">'+l+'</span>';
  if(c=='loading') return '<span class="badge badge-loading">'+l+'</span>';
  return '<span class="badge badge-wait">'+l+'</span>';
}
function sparklineSVG(data){
  if(!data || data.length<2) return '';
  var min=Math.min(...data), max=Math.max(...data);
  var range=max-min || 1;
  var w=70, h=28;
  var points=data.map((v,i)=>{
    var x=(i/(data.length-1))*w;
    var y=h - ((v-min)/range)*h;
    return x.toFixed(1)+','+y.toFixed(1);
  }).join(' ');
  var color=data[data.length-1]>=data[0]?'#22c55e':'#ef4444';
  return `<svg class="spark" viewBox="0 0 ${w} ${h}"><polyline fill="none" stroke="${color}" stroke-width="1.8" points="${points}"/></svg>`;
}

async function checkTelegram(){
  try{
    var r=await fetch('/api/telegram_config');
    var j=await r.json();
    var banner=document.getElementById('teleBanner');
    if(j.enabled){
      banner.className='tele-banner tele-on';
      banner.innerHTML=`<span>✅ Telegram attivo - Cooldown ${j.cooldown_minutes} min</span><span style="font-size:10px">Chat: ...${String(j.has_chat_id).slice(-4)}</span>`;
    }else{
      banner.className='tele-banner tele-off';
      banner.innerHTML=`<span>❌ Telegram OFF - Configura ENV su Render: TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID</span><span><button onclick="showSetup()" style="background:#dc2626;color:white;border:none;padding:4px 8px;border-radius:10px;font-size:10px">Come fare?</button></span>`;
    }
  }catch(e){}
}
function showSetup(){
  alert(`SETUP TELEGRAM - 2 minuti:

1. Su Telegram cerca @BotFather
2. Scrivi /newbot -> nome VendiBot
3. Copia il token tipo 123456:ABC...
4. Su Render.com -> tuo servizio -> Environment -> aggiungi:
   TELEGRAM_BOT_TOKEN = token
   TELEGRAM_CHAT_ID = tuo ID

Per trovare Chat ID:
- Cerca @userinfobot su Telegram
- Scrivi /start -> ti da il tuo ID
- Mettilo in ENV e fai Deploy

Poi clicca Test TG qui nell'app.`);
}

async function loadTF(tf, withTelegram=false){
  curTF=tf;
  document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active'));
  var el=document.getElementById('b'+tf); if(el) el.classList.add('active');
  document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center;color:#94a3b8">⚡ Carico '+tf+(withTelegram?' + invio Telegram se ENTRA...':'...')+'</div>';
  try{
    var url='/api/signals?tf='+tf+(withTelegram?'&telegram=1':'');
    var res=await fetch(url);
    var d=await res.json();
    lastData=d;
    var html='';
    for(var name in d.coins){
      var info=d.coins[name];
      var iconClass=name=='BTC'?'btc':name=='ETH'?'eth':'oro';
      var ico=name=='BTC'?'B':name=='ETH'?'E':'Au';
      var qBadge=qualityBadge(info);
      var price='$'+info.price.toFixed(2);
      var spark=sparklineSVG(info.spark);
      var actionText=info.quality_color=='loading'?'...': info.quality_color=='entra' ? (info.signal=='COMPRA'?'🚀 COMPRA ORA':'🔻 VENDI ORA') : '⏸️ Aspetta';
      html+=`<div class="coin-row" onclick="openDetails('${name}')"><div style="display:flex;gap:10px;align-items:center"><div class="coin-icon ${iconClass}">${ico}</div><div><b style="font-size:15px">${name}</b> - ${price}${spark}<div style="font-size:11px;color:#94a3b8;margin-top:2px">RSI ${info.rsi} • Stoch ${info.stoch_k} • ${actionText}</div></div></div><div style="text-align:right">${qBadge}<div style="font-size:11px;color:#64748b;margin-top:4px">${info.signal} ${info.conf>0?info.conf+'%':''}</div></div></div>`;
    }
    if(d.telegram_results && Object.keys(d.telegram_results).length>0){
      html+=`<div style="background:#052e16;padding:10px 14px;font-size:11px;color:#86efac;border-top:1px solid #16a34a">📱 Inviati su Telegram: ${Object.keys(d.telegram_results).join(', ')}</div>`;
    }
    document.getElementById('coins').innerHTML=html;
  }catch(e){
    document.getElementById('coins').innerHTML='<div style="padding:20px;color:#ef4444">Errore: '+e.message+'</div>';
  }
}

async function openDetails(coin){
  if(!lastData) return;
  var info=lastData.coins[coin];
  document.getElementById('mCoin').textContent=coin+' - $'+info.price.toFixed(2);
  document.getElementById('mPrice').textContent=info.source+'/'+info.ohlc_src+' - '+info.signal+' '+info.conf+'% - TF '+curTF;
  var big=document.getElementById('mQualityBig');
  big.className='big-box '+(info.quality_color=='entra'?'entra-big':info.quality_color=='quasi'?'quasi-big':'wait-big');
  big.innerHTML=info.quality_color=='entra'?`<div style="font-size:22px;font-weight:900;color:#22c55e">${info.quality_label} - ${info.signal} ${info.conf}%</div>`:`<div style="font-size:20px;font-weight:900">${info.quality_label}</div>`;
  document.getElementById('mSL').textContent='$'+Math.round(info.sl);
  document.getElementById('mSLpct').textContent='-'+info.sl_pct.toFixed(2)+'%';
  document.getElementById('mTP').textContent='$'+Math.round(info.tp);
  document.getElementById('mTPpct').textContent='+'+info.tp_pct.toFixed(2)+'%';
  document.getElementById('sRSI').textContent=info.rsi+' / '+info.rsi_fast;
  document.getElementById('sStoch').textContent=info.stoch_k;
  document.getElementById('sEMA').textContent=Math.round(info.ema9)+' / '+Math.round(info.ema21);
  document.getElementById('sST').textContent=(info.st_trend==1?'UP ':'DOWN ')+'$'+Math.round(info.st_val);
  document.getElementById('sVWAP').textContent='$'+Math.round(info.vwap);
  document.getElementById('sADX').textContent=info.adx;
  document.getElementById('mSimpleText').textContent=info.quality_simple;
  document.getElementById('modal').classList.add('show');
  window._currentCoin=coin;
}
function closeModal(){ document.getElementById('modal').classList.remove('show'); }

async function testTelegram(){
  document.getElementById('teleBanner').textContent='Invio test Telegram...';
  try{
    var r=await fetch('/api/telegram_test');
    var j=await r.json();
    if(j.ok){
      alert('✅ Test Telegram inviato! Controlla Telegram ora.');
    }else{
      alert('❌ Errore: '+j.error);
    }
    checkTelegram();
  }catch(e){ alert('Errore: '+e.message); }
}
async function sendThisToTelegram(){
  if(!window._currentCoin) return;
  var coin=window._currentCoin;
  var info=lastData.coins[coin];
  try{
    var r=await fetch(`/api/signals?tf=${curTF}&telegram=1`);
    var j=await r.json();
    alert('Tentativo invio Telegram per '+coin+' - Controlla Telegram. Risultato: '+JSON.stringify(j.telegram_results[coin]||'nessun ENTRA, serve >=75%'));
  }catch(e){ alert(e.message); }
}

checkTelegram();
loadTF('5m');
setInterval(()=>loadTF(curTF), 15000);
</script>
</body></html>
"""
    return Response(html, mimetype="text/html; charset=utf-8")

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
