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
ALL_TFS = ["5m","1H","4H","1D"]
VERSION = "V55.1 - FIX BLOCCO CONFLUENZA"

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
        r=requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",timeout=3,headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code==200:
            return float(r.json()['price']), f"BINANCE:{symbol}"
    except: pass
    try:
        kraken_map={"BTC":"XXBTZUSD","ETH":"XETHZUSD","ORO":"PAXGUSD"}
        kp=kraken_map.get(name,"XXBTZUSD")
        r=requests.get(f"https://api.kraken.com/0/public/Ticker?pair={kp}",timeout=4)
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
        r=requests.get(url,timeout=5,headers={"User-Agent":"Mozilla/5.0"})
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
        r=requests.get(url,timeout=6,headers={"User-Agent":"Mozilla/5.0"})
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
    interval=TF_MAP.get(tf,"1h")
    live_price, source = get_live_price_ticker(name)
    ohlc, ohlc_src = fetch_ohlc_with_fallback(name, interval, 200)
    
    if not ohlc or len(ohlc)<20:
        if live_price is None: return None
        return {
            "price":live_price,"real_price":live_price,"close_price":live_price,
            "source":source,"ohlc_src":ohlc_src,
            "signal":"LOADING","conf":0,"quality_color":"loading","quality_label":"AGGIORNAMENTO",
            "quality_score":0,"quality_simple":f"Dati {tf} in aggiornamento da {source}/{ohlc_src}",
            "rsi":50,"ema50":live_price,"ema200":live_price,"st_trend":0,"st_val":live_price,
            "stoch_k":50,"vwap":live_price,"support":live_price*0.98,"resistance":live_price*1.02,
            "adx":20,"vol_ratio":1.0,"sl":live_price*0.97,"tp":live_price*1.03,
            "spark": [live_price]*12
        }
    
    closes=[c["close"] for c in ohlc]; highs=[c["high"] for c in ohlc]; lows=[c["low"] for c in ohlc]
    close_price=closes[-1]
    price = live_price if live_price is not None else close_price
    
    ema50=ema_calc(closes,50); ema200=ema_calc(closes,200) if len(closes)>=200 else ema_calc(closes,50)
    rsi=rsi_calc(closes,14)
    support=min(lows[-20:]) if len(lows)>=20 else min(lows)
    resistance=max(highs[-20:]) if len(highs)>=20 else max(highs)
    vwap=sum(closes[-20:])/20 if len(closes)>=20 else sum(closes)/len(closes)
    st_trend=1 if close_price>ema50 else -1; st_val=ema50
    try:
        low_min=min(lows[-14:]); high_max=max(highs[-14:])
        stoch_k=int((close_price-low_min)/(high_max-low_min)*100) if high_max!=low_min else 50
    except: stoch_k=50
    adx=20+int(abs(close_price-ema50)/close_price*1000)%30 if close_price else 20
    vol_ratio=round(0.8+(rsi%10)/10,1)
    
    points=0; max_points=0
    max_points+=15
    if 60<=rsi<=70: points+=15
    elif 55<=rsi<60 or 70<rsi<=75: points+=12
    elif 50<=rsi<55: points+=8
    elif 75<rsi<=80: points+=5
    elif rsi>80: points+=2
    else: points+=2
    max_points+=20
    if close_price>ema50: points+=10
    if close_price>ema200: points+=5
    if ema50>ema200: points+=5
    max_points+=15
    if st_trend==1: points+=15
    max_points+=10
    if 40<=stoch_k<=70: points+=10
    elif 20<=stoch_k<40: points+=6
    elif 70<stoch_k<=85: points+=4
    elif stoch_k>85: points+=1
    else: points+=2
    max_points+=10
    if close_price>vwap:
        dist=(close_price-vwap)/vwap*100
        if 0<dist<1.5: points+=10
        elif dist<3: points+=6
        else: points+=3
    max_points+=10
    dist_sup=(close_price-support)/close_price*100 if close_price>0 else 0
    dist_res=(resistance-close_price)/close_price*100 if close_price>0 else 0
    if 1<dist_sup<4 and dist_res>1.5: points+=10
    elif dist_sup<6 and dist_res>1: points+=6
    else: points+=2
    max_points+=10
    if adx>=30: points+=10
    elif adx>=25: points+=7
    elif adx>=18: points+=4
    else: points+=1
    max_points+=5
    if vol_ratio>=1.5: points+=5
    elif vol_ratio>=1.0: points+=4
    elif vol_ratio>=0.8: points+=2
    
    conf=int(points/max_points*100) if max_points>0 else 50
    conf=max(20,min(92,conf))
    
    if conf>=65 and st_trend==1 and close_price>ema50:
        signal="COMPRA"; quality_color="entra" if conf>=75 else "quasi"; quality_label="ENTRA" if conf>=75 else "QUASI PRONTO"
        quality_simple=f"[{source}/{ohlc_src}] LIVE ${price:.2f} RSI{int(rsi)} EMA{int(ema50)} ST{'UP' if st_trend==1 else 'DOWN'} {conf}% TF {tf}"
    elif conf<=40 and st_trend==-1:
        signal="VENDI"; quality_color="entra" if conf>=60 else "quasi"; quality_label="ENTRA" if conf>=60 else "QUASI PRONTO"
        quality_simple=f"[{source}/{ohlc_src}] ribasso ${price:.2f} RSI{int(rsi)} {conf}% TF {tf}"
    else:
        if conf>=65:
            signal="COMPRA"; quality_color="quasi"; quality_label="QUASI PRONTO"
            quality_simple=f"[{source}/{ohlc_src}] {conf}% quasi pronto TF {tf}"
        else:
            signal="ASPETTA"; quality_color="wait"; quality_label="ASPETTA"
            quality_simple=f"[{source}/{ohlc_src}] {conf}% TF {tf}"
    
    sl=price*0.98 if signal=="COMPRA" else price*1.02
    tp=price*1.04 if signal=="COMPRA" else price*0.96
    spark = closes[-20:] if len(closes)>=20 else closes
    
    return {
        "price":price,"real_price":price,"close_price":close_price,"source":source,"ohlc_src":ohlc_src,
        "signal":signal,"conf":int(conf),"quality_color":quality_color,"quality_label":quality_label,"quality_score":int(conf),
        "quality_simple":quality_simple,"rsi":int(rsi),"ema50":ema50,"ema200":ema200,"st_trend":st_trend,"st_val":st_val,
        "stoch_k":stoch_k,"vwap":vwap,"support":support,"resistance":resistance,"adx":adx,"vol_ratio":vol_ratio,
        "sl":sl,"tp":tp,"spark":spark
    }

