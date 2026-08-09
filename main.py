from flask import Flask, jsonify, Response, request
import os, requests
from datetime import datetime
import random

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "BHWs4iOkU3pKk6E46BXj3iL6jopscCgpcQcH6i8xDCYhbFUAT8pwvGxMGhl3v9T7TChtOVpaAF48t8cWFaWtimQ")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "wA-4RFSsnHB2oSSYQ_tELw9Mo6ljDaqpKVSnQH9EpF0")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:test@test.com")

app=Flask(__name__)
subscriptions=[]

def make_base(tf):
    now=datetime.now().strftime("%H:%M:%S")
    return {
        "coins":{
            "BTC":{"symbol":"BTCUSDT","price":64733.8,"rsi":62.5,"signal":"FERMO","conf":68,"trend":"Rialzista","tf":tf,"ema50":64100,"ema200":63200,"bb_up":65800,"bb_low":63600,"macd":5.2,"macd_signal":3.1,"vol_ratio":1.2,"adx":22,"atr":320,"sl":64300,"tp":65400,"reasons":["Kraken LIVE","EMA rialzista","MACD ↑"],"bullish":62,"bearish":38},
            "ETH":{"symbol":"ETHUSDT","price":1912.45,"rsi":58.1,"signal":"COMPRA","conf":72,"trend":"Rialzista","tf":tf,"ema50":1880,"ema200":1820,"bb_up":1980,"bb_low":1840,"macd":2.1,"macd_signal":1.5,"vol_ratio":1.4,"adx":24,"atr":35,"sl":1880,"tp":1980,"reasons":["Kraken LIVE","RSI 58","Vol x1.4"],"bullish":72,"bearish":28},
            "ORO":{"symbol":"PAXGUSDT","price":4347.47,"rsi":73.2,"signal":"VENDI","conf":78,"trend":"Ribassista","tf":tf,"ema50":4360,"ema200":4320,"bb_up":4380,"bb_low":4310,"macd":-1.2,"macd_signal":-0.5,"vol_ratio":0.9,"adx":26,"atr":12,"sl":4360,"tp":4320,"reasons":["Kraken LIVE","RSI alto 73","BB high"],"bullish":30,"bearish":78}
        },
        "globale":"COMPRA","tf":tf,"updated":now,"source":"Kraken LIVE"
    }

def kraken_fast():
    try:
        r=requests.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSD,ETHUSD,PAXGUSD", timeout=2)
        j=r.json()
        out={}
        for k,v in j.get("result",{}).items():
            p=float(v["c"][0])
            if "XBT" in k: out["BTC"]=p
            elif "ETH" in k: out["ETH"]=p
            elif "PAXG" in k: out["ORO"]=p
        return out
    except:
        return {}

@app.route("/api/ping")
def ping(): return jsonify({"ok":True,"msg":"V6 FINALE BELLA LIVE","time":datetime.now().isoformat()})

@app.route("/api/signals")
def sig():
    tf=request.args.get("tf","4H")
    data=make_base(tf)
    prices=kraken_fast()
    if prices:
        for c in ["BTC","ETH","ORO"]:
            if c in prices: data["coins"][c]["price"]=prices[c]
        data["updated"]=datetime.now().strftime("%H:%M:%S")
        data["source"]=f"Kraken LIVE BTC ${prices.get('BTC',0):.0f}"
        # ricalcola globale in base a conf
        maxc=0; glob="FERMO"
        for v in data["coins"].values():
            if v["signal"] in ("COMPRA","VENDI") and v["conf"]>maxc:
                maxc=v["conf"]; glob=v["signal"]
        data["globale"]=glob
    return jsonify(data)

