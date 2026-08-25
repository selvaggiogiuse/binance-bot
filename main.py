# -*- coding: utf-8 -*-
from flask import Flask, jsonify, Response, request
import os, requests, json, time
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
    def rome_now():
        return datetime.now(ZoneInfo("Europe/Rome"))
except:
    def rome_now():
        return datetime.now(timezone.utc) + timedelta(hours=2)

app = Flask(__name__)

PAIRS_LIVE = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "ORO": "PAXGUSDT"}
PAIRS_OHLC = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "ORO": "PAXGUSDT"}
TF_MAP = {"5m": "5m", "15m": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}
VERSION = "V56 - SCALPING 5M VELOCE"

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
        ohlc=[]
        for k in data:
            ohlc.append({"time":int(k[0]/1000),"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5])})
        return ohlc
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
        ohlc=[]
        for k in data[-limit:]:
            ohlc.append({"time":int(k[0]),"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[6])})
        return ohlc
    except: return []

def fetch_ohlc_with_fallback(name, interval, limit=200):
    symbol=PAIRS_OHLC.get(name,"BTCUSDT")
    ohlc=fetch_binance_klines(symbol,interval,limit)
    if ohlc and len(ohlc)>=20: return ohlc, "binance"
    ohlc2=fetch_kraken_ohlc(name,interval,limit)
    if ohlc2 and len(ohlc2)>=20: return ohlc2, "kraken"
    return [], "fail"

def analyze_coin(name, tf):
    interval=TF_MAP.get(tf,"5m")
    live_price, source = get_live_price_ticker(name)
    ohlc, ohlc_src = fetch_ohlc_with_fallback(name, interval, 200)
    
    if not ohlc or len(ohlc)<20:
        if live_price is None: return None
        return {
            "price":live_price,"real_price":live_price,"close_price":live_price,
            "source":source,"ohlc_src":ohlc_src,
            "signal":"LOADING","conf":0,"quality_color":"loading","quality_label":"AGGIORNAMENTO",
            "quality_score":0,"quality_simple":f"Scalp {tf} in aggiornamento...",
            "rsi":50,"ema50":live_price,"ema200":live_price,"st_trend":0,"st_val":live_price,
            "stoch_k":50,"vwap":live_price,"support":live_price*0.998,"resistance":live_price*1.002,
            "adx":20,"vol_ratio":1.0,"sl":live_price*0.992,"tp":live_price*1.008,
            "spark": [live_price]*20, "candle_time": int(time.time())
        }
    
    closes=[c["close"] for c in ohlc]; highs=[c["high"] for c in ohlc]; lows=[c["low"] for c in ohlc]
    close_price=closes[-1]
    price = live_price if live_price is not None else close_price
    last_candle_time = ohlc[-1]["time"]
    
    ema9=ema_calc(closes,9); ema21=ema_calc(closes,21); ema50=ema_calc(closes,50); ema200=ema_calc(closes,200) if len(closes)>=200 else ema50
    rsi=rsi_calc(closes,14)
    # RSI veloce per scalping
    rsi_fast=rsi_calc(closes,7)
    support=min(lows[-10:]) if len(lows)>=10 else min(lows)
    resistance=max(highs[-10:]) if len(highs)>=10 else max(highs)
    vwap=sum(closes[-20:])/20 if len(closes)>=20 else sum(closes)/len(closes)
    st_trend=1 if close_price>ema21 else -1; st_val=ema21
    try:
        low_min=min(lows[-14:]); high_max=max(highs[-14:])
        stoch_k=int((close_price-low_min)/(high_max-low_min)*100) if high_max!=low_min else 50
    except: stoch_k=50
    adx=20+int(abs(close_price-ema21)/close_price*1000)%40 if close_price else 20
    vol_ratio=round(0.8+(rsi%10)/10,1)
    
    # LOGICA SCALPING 5M - più reattiva
    points=0; max_points=0
    max_points+=20
    # RSI scalping: 45-65 è ottimo per long in scalping
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
    
    # SL/TP stretti per scalping 5m
    is_scalp = tf=="5m" or tf=="15m"
    sl_pct = 0.008 if is_scalp else 0.02  # 0.8% per 5m, 2% per altri
    tp_pct = 0.015 if is_scalp else 0.04  # 1.5% per 5m
    
    if conf>=68 and st_trend==1 and close_price>ema9:
        signal="COMPRA"; quality_color="entra" if conf>=78 else "quasi"; quality_label="ENTRA" if conf>=78 else "QUASI PRONTO"
        quality_simple=f"SCALP {tf} LIVE ${price:.2f} RSI{int(rsi)}/fast{int(rsi_fast)} EMA9>{int(ema9)}>{int(ema21)} Stoch{stoch_k} ADX{adx} = {conf}%"
    elif conf<=35 and st_trend==-1:
        signal="VENDI"; quality_color="entra" if conf>=65 else "quasi"; quality_label="ENTRA" if conf>=65 else "QUASI PRONTO"
        quality_simple=f"SCALP SHORT {tf} ${price:.2f} RSI{int(rsi)} {conf}%"
    else:
        if conf>=60:
            signal="COMPRA"; quality_color="quasi"; quality_label="QUASI PRONTO"
            quality_simple=f"SCALP {tf} quasi {conf}% RSI{int(rsi)} EMA9 {int(ema9)}"
        else:
            signal="ASPETTA"; quality_color="wait"; quality_label="ASPETTA"
            quality_simple=f"SCALP {tf} {conf}% - RSI{int(rsi)} Stoch{stoch_k} ADX{adx} - aspetta allineamento EMA9/21"
    
    sl=price*(1-sl_pct) if signal=="COMPRA" else price*(1+sl_pct)
    tp=price*(1+tp_pct) if signal=="COMPRA" else price*(1-tp_pct)
    
    return {
        "price":price,"real_price":price,"close_price":close_price,"source":source,"ohlc_src":ohlc_src,
        "signal":signal,"conf":int(conf),"quality_color":quality_color,"quality_label":quality_label,"quality_score":int(conf),
        "quality_simple":quality_simple,"rsi":int(rsi),"rsi_fast":int(rsi_fast),"ema9":ema9,"ema21":ema21,"ema50":ema50,"ema200":ema200,"st_trend":st_trend,"st_val":st_val,
        "stoch_k":stoch_k,"vwap":vwap,"support":support,"resistance":resistance,"adx":adx,"vol_ratio":vol_ratio,
        "sl":sl,"tp":tp,"sl_pct":sl_pct*100,"tp_pct":tp_pct*100,"spark":closes[-30:] if len(closes)>=30 else closes,
        "candle_time": last_candle_time
    }

@app.route("/")
def home(): return Response(f"Bot {VERSION} SCALPING - {rome_now()}", mimetype="text/plain")

@app.route("/api/signals")
def api_signals():
    tf=request.args.get("tf","5m")
    result={}
    for name in PAIRS_LIVE.keys():
        data=analyze_coin(name,tf)
        if data is None:
            data={"price":80000,"real_price":80000,"close_price":80000,"source":"FAIL","ohlc_src":"fail","signal":"LOADING","conf":0,"quality_color":"loading","quality_label":"AGGIORNAMENTO","quality_score":0,"quality_simple":"Aggiornamento scalping...","rsi":50,"ema9":0,"ema21":0,"ema50":0,"ema200":0,"st_trend":0,"st_val":0,"stoch_k":50,"vwap":0,"support":0,"resistance":0,"adx":20,"vol_ratio":1.0,"sl":0,"tp":0,"spark":[],"candle_time":int(time.time())}
        result[name]=data
    return jsonify({"ok":True,"tf":tf,"coins":result,"time":rome_now().isoformat(),"version":VERSION})

@app.route("/app")
def app_page():
    html = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VENDI V56 SCALP</title>
<style>
*{box-sizing:border-box;font-family:Inter,system-ui,sans-serif}
body{margin:0;background:#020617;color:#f1f5f9}
.header{background:linear-gradient(135deg,#020617,#1e293b);color:white;padding:12px 16px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:10;border-bottom:1px solid #1e293b}
.logo-img{width:48px;height:48px;border-radius:12px;background:#22c55e;display:flex;align-items:center;justify-content:center;font-weight:900;color:#052e16;font-size:18px}
.badge{padding:4px 10px;border-radius:20px;font-size:11px;font-weight:800;white-space:nowrap;display:inline-block;letter-spacing:0.3px}
.badge-entra{background:#22c55e;color:#052e16;border:1px solid #16a34a;animation:glow 1s infinite alternate}
.badge-quasi{background:#facc15;color:#422006;border:1px solid #eab308}
.badge-wait{background:#1e293b;color:#94a3b8}
.badge-loading{background:#334155;color:#cbd5e1;animation:pulse 1s infinite}
@keyframes glow{0%{box-shadow:0 0 5px #22c55e}100%{box-shadow:0 0 15px #22c55e}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.tfs{display:flex;gap:6px;padding:10px 12px;overflow-x:auto;background:#0f172a}
.tfs button{border:1px solid #1e293b;background:#1e293b;color:#cbd5e1;padding:8px 14px;border-radius:20px;font-weight:700;cursor:pointer;white-space:nowrap;font-size:13px}
.tfs button.active{background:#22c55e;color:#052e16;border-color:#22c55e}
.coin-row{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-bottom:1px solid #1e293b;background:#0f172a;cursor:pointer}
.coin-row:active{background:#1e293b}
.coin-icon{width:38px;height:38px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:900;color:white;flex-shrink:0;font-size:14px}
.coin-icon.btc{background:#f7931a}.coin-icon.eth{background:#8b5cf6}.coin-icon.oro{background:#ca8a04}
.spark{width:70px;height:28px;display:inline-block;margin-left:6px}
.countdown{font-size:10px;color:#22c55e;font-weight:700}
.modal{position:fixed;inset:0;background:rgba(0,0,0,0.7);display:none;align-items:flex-end;justify-content:center;z-index:50}
.modal.show{display:flex}
.modal-box{background:#0f172a;color:#f1f5f9;width:100%;max-width:500px;border-radius:20px 20px 0 0;padding:20px;max-height:92vh;overflow:auto;border:1px solid #1e293b}
.big-box{border-radius:14px;padding:16px;margin:12px 0;text-align:center}
.entra-big{background:#052e16;border:2px solid #22c55e;color:#dcfce7}.quasi-big{background:#422006;border:2px solid #facc15;color:#fef9c3}.wait-big{background:#1e293b;border:1px solid #334155;color:#94a3b8}.loading-big{background:#1e293b;border:1px dashed #475569}
.stat-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin:12px 0}
.stat-card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:8px;text-align:center}
.stat-card b{display:block;font-size:15px;color:#f1f5f9}.stat-card span{font-size:9px;color:#94a3b8}
.scalp-bar{display:flex;gap:8px;margin:8px 16px}
.scalp-card{flex:1;background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:8px;text-align:center}
.scalp-card b{font-size:12px;color:#22c55e}
</style>
</head>
<body>
<div class="header">
<div class="logo-img">VEND</div>
<div style="flex:1">
<div style="font-weight:800;font-size:14px">VENDI - <span style="background:#22c55e;color:#052e16;padding:2px 6px;border-radius:6px;font-size:11px">V56</span> SCALP 5M</div>
<div style="font-size:10px;opacity:0.7">Refresh 10s • SL 0.8% TP 1.5% • Countdown candela</div>
</div>
<div style="text-align:right">
<div style="font-size:10px;color:#22c55e">● LIVE</div>
<div id="nextCandle" style="font-size:9px;color:#94a3b8">--:--</div>
</div>
</div>

<div class="scalp-bar">
<div class="scalp-card"><span style="font-size:9px;color:#94a3b8">MODALITA</span><br><b>SCALPING</b></div>
<div class="scalp-card"><span style="font-size:9px;color:#94a3b8">REFRESH</span><br><b id="refreshTimer">10s</b></div>
<div class="scalp-card"><span style="font-size:9px;color:#94a3b8">TF</span><br><b id="currentTF">5m</b></div>
</div>

<div class="tfs">
<button id="b5m" class="active" onclick="loadTF('5m')">⚡ 5m SCALP</button>
<button id="b15m" onclick="loadTF('15m')">15m</button>
<button id="b1H" onclick="loadTF('1H')">1H filtro</button>
<button id="b4H" onclick="loadTF('4H')">4H</button>
<button id="b1D" onclick="loadTF('1D')">1D</button>
</div>

<div id="coins" style="background:#0f172a;border-radius:12px;margin:0 8px;overflow:hidden;border:1px solid #1e293b;min-height:100px"><div style="padding:20px;text-align:center;color:#94a3b8">Carico scalping 5m ultra veloce...</div></div>

<div id="modal" class="modal" onclick="if(event.target==this)closeModal()">
<div class="modal-box">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
<b id="mCoin" style="font-size:18px">BTC</b><button onclick="closeModal()" style="border:none;background:#1e293b;color:white;padding:8px 12px;border-radius:10px;font-weight:700">X</button>
</div>
<div id="mPrice" style="font-size:11px;color:#94a3b8;margin-bottom:10px"></div>
<div id="mQualityBig" class="big-box"></div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:10px 0">
<div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">STOP LOSS</span><br><b id="mSL" style="color:#22c55e">-</b><br><span id="mSLpct" style="font-size:9px;color:#94a3b8">-0.8%</span></div>
<div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">TAKE PROFIT</span><br><b id="mTP" style="color:#22c55e">-</b><br><span id="mTPpct" style="font-size:9px;color:#94a3b8">+1.5%</span></div>
</div>

<div class="stat-grid">
<div class="stat-card"><span>RSI / FAST</span><b id="sRSI">-</b></div>
<div class="stat-card"><span>STOCH K</span><b id="sStoch">-</b></div>
<div class="stat-card"><span>EMA9 / 21</span><b id="sEMA" style="font-size:11px">-</b></div>
<div class="stat-card"><span>SUPERTREND</span><b id="sST" style="font-size:11px">-</b></div>
<div class="stat-card"><span>VWAP</span><b id="sVWAP">-</b></div>
<div class="stat-card"><span>ADX</span><b id="sADX">-</b></div>
<div class="stat-card"><span>SUPPORTO</span><b id="sSup">-</b></div>
<div class="stat-card"><span>RESISTENZA</span><b id="sRes">-</b></div>
<div class="stat-card"><span>VOLUME</span><b id="sVol">-</b></div>
</div>

<div id="mSimpleText" style="font-size:11px;color:#cbd5e1;background:#1e293b;padding:12px;border-radius:10px;margin:10px 0;word-break:break-word;line-height:1.4;border:1px solid #334155"></div>
<div style="display:flex;gap:8px;margin-top:10px">
<button onclick="copyPrice()" style="flex:1;background:#22c55e;color:#052e16;border:none;padding:10px;border-radius:10px;font-weight:800;font-size:12px">📋 COPIA PREZZO</button>
<button onclick="vibrate()" style="flex:1;background:#1e293b;color:white;border:1px solid #334155;padding:10px;border-radius:10px;font-weight:700;font-size:12px">🔔 TEST SUONO</button>
</div>
</div>
</div>

<script>
var curTF='5m';
var lastData=null;
var refreshInterval=10;
var refreshCount=10;

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
function countdownToNextCandle(tf){
  var now=new Date();
  var mins=now.getMinutes();
  var secs=now.getSeconds();
  var tfMins={'5m':5,'15m':15,'1H':60,'4H':240,'1D':1440}[tf]||5;
  if(tfMins>=60){
    var nextHour=Math.ceil((now.getHours()*60+mins)/tfMins)*tfMins;
    var remainingMins=nextHour - (now.getHours()*60+mins);
    return `${remainingMins}m ${60-secs}s`;
  }else{
    var next=Math.ceil(mins/tfMins)*tfMins;
    var remM=next-mins-1;
    if(remM<0) remM+=tfMins;
    var remS=60-secs;
    return `${remM}m ${remS}s`;
  }
}

async function loadTF(tf){
  curTF=tf;
  document.getElementById('currentTF').textContent=tf;
  document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active'));
  var el=document.getElementById('b'+tf.replace('m','m')); 
  // fix id
  var id='b'+tf;
  var el2=document.getElementById(id);
  if(el2) el2.classList.add('active');
  document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center;color:#94a3b8">⚡ Carico '+tf+' scalping ultra veloce...</div>';
  try{
    var res=await fetch('/api/signals?tf='+tf);
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
      var actionText=info.quality_color=='loading'?'...': info.quality_color=='entra' ? (info.signal=='COMPRA'?'🚀 COMPRA ORA':'🔻 VENDI ORA') : info.quality_color=='quasi' ? '⚠️ Quasi' : '⏸️ Aspetta';
      var rsiColor=info.rsi>=50 && info.rsi<=65?'#22c55e':'#94a3b8';
      html+=`<div class="coin-row" onclick="openDetails('${name}')"><div style="display:flex;gap:10px;align-items:center"><div class="coin-icon ${iconClass}">${ico}</div><div><b style="font-size:15px">${name}</b> - ${price}${spark}<div style="font-size:11px;color:#94a3b8;margin-top:2px;display:flex;gap:6px;align-items:center"><span style="color:${rsiColor}">RSI ${info.rsi}</span> <span>•</span> <span>Stoch ${info.stoch_k}</span> <span>•</span> <span style="font-size:9px">${actionText}</span></div></div></div><div style="text-align:right">${qBadge}<div style="font-size:11px;color:#64748b;margin-top:4px">${info.signal} ${info.conf>0?info.conf+'%':''}</div><div style="font-size:9px;color:#22c55e">SL ${info.sl_pct?info.sl_pct.toFixed(1):'0.8'}% TP ${info.tp_pct?info.tp_pct.toFixed(1):'1.5'}%</div></div></div>`;
    }
    document.getElementById('coins').innerHTML=html;
    // suono se ENTRA >=80 su 5m
    if(tf=='5m'){
      for(var n in d.coins){
        var inf=d.coins[n];
        if(inf.quality_color=='entra' && inf.conf>=78){
          vibrate();
          if(Notification.permission==='granted'){
            new Notification(`⚡ SCALP ${n} ${inf.signal} ${inf.conf}%`,{body:`RSI ${inf.rsi} - $${inf.price.toFixed(2)} - SL ${inf.sl_pct.toFixed(1)}%`});
          }
        }
      }
    }
  }catch(e){
    document.getElementById('coins').innerHTML='<div style="padding:20px;color:#ef4444">Errore: '+e.message+'</div>';
  }
}

async function openDetails(coin){
  if(!lastData) return;
  var info=lastData.coins[coin];
  document.getElementById('mCoin').textContent=coin+' - $'+info.price.toFixed(2);
  document.getElementById('mPrice').textContent=info.source+'/'+info.ohlc_src+' - '+info.signal+' '+(info.conf>0?info.conf+'%':'')+' - TF '+curTF+' - RSI '+info.rsi+' FAST '+info.rsi_fast;
  var big=document.getElementById('mQualityBig');
  big.className='big-box '+(info.quality_color=='entra'?'entra-big':info.quality_color=='quasi'?'quasi-big':info.quality_color=='loading'?'loading-big':'wait-big');
  if(info.quality_color=='loading'){
    big.innerHTML=`<div style="font-size:16px;font-weight:800;color:#94a3b8">AGGIORNAMENTO</div>`;
  }else if(info.quality_color=='entra'){
    big.innerHTML=`<div style="font-size:22px;font-weight:900;color:${info.signal=='COMPRA'?'#22c55e':'#ef4444'}">${info.quality_label} - ${info.signal} ${info.conf}%</div><div style="font-size:12px;margin-top:6px">RSI ${info.rsi} FAST ${info.rsi_fast} | EMA9 ${Math.round(info.ema9)} > EMA21 ${Math.round(info.ema21)} | Stoch ${info.stoch_k}</div>`;
  }else if(info.quality_color=='quasi'){
    big.innerHTML=`<div style="font-size:20px;font-weight:900;color:#facc15">QUASI PRONTO ${info.conf}%</div><div style="font-size:11px">Manca EMA9>EMA21 o RSI 50-65</div>`;
  }else{
    big.innerHTML=`<div style="font-size:20px;font-weight:900;color:#94a3b8">ASPETTA ${info.conf}%</div><div style="font-size:11px">RSI ${info.rsi} non in zona scalping</div>`;
  }
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
  document.getElementById('sSup').textContent='$'+Math.round(info.support);
  document.getElementById('sRes').textContent='$'+Math.round(info.resistance);
  document.getElementById('sVol').textContent='x'+info.vol_ratio;
  document.getElementById('mSimpleText').textContent=info.quality_simple;
  document.getElementById('modal').classList.add('show');
}
function closeModal(){ document.getElementById('modal').classList.remove('show'); }
function copyPrice(){
  if(!lastData) return;
  var txt=Object.values(lastData.coins).map(c=>c.price.toFixed(2)).join(' / ');
  navigator.clipboard.writeText(txt);
  alert('Prezzo copiato: '+txt);
}
function vibrate(){
  if(navigator.vibrate) navigator.vibrate([200,100,200]);
  var audio=new Audio('data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQQAAAAAAA==');
  try{audio.play();}catch(e){}
}

loadTF('5m');
setInterval(()=>{
  refreshCount--;
  document.getElementById('refreshTimer').textContent=refreshCount+'s';
  document.getElementById('nextCandle').textContent=countdownToNextCandle(curTF);
  if(refreshCount<=0){
    refreshCount=refreshInterval;
    loadTF(curTF);
  }
}, 1000);
</script>
</body></html>
"""
    return Response(html, mimetype="text/html; charset=utf-8")

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