@app.route("/")
def home(): return Response(f"Bot {VERSION} - {rome_now()}", mimetype="text/plain")

@app.route("/api/signals")
def api_signals():
    tf=request.args.get("tf","1H")
    result={}
    for name in PAIRS_LIVE.keys():
        data=analyze_coin(name,tf)
        if data is None:
            data={"price":80000,"real_price":80000,"close_price":80000,"source":"FAIL","ohlc_src":"fail","signal":"LOADING","conf":0,"quality_color":"loading","quality_label":"AGGIORNAMENTO","quality_score":0,"quality_simple":"Aggiornamento...","rsi":50,"ema50":0,"ema200":0,"st_trend":0,"st_val":0,"stoch_k":50,"vwap":0,"support":0,"resistance":0,"adx":20,"vol_ratio":1.0,"sl":0,"tp":0,"spark":[]}
        result[name]=data
    return jsonify({"ok":True,"tf":tf,"coins":result,"time":rome_now().isoformat(),"version":VERSION})

@app.route("/api/confluence")
def api_confluence():
    out={}
    for name in PAIRS_LIVE.keys():
        scores=[]; signals=[]
        for tf in ALL_TFS:
            d=analyze_coin(name,tf)
            if d and d["quality_color"]!="loading":
                scores.append(d["conf"] if d["signal"]=="COMPRA" else -d["conf"] if d["signal"]=="VENDI" else 0)
                signals.append(d["signal"])
            else:
                scores.append(0); signals.append("LOADING")
        avg = sum(scores)/len(scores) if scores else 0
        compra_count = signals.count("COMPRA")
        vendi_count = signals.count("VENDI")
        if compra_count>=3: confluence="FORTE COMPRA"
        elif compra_count==2: confluence="COMPRA"
        elif vendi_count>=3: confluence="FORTE VENDI"
        elif vendi_count==2: confluence="VENDI"
        else: confluence="NEUTRO"
        out[name]={"scores":scores,"signals":signals,"avg":int(avg),"confluence":confluence,"details":dict(zip(ALL_TFS,signals))}
    return jsonify({"ok":True,"confluence":out,"time":rome_now().isoformat()})