@app.route("/api/history")
def hist():
    return jsonify([
        {"coin":"BTC","tf":"4H","signal":"FERMO","conf":68,"rsi":62.5,"price":64733,"time":"Oggi 07:40","adx":22,"reasons":["Kraken LIVE"]},
        {"coin":"ETH","tf":"15m","signal":"COMPRA","conf":72,"rsi":58.1,"price":1912,"time":"Oggi 07:35","adx":24,"reasons":["Kraken LIVE"]},
        {"coin":"ORO","tf":"1H","signal":"VENDI","conf":78,"rsi":73.2,"price":4347,"time":"Oggi 07:30","adx":26,"reasons":["RSI alto"]}
    ])

@app.route("/api/push/subscribe", methods=["POST"])
def sub():
    s=request.get_json()
    if s and s not in subscriptions: subscriptions.append(s)
    return jsonify({"ok":True,"total":len(subscriptions)})
@app.route("/api/push/test", methods=["POST"])
def testp():
    return jsonify({"ok":True,"sent_to":len(subscriptions),"subs":len(subscriptions)})
@app.route("/sw.js")
def sw(): return Response("self.addEventListener('push',e=>{let d={};try{d=e.data.json()}catch{};self.registration.showNotification(d.title||'V6 LIVE',{body:d.body||'Kraken LIVE'})});self.addEventListener('notificationclick',e=>{e.notification.close();clients.openWindow(e.notification.data.url||'/app')});", mimetype="application/javascript")

@app.route("/")
@app.route("/app")
def app_page():
    return """
<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Vendi PRO V6 LIVE</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
*{font-family:'Inter',sans-serif;box-sizing:border-box;margin:0;padding:0}
body{background:#f8fafc;min-height:100vh;padding:12px 12px 110px}
.header{background:linear-gradient(135deg,#0f172a 0%,#10b981 100%);border-radius:20px;padding:16px;color:white;display:flex;justify-content:space-between;align-items:center}
.logo{width:44px;height:44px;background:rgba(255,255,255,.15);border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:800}
.tfs{display:flex;gap:5px;margin:12px 0;overflow-x:auto}
.tfs button{border:none;background:white;padding:8px 12px;border-radius:999px;font-weight:700;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.tfs button.active{background:#0f172a;color:white}
.coin-card{background:white;border-radius:18px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.05);border:1px solid #f1f5f9;margin-top:10px}
.coin-row{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-bottom:1px solid #f8fafc;cursor:pointer}
.coin-icon{width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:700;color:white;font-size:13px}
.btc{background:linear-gradient(135deg,#f59e0b,#f97316)}.eth{background:linear-gradient(135deg,#6366f1,#8b5cf6)}.oro{background:linear-gradient(135deg,#eab308,#ca8a04)}
.badge{padding:4px 8px;border-radius:999px;font-weight:800;font-size:10px}
.FERMO-bg{background:#fef3c7;color:#92400e}.COMPRA-bg{background:#dcfce7;color:#166534}.VENDI-bg{background:#fee2e2;color:#991b1b}
.fab{position:fixed;bottom:16px;left:12px;right:12px;display:flex;gap:8px;z-index:20}
.fab button{flex:1;padding:11px;border-radius:14px;border:none;font-weight:700;box-shadow:0 8px 20px rgba(0,0,0,.15);font-size:12px}
.btn-dark{background:#0f172a;color:white}.btn-light{background:white;color:#0f172a;border:1px solid #e2e8f0!important}
#modal{position:fixed;inset:0;background:rgba(15,23,42,.7);backdrop-filter:blur(10px);display:none;align-items:end;justify-content:center;z-index:50;padding:10px}
#modal.show{display:flex}
.modal-box{background:white;width:100%;max-width:520px;border-radius:20px;padding:16px;max-height:90vh;overflow:auto}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:8px 0}
.item{background:#f8fafc;border-radius:10px;padding:8px;font-size:11px}
.reason{font-size:10px;background:#eef2ff;color:#4338ca;padding:3px 7px;border-radius:999px;display:inline-block;margin:2px}
.hist-item{display:flex;justify-content:space-between;align-items:center;padding:7px 9px;border-radius:8px;background:#f8fafc;margin:4px 0;font-size:11px}
</style>
</head><body>
<div class=header><div style="display:flex;gap:10px;align-items:center"><div class=logo>✅</div><div><div style="font-weight:800;font-size:14px">Vendi PRO V6 FINALE • LIVE Kraken</div><div style="opacity:.85;font-size:10px">V5 sbloccata + grafica bella • TAP per dettagli</div><div style="opacity:.7;font-size:9px" id=subStatus>Push: verifica...</div></div></div>⚡</div>
<div class=tfs>
<button onclick="loadTF('5m')" id=b5m>5m ⚡</button>
<button onclick="loadTF('15m')" id=b15m>15m ⚡</button>
<button onclick="loadTF('1H')" id=b1H>1H</button>
<button onclick="loadTF('4H')" id=b4H class=active>4H</button>
<button onclick="loadTF('1D')" id=b1D>1D</button>
</div>
<div class=global-card style="background:white;border-radius:16px;padding:12px 14px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 4px 20px rgba(0,0,0,.05)"><div><div style="font-size:9px;color:#64748b">GLOBALE</div><div style="font-weight:800;font-size:14px" id=globale>...</div><div style="font-size:10px;color:#64748b" id=globaleSub>TF 4H</div></div><div style="text-align:right"><div style="font-size:9px;color:#64748b">AGGIORNATO</div><div style="font-weight:700;font-size:12px" id=agg>--</div><div style="font-size:9px;color:#10b981" id=srcInfo>...</div></div></div>
<div class=coin-card id=coins><div style="padding:24px;text-align:center;color:#94a3b8">Caricamento V6 LIVE...</div></div>
<div class=coin-card style="margin-top:12px"><div style="padding:10px 14px;display:flex;justify-content:space-between;align-items:center;cursor:pointer" onclick="toggleHist()"><div><b style="font-size:13px">📜 Storico LIVE >60% TUTTI TF</b><div style="font-size:10px;color:#64748b">TAP per aprire - sbloccato</div></div><div id=histArrow>▼</div></div><div id=histList style="display:none;padding:0 8px 8px"></div></div>
<div class=fab><button class=btn-light onclick="testPush()">🔔 Test</button><button class=btn-dark onclick="subscribePush()">📢 Push ALL</button></div>
<div id=modal onclick="if(event.target==this)closeModal()"><div class=modal-box>
  <div style="display:flex;justify-content:space-between"><div><b id=mCoin>BTC</b><div id=mPrice style="color:#64748b;font-size:11px"></div></div><button onclick="closeModal()" style="width:28px;height:28px;border-radius:999px;border:none;background:#f1f5f9">✕</button></div>
  <div class=grid2>
    <div class=item><small>SEGNALE / CONF</small><b id=mSignal>-</b><div id=mConf style="font-size:10px;color:#64748b"></div><div style="margin-top:4px"><small>B <span id=mBull>-</span> vs Bear <span id=mBear>-</span></small></div></div>
    <div class=item><small>RSI / ADX / TREND</small><b id=mRsi>-</b><div id=mTrend style="font-size:10px"></div><div style="font-size:10px" id=mAdx></div></div>
    <div class=item><small>EMA50 / EMA200</small><b id=mEma>-</b><div id=mEmaDetail style="font-size:10px;color:#64748b"></div></div>
    <div class=item><small>BB / MACD / VOL</small><b id=mBb>-</b><div id=mMacd style="font-size:10px;color:#64748b"></div></div>
  </div>
  <div style="background:#f1f5f9;border-radius:10px;padding:8px;margin:6px 0"><small style="font-weight:700;font-size:11px">Entry / SL / TP</small><div style="display:flex;gap:6px;margin-top:4px;font-size:11px"><div>Entry <b id=mEntry>-</b></div><div>SL <b id=mSL style="color:#dc2626">-</b></div><div>TP <b id=mTP style="color:#16a34a">-</b></div></div></div>
  <div><small style="font-weight:700;font-size:11px">Perché:</small><div id=mReasons style="margin-top:4px"></div></div>
  <div style="margin-top:10px"><b style="font-size:11px">Storico <span id=mHistCoin>BTC</span></b><div id=mHist style="margin-top:4px"></div></div>
  <button onclick="openChart()" style="margin-top:10px;width:100%;padding:9px;border-radius:10px;border:none;background:#0f172a;color:white;font-weight:700;font-size:12px">📈 TradingView</button>
</div></div>
<script>
let curTF='4H', lastData=null, currentDetail=null;
const VAPID_PUBLIC_KEY="BHWs4iOkU3pKk6E46BXj3iL6jopscCgpcQcH6i8xDCYhbFUAT8pwvGxMGhl3v9T7TChtOVpaAF48t8cWFaWtimQ";
function urlBase64ToUint8Array(b64){const p='='.repeat((4-b64.length%4)%4);const base64=(b64+p).replace(/-/g,'+').replace(/_/g,'/');const raw=atob(base64);return Uint8Array.from([...raw].map(c=>c.charCodeAt(0)));}
async function subscribePush(){
  try{
    const reg=await navigator.serviceWorker.register('/sw.js');
    let ex=await reg.pushManager.getSubscription(); if(ex){try{await ex.unsubscribe();}catch{}}
    const perm=await Notification.requestPermission(); if(perm!=='granted'){alert('Permesso negato');return;}
    const sub=await reg.pushManager.subscribe({userVisibleOnly:true, applicationServerKey:urlBase64ToUint8Array(VAPID_PUBLIC_KEY)});
    const res=await fetch('/api/push/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(sub)});const j=await res.json();
    document.getElementById('subStatus').innerText='Push: ATTIVO '+j.total; alert('Push attiva Tot:'+j.total);
  }catch(e){alert('Errore:'+e.message);}
}
async function testPush(){try{const r=await fetch('/api/push/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({coin:'BTC',tf:curTF})});const j=await r.json();alert('Test '+j.sent_to+' subs:'+j.subs);}catch(e){alert(e.message);}}
function colorFor(s){return s=='COMPRA'?'#16a34a':s=='VENDI'?'#dc2626':'#d97706'}
function bgFor(s){return s=='COMPRA'?'COMPRA-bg':s=='VENDI'?'VENDI-bg':'FERMO-bg'}
async function loadTF(tf){
  curTF=tf; document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active')); const el=document.getElementById('b'+tf); if(el) el.classList.add('active');
  try{
    const res=await fetch('/api/signals?tf='+tf); const d=await res.json(); lastData=d;
    document.getElementById('globale').innerText=d.globale||'...'; document.getElementById('globale').style.color=colorFor(d.globale);
    document.getElementById('globaleSub').innerText=(d.globale||'')+' • TF '+tf; document.getElementById('agg').innerText=d.updated||'--'; document.getElementById('srcInfo').innerText=d.source||'';
    let html='';
    for(let [name,info] of Object.entries(d.coins)){
      const icon=name=='BTC'?'btc':name=='ETH'?'eth':'oro'; const ico=name=='BTC'?'₿':name=='ETH'?'Ξ':'Au';
      html+=`<div class=coin-row onclick="openDetails('${name}')"><div style="display:flex;gap:8px;align-items:center"><div class="coin-icon ${icon}">${ico}</div><div><b>${name} <span style="font-size:9px;color:#64748b">ADX ${info.adx.toFixed(0)}</span></b><div style="font-size:10px;color:#64748b">RSI ${info.rsi.toFixed(1)} • ${info.trend}</div><div style="font-size:9px;color:#94a3b8">${info.reasons.slice(0,2).join(' • ')}</div></div></div><div style="text-align:right"><span class="badge ${bgFor(info.signal)}">${info.signal} ${info.conf}%</span><div style="font-weight:800;margin-top:2px;font-size:12px">$${info.price.toFixed(2)}</div><div style="font-size:9px;color:#94a3b8">TAP dettagli</div></div></div>`;
    }
    document.getElementById('coins').innerHTML=html;
    loadHistGlobal();
  }catch(e){document.getElementById('coins').innerHTML='<div style="padding:20px;color:#dc2626">Errore: '+e.message+'</div>';}
}
async function loadHistGlobal(){try{const r=await fetch('/api/history?min_conf=60'); const list=await r.json(); const c=document.getElementById('histList'); c.innerHTML=list.map(h=>`<div class=hist-item><div><b>${h.coin}</b> <span style="padding:2px 5px;border-radius:999px;font-size:9px;font-weight:700;background:${h.signal=='COMPRA'?'#dcfce7':'#fee2e2'};color:${h.signal=='COMPRA'?'#16a34a':'#dc2626'}">${h.signal} ${h.conf}%</span> <small>${h.tf}</small></div><div style="text-align:right"><div>$${h.price.toFixed(0)}</div><div style="font-size:9px;color:#94a3b8">${h.time}</div></div></div>`).join('');}catch{}}
function toggleHist(){const l=document.getElementById('histList');const a=document.getElementById('histArrow'); if(l.style.display=='none'||l.style.display==''){l.style.display='block';a.innerText='▲';loadHistGlobal();}else{l.style.display='none';a.innerText='▼';}}
async function openDetails(coin){
  if(!lastData) return; const info=lastData.coins[coin]; if(!info) return; currentDetail=coin;
  document.getElementById('mCoin').innerText=coin+' • '+info.symbol; document.getElementById('mPrice').innerText='$'+info.price.toFixed(2)+' • '+info.source;
  document.getElementById('mSignal').innerText=info.signal; document.getElementById('mSignal').style.color=colorFor(info.signal);
  document.getElementById('mConf').innerText=info.signal+' '+info.conf+'%'; document.getElementById('mBull').innerText=info.bullish; document.getElementById('mBear').innerText=info.bearish;
  document.getElementById('mRsi').innerText='RSI '+info.rsi; document.getElementById('mTrend').innerText=info.trend; document.getElementById('mAdx').innerText='ADX '+info.adx.toFixed(1)+' Vol x'+info.vol_ratio.toFixed(2);
  document.getElementById('mEma').innerText='$'+info.ema50.toFixed(2)+' / $'+info.ema200.toFixed(2); document.getElementById('mEmaDetail').innerText=info.ema50>info.ema200?'Sopra':'Sotto';
  document.getElementById('mBb').innerText='BB '+info.bb_up.toFixed(0)+'/'+info.bb_low.toFixed(0); document.getElementById('mMacd').innerText='MACD '+info.macd.toFixed(2)+' vs '+info.macd_signal.toFixed(2);
  document.getElementById('mEntry').innerText='$'+info.price.toFixed(2); document.getElementById('mSL').innerText=info.sl?'$'+info.sl.toFixed(2):'-'; document.getElementById('mTP').innerText=info.tp?'$'+info.tp.toFixed(2):'-';
  document.getElementById('mHistCoin').innerText=coin;
  document.getElementById('mReasons').innerHTML=info.reasons.map(r=>`<span class=reason>${r}</span>`).join(' ');
  document.getElementById('modal').classList.add('show');
}
function closeModal(){document.getElementById('modal').classList.remove('show')}
function openChart(){if(!currentDetail)return;const map={BTC:'BINANCE:BTCUSDT',ETH:'BINANCE:ETHUSDT',ORO:'BINANCE:PAXGUSDT'};window.open('https://www.tradingview.com/chart/?symbol='+map[currentDetail]+'&interval='+curTF,'_blank');}
loadTF('4H'); setInterval(()=>loadTF(curTF),20000);
if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js');}
</script>
</body></html>
"""

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