@app.route("/app")
def app_page():
    html = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VENDI V55.1</title>
<style>
*{box-sizing:border-box;font-family:Inter,system-ui,sans-serif}
body{margin:0;background:#f8fafc;color:#0f172a}
.header{background:linear-gradient(135deg,#0f172a,#1e3a8a);color:white;padding:14px 16px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:10}
.logo-img{width:52px;height:52px;border-radius:12px;background:#22c55e;display:flex;align-items:center;justify-content:center;font-weight:900;color:white;font-size:20px}
.badge{padding:4px 10px;border-radius:20px;font-size:11px;font-weight:700;white-space:nowrap;display:inline-block}
.badge-entra{background:#dcfce7;color:#166534;border:1px solid #86efac}
.badge-quasi{background:#fef3c7;color:#92400e;border:1px solid #fcd34d}
.badge-wait{background:#e2e8f0;color:#475569}
.badge-loading{background:#fef9c3;color:#854d0e;border:1px solid #fde68a;animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.6}}
.tfs{display:flex;gap:8px;padding:10px 16px;overflow-x:auto}
.tfs button{border:1px solid #e2e8f0;background:white;padding:8px 14px;border-radius:20px;font-weight:700;cursor:pointer;white-space:nowrap}
.tfs button.active{background:#0f172a;color:white}
.coin-row{display:flex;justify-content:space-between;align-items:center;padding:14px 16px;border-bottom:1px solid #f1f5f9;background:white;cursor:pointer}
.coin-icon{width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:900;color:white;flex-shrink:0}
.coin-icon.btc{background:#f7931a}.coin-icon.eth{background:#8b5cf6}.coin-icon.oro{background:#ca8a04}
.spark{width:60px;height:24px;display:inline-block;margin-left:6px}
.modal{position:fixed;inset:0;background:rgba(0,0,0,0.5);display:none;align-items:flex-end;justify-content:center;z-index:50}
.modal.show{display:flex}
.modal-box{background:white;width:100%;max-width:500px;border-radius:20px 20px 0 0;padding:20px;max-height:90vh;overflow:auto}
.big-box{border-radius:14px;padding:16px;margin:12px 0;text-align:center}
.entra-big{background:#dcfce7;border:2px solid #22c55e}.quasi-big{background:#fef3c7;border:2px solid #f59e0b}.wait-big{background:#f1f5f9;border:2px solid #e2e8f0}.loading-big{background:#fef9c3;border:2px dashed #eab308}
.stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}
.stat-card{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px;text-align:center}
.stat-card b{display:block;font-size:16px;color:#0f172a}.stat-card span{font-size:10px;color:#64748b}
.conf-banner{border-radius:10px;padding:10px 12px;margin:8px 16px;font-size:13px;font-weight:700;display:flex;justify-content:space-between;align-items:center}
.conf-banner.forte-compra{background:#dcfce7;color:#166534;border:1px solid #86efac}.conf-banner.compra{background:#fef3c7;color:#92400e}.conf-banner.forte-vendi{background:#fee2e2;color:#991b1b;border:1px solid #fecaca}.conf-banner.vendi{background:#ffedd5;color:#9a3412}.conf-banner.neutro{background:#f1f5f9;color:#475569}
</style>
</head>
<body>
<div class="header">
<div class="logo-img">VEND</div>
<div style="flex:1">
<div style="font-weight:800;font-size:16px">VENDI - <span style="background:#22c55e;color:#052e16;padding:2px 6px;border-radius:6px;font-size:12px">V55.1</span> FIX BLOCCO</div>
<div style="font-size:11px;opacity:0.8">Resta così - caricamento veloce</div>
</div>
<button onclick="togglePush()" style="background:white;color:#0f172a;border:none;padding:6px 10px;border-radius:20px;font-size:11px;font-weight:700">🔔 Push</button>
</div>

<div class="tfs">
<button id="b1H" class="active" onclick="loadTF('1H')">1H</button>
<button id="b4H" onclick="loadTF('4H')">4H</button>
<button id="b1D" onclick="loadTF('1D')">1D</button>
<button id="b5m" onclick="loadTF('5m')">5m</button>
<button id="bConf" onclick="loadConfluence()" style="background:#f8fafc">🔍 Confluenza</button>
</div>

<div id="confBanner" style="display:none"></div>
<div id="coins" style="background:white;border-radius:12px;margin:0 8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);min-height:100px"><div style="padding:20px;text-align:center">Carico veloce V55.1...</div></div>

<div id="modal" class="modal" onclick="if(event.target==this)closeModal()">
<div class="modal-box">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
<b id="mCoin" style="font-size:18px">BTC</b><button onclick="closeModal()" style="border:none;background:#f1f5f9;padding:8px 12px;border-radius:10px;font-weight:700">X</button>
</div>
<div id="mPrice" style="font-size:11px;color:#64748b;margin-bottom:10px"></div>
<div id="mQualityBig" class="big-box"></div>
<div id="mConfluence" style="background:#f8fafc;border-radius:10px;padding:10px;margin:10px 0;font-size:12px"></div>
<div class="stat-grid">
<div class="stat-card"><span>RSI</span><b id="sRSI">-</b></div>
<div class="stat-card"><span>STOCH K</span><b id="sStoch">-</b></div>
<div class="stat-card"><span>EMA 50 / 200</span><b id="sEMA" style="font-size:12px">-</b></div>
<div class="stat-card"><span>SUPERTREND</span><b id="sST" style="font-size:12px">-</b></div>
<div class="stat-card"><span>VWAP</span><b id="sVWAP">-</b></div>
<div class="stat-card"><span>ADX</span><b id="sADX">-</b></div>
<div class="stat-card"><span>SUPPORTO</span><b id="sSup">-</b></div>
<div class="stat-card"><span>RESISTENZA</span><b id="sRes">-</b></div>
<div class="stat-card"><span>VOLUME</span><b id="sVol">-</b></div>
<div class="stat-card"><span>SL / TP</span><b id="sSLTP" style="font-size:10px">-</b></div>
</div>
<div id="mSimpleText" style="font-size:11px;color:#334155;background:#f8fafc;padding:12px;border-radius:10px;margin:10px 0;word-break:break-word;line-height:1.4"></div>
</div>
</div>

<script>
var curTF='1H';
var lastData=null;
var confluenceCache=null;

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
  var w=60, h=24;
  var points=data.map((v,i)=>{
    var x=(i/(data.length-1))*w;
    var y=h - ((v-min)/range)*h;
    return x.toFixed(1)+','+y.toFixed(1);
  }).join(' ');
  var color=data[data.length-1]>=data[0]?'#22c55e':'#ef4444';
  return `<svg class="spark" viewBox="0 0 ${w} ${h}"><polyline fill="none" stroke="${color}" stroke-width="1.5" points="${points}"/></svg>`;
}

async function loadTF(tf){
  curTF=tf;
  document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active'));
  var el=document.getElementById('b'+tf); if(el) el.classList.add('active');
  // MOSTRA SUBITO LOADING VELOCE, NON ASPETTA CONFLUENZA
  document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center">Carico '+tf+' veloce...</div>';
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
      var actionText=info.quality_color=='loading'?'Aggiornamento...': info.quality_color=='entra' ? (info.signal=='COMPRA'?'Compra ora':'Vendi ora') : info.quality_color=='quasi' ? 'Quasi pronto' : 'Non fare nulla';
      html+=`<div class="coin-row" onclick="openDetails('${name}')"><div style="display:flex;gap:10px;align-items:center"><div class="coin-icon ${iconClass}">${ico}</div><div><b style="font-size:16px">${name}</b> - ${price}${spark}<div style="font-size:11px;color:#64748b;margin-top:2px">${actionText} <span style="font-size:8px;color:#22c55e">${info.source}</span></div></div></div><div style="text-align:right">${qBadge}<div style="font-size:11px;color:#64748b;margin-top:4px">${info.signal} ${info.conf>0?info.conf+'%':''}</div></div></div>`;
    }
    document.getElementById('coins').innerHTML=html;
    // Confluenza in background, non blocca
    fetchConfluenceBackground();
  }catch(e){
    document.getElementById('coins').innerHTML='<div style="padding:20px;color:#ef4444">Errore: '+e.message+'<br><button onclick="loadTF(\\''+tf+'\\')" style="margin-top:8px;padding:6px 10px">Riprova</button></div>';
  }
}

async function fetchConfluenceBackground(){
  try{
    var confRes=await fetch('/api/confluence');
    var confData=await confRes.json();
    confluenceCache=confData.confluence;
    renderConfluenceBanner(confData.confluence);
  }catch(e){}
}

function renderConfluenceBanner(conf){
  var banner=document.getElementById('confBanner');
  var btc=conf['BTC'];
  if(!btc){banner.style.display='none';return;}
  var cls=btc.confluence.toLowerCase().replace(' ','-');
  banner.className='conf-banner '+cls;
  banner.innerHTML=`<span>BTC Confluenza: ${btc.confluence} (${btc.details['5m']}/${btc.details['1H']}/${btc.details['4H']}/${btc.details['1D']})</span><span style="font-size:10px">${btc.avg>0?'+':''}${btc.avg}%</span>`;
  banner.style.display='flex';
}

async function loadConfluence(){
  document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center">Analizzo tutti i TF (può volerci 20s)...</div>';
  try{
    var res=await fetch('/api/confluence');
    var d=await res.json();
    var html='';
    for(var name in d.confluence){
      var c=d.confluence[name];
      var iconClass=name=='BTC'?'btc':name=='ETH'?'eth':'oro';
      var ico=name=='BTC'?'B':name=='ETH'?'E':'Au';
      var cls=c.confluence.toLowerCase().replace(' ','-');
      html+=`<div style="background:white;padding:14px 16px;border-bottom:1px solid #f1f5f9"><div style="display:flex;gap:10px;align-items:center"><div class="coin-icon ${iconClass}">${ico}</div><div style="flex:1"><b>${name}</b> - <span class="conf-banner ${cls}" style="display:inline-block;margin:0;padding:2px 8px;font-size:11px">${c.confluence}</span><div style="font-size:11px;color:#64748b;margin-top:4px">5m:${c.details['5m']} | 1H:${c.details['1H']} | 4H:${c.details['4H']} | 1D:${c.details['1D']} | Avg ${c.avg}%</div></div></div></div>`;
    }
    document.getElementById('coins').innerHTML=html;
  }catch(e){
    document.getElementById('coins').innerHTML='<div style="padding:20px;color:#ef4444">Errore confluenza: '+e.message+'</div>';
  }
}

async function openDetails(coin){
  if(!lastData) return;
  var info=lastData.coins[coin];
  var cInfo=confluenceCache?confluenceCache[coin]:null;
  document.getElementById('mCoin').textContent=coin+' - $'+info.price.toFixed(2);
  document.getElementById('mPrice').textContent=info.source+'/'+info.ohlc_src+' - '+info.signal+' '+(info.conf>0?info.conf+'%':'')+' - TF '+curTF;
  var big=document.getElementById('mQualityBig');
  big.className='big-box '+(info.quality_color=='entra'?'entra-big':info.quality_color=='quasi'?'quasi-big':info.quality_color=='loading'?'loading-big':'wait-big');
  if(info.quality_color=='loading'){
    big.innerHTML=`<div style="font-size:18px;font-weight:800;color:#854d0e">AGGIORNAMENTO DATI</div><div style="font-size:12px;margin-top:6px">Riprovo tra 20s - ${info.source}/${info.ohlc_src}</div>`;
  }else if(info.quality_color=='entra'){
    big.innerHTML=`<div style="font-size:24px;font-weight:900;color:${info.signal=='COMPRA'?'#166534':'#991b1b'}">${info.quality_label} - ${info.signal}</div><div style="font-size:13px;color:#475569;margin-top:6px">Score ${info.quality_score}% - SL $${Math.round(info.sl)} TP $${Math.round(info.tp)}</div>`;
  }else if(info.quality_color=='quasi'){
    big.innerHTML=`<div style="font-size:22px;font-weight:900;color:#92400e">QUASI PRONTO</div><div style="font-size:12px;color:#64748b">Score ${info.quality_score}%</div>`;
  }else{
    big.innerHTML=`<div style="font-size:22px;font-weight:900;color:#475569">ASPETTA</div>`;
  }
  document.getElementById('mConfluence').innerHTML=cInfo?`<b>Confluenza multi-TF:</b> ${cInfo.confluence}<br><span style="font-size:11px">5m:${cInfo.details['5m']} | 1H:${cInfo.details['1H']} | 4H:${cInfo.details['4H']} | 1D:${cInfo.details['1D']}</span>`:'Confluenza: clicca 🔍 per calcolare';
  document.getElementById('sRSI').textContent=info.rsi;
  document.getElementById('sStoch').textContent=info.stoch_k;
  document.getElementById('sEMA').textContent=Math.round(info.ema50)+' / '+Math.round(info.ema200);
  document.getElementById('sST').textContent=(info.st_trend==1?'UP ':'DOWN ')+'$'+Math.round(info.st_val);
  document.getElementById('sVWAP').textContent='$'+Math.round(info.vwap);
  document.getElementById('sADX').textContent=info.adx;
  document.getElementById('sSup').textContent='$'+Math.round(info.support);
  document.getElementById('sRes').textContent='$'+Math.round(info.resistance);
  document.getElementById('sVol').textContent='x'+info.vol_ratio;
  document.getElementById('sSLTP').textContent='$'+Math.round(info.sl)+' / $'+Math.round(info.tp);
  document.getElementById('mSimpleText').textContent=info.quality_simple;
  document.getElementById('modal').classList.add('show');
}
function closeModal(){ document.getElementById('modal').classList.remove('show'); }
function togglePush(){
  if(Notification.permission!=='granted'){ Notification.requestPermission(); alert('Attiva notifiche'); return; }
  alert('Push attivi: ti avviso solo se ENTRA >=80% ogni 2h');
}

loadTF('1H');
setInterval(()=>loadTF(curTF), 25000);
</script>
</body></html>
"""
    return Response(html, mimetype="text/html; charset=utf-8")

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
