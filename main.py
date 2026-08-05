import os
import time
import threading
import requests
from flask import Flask, Response
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID")
SYMBOLS = ["BTCEUR", "ETHEUR", "SOLEUR", "BNBEUR"]

app = Flask(__name__)
LOGS = []
bot_thread = None

def log_msg(msg):
    t = datetime.now().strftime("%H:%M:%S")
    entry = f"[{t}] {msg}"
    print(entry, flush=True)
    LOGS.append(entry)
    if len(LOGS) > 300:
        LOGS.pop(0)

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        log_msg(f"TG error: {e}")

def get_klines(symbol, interval_str, limit=21):
    urls = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval_str}&limit={limit}",
        f"https://api1.binance.com/api/v3/klines?symbol={symbol}&interval={interval_str}&limit={limit}"
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=10).json()
            if isinstance(r, list) and len(r) >= 5:
                return r
        except:
            continue
    return []

def get_volume_info(symbol, interval=1, lookback=20):
    try:
        klines = get_klines(symbol, f"{interval}m", lookback+1)
        if not klines:
            return 0, 0, "VOL NORMALE"
        volumes = [float(c[5]) for c in klines]
        vol_now = volumes[-1]
        vol_avg = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else vol_now
        if vol_avg == 0:
            return vol_now, vol_avg, "VOL NORMALE"
        if vol_now < vol_avg * 0.7:
            label = "VOL BASSO"
        elif vol_now > vol_avg * 1.9:
            label = "VOL ALTO"
        else:
            label = "VOL NORMALE"
        return vol_now, vol_avg, label
    except:
        return 0, 0, "VOL NORMALE"

def get_price_info(symbol):
    try:
        url = f"https://data-api.binance.vision/api/v3/ticker/24hr?symbol={symbol}"
        d = requests.get(url, timeout=10).json()
        return float(d['lastPrice']), float(d['priceChangePercent'])
    except:
        return 0, 0

def loop_bot():
    log_msg("Bot KRAKEN v5.6 EUR PRO partito")
    send_telegram("Bot KRAKEN v5.6 EUR PRO partito - grafico + timeframe + affidabilita")
    while True:
        try:
            for s in SYMBOLS:
                try:
                    price, change = get_price_info(s)
                    v1, a1, l1 = get_volume_info(s, 1, 20)
                    v5, a5, l5 = get_volume_info(s, 5, 20)
                    log_line = f"AGG 1m - {s}: {price:.2f}EUR ({change:+.2f}%) | {l1} ({v1:.1f} vs {a1:.1f})"
                    log_msg(log_line)
                    now = datetime.now().strftime("%H:%M:%S")
                    msg = "AGG 1m - " + now + "\n" + s + f": {price:.2f}EUR ({change:+.2f}%)\n1m: {l1} ({v1:.1f} vs {a1:.1f})\n5m: {l5} ({v5:.1f} vs {a5:.1f})"
                    send_telegram(msg)
                except Exception as e:
                    log_msg(f"Errore {s}: {e}")
                    continue
            time.sleep(60)
        except Exception as e:
            log_msg(f"Loop error: {e}")
            time.sleep(10)

@app.route("/")
def home():
    global bot_thread
    if bot_thread is None or not bot_thread.is_alive():
        bot_thread = threading.Thread(target=loop_bot, daemon=True)
        bot_thread.start()
        return "Bot riavviato EUR PRO - <a href='/app'>Vai alla APP PRO</a>", 200
    return f"Bot vivo EUR PRO - {len(LOGS)} log - <a href='/app'>Vai alla APP PRO</a>", 200

@app.route("/log")
def show_log():
    return "<br>".join(LOGS[-200:])

@app.route("/app")
def serve_app():
    html = '''<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<meta name="theme-color" content="#0a0e1a">
<title>Crypto Vendi PRO - EURO</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#070b18;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,system-ui,Segoe UI,Roboto;min-height:100vh;padding:12px;padding-bottom:80px}
.header{position:sticky;top:0;z-index:10;background:#070b18ee;backdrop-filter:blur(12px);padding:12px 0;margin:-12px -12px 16px -12px;padding-left:12px;padding-right:12px;border-bottom:1px solid #1e2a4a}
.h-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.logo{width:44px;height:44px;background:linear-gradient(135deg,#7c3aed,#3b82f6);border-radius:14px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:20px;box-shadow:0 4px 20px #7c3aed44}
.btn{border:none;padding:8px 14px;border-radius:20px;font-weight:700;cursor:pointer;font-size:13px;transition:.2s}
.btn-install{background:#fff;color:#000}
.btn-sound{background:#1e293b;color:#fff;border:1px solid #334155}
.btn-sound.on{background:#10b981;color:#000;border-color:#10b981}
.tf-bar{display:flex;gap:6px;overflow-x:auto;margin-top:12px;padding-bottom:2px}
.tf{padding:6px 14px;border-radius:20px;background:#131a2e;border:1px solid #1e2a4a;color:#94a3b8;font-weight:700;font-size:13px;cursor:pointer;white-space:nowrap}
.tf.active{background:#fff;color:#000;border-color:#fff}
.card{background:#131a2e;border:1px solid #1e2a4a;border-radius:18px;padding:14px;margin-bottom:12px}
.price{font-size:26px;font-weight:900;letter-spacing:-.5px}
.pos{color:#10b981}.neg{color:#ef4444}
.badge{padding:6px 12px;border-radius:20px;font-weight:900;font-size:12px;letter-spacing:.5px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:10px 0}
.mini{font-size:10px;opacity:.5;text-transform:uppercase;letter-spacing:1px}.val{font-size:13px;font-weight:800;color:#fff;display:block;margin-top:2px}
.conf-bar{height:6px;background:#0f172a;border-radius:10px;overflow:hidden;margin-top:6px}
.conf-fill{height:100%;border-radius:10px;transition:width .6s}
.chart-wrap{margin-top:12px;background:#0a1020;border-radius:14px;padding:8px;display:none}
.chart-wrap.open{display:block}
.btn-chart{background:#0f172a;border:1px solid #1e2a4a;color:#94a3b8;width:100%;margin-top:8px}
.toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#fff;color:#000;padding:12px 20px;border-radius:30px;font-weight:800;box-shadow:0 10px 30px #0008;z-index:99;display:none;animation:pop .3s}
@keyframes pop{0%{transform:translateX(-50%) scale(.8)}100%{transform:translateX(-50%) scale(1)}}
</style>
</head>
<body>
<div class="header">
 <div class="h-row">
  <div class="logo">V</div>
  <div style="flex:1"><div style="font-weight:900;font-size:16px">Crypto Vendi PRO</div><div style="font-size:11px;opacity:.6">EURO • RSI • EMA • Volume • Affidabilità</div></div>
  <button class="btn btn-sound" id="soundBtn">🔇 Suono OFF</button>
  <button class="btn btn-install" id="installBtn">⬇️ Installa</button>
 </div>
 <div class="tf-bar" id="tfBar">
  <div class="tf" data-tf="1m">1m</div>
  <div class="tf" data-tf="5m">5m</div>
  <div class="tf" data-tf="15m">15m</div>
  <div class="tf active" data-tf="1h">1H</div>
  <div class="tf" data-tf="4h">4H</div>
  <div class="tf" data-tf="1d">1D</div>
 </div>
</div>
<div class="card" style="display:flex;align-items:center;gap:12px;background:linear-gradient(135deg,#131a2e,#1a2442);border-color:#2a3a62">
 <div style="width:46px;height:46px;background:#1e293b;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:20px">📊</div>
 <div style="flex:1"><div style="font-size:11px;letter-spacing:2px;opacity:.6">MERCATO GLOBALE</div><div id="globale" style="font-size:19px;font-weight:900;color:#fbbf24">CARICAMENTO...</div><div id="globaleSub" style="font-size:11px;opacity:.6;margin-top:2px"></div></div>
 <div style="text-align:right"><div style="font-size:10px;opacity:.5">TIMEFRAME</div><div id="tfLabel" style="font-weight:900">1H</div></div>
</div>
<div id="coins"></div>
<div style="text-align:center;margin-top:10px;font-size:11px;opacity:.4" id="upd">Aggiornato: --:--</div>
<div class="toast" id="toast"></div>
<script>
let deferredPrompt=null, soundOn=false, currentTF='1h', prevSignals={}, charts={};
const SYMBOLS=['BTCEUR','ETHEUR','SOLEUR','BNBEUR'];
const audioCtx = new (window.AudioContext||window.webkitAudioContext)();
function playSound(type){
 if(!soundOn) return;
 try{
  const o=audioCtx.createOscillator(); const g=audioCtx.createGain();
  o.connect(g); g.connect(audioCtx.destination);
  if(type==='COMPRA'){ o.frequency.value=880; g.gain.value=0.15; o.start(); g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.6); o.stop(audioCtx.currentTime+0.6);}
  else if(type==='VENDI'){ o.frequency.value=220; g.gain.value=0.2; o.type='sawtooth'; o.start(); g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.8); o.stop(audioCtx.currentTime+0.8);}
 }catch(e){}
}
function showToast(msg){
 const t=document.getElementById('toast'); t.textContent=msg; t.style.display='block';
 setTimeout(()=>t.style.display='none',4000);
}
document.getElementById('soundBtn').onclick=()=>{
 soundOn=!soundOn;
 const b=document.getElementById('soundBtn');
 if(soundOn){ b.textContent='🔊 Suono ON'; b.classList.add('on'); audioCtx.resume(); showToast('🔊 Alert sonoro ATTIVO'); playSound('COMPRA');}
 else{ b.textContent='🔇 Suono OFF'; b.classList.remove('on'); showToast('🔇 Suono disattivato');}
};
window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();deferredPrompt=e;});
document.getElementById('installBtn').onclick=async()=>{
 if(deferredPrompt){deferredPrompt.prompt(); await deferredPrompt.userChoice; deferredPrompt=null;}
 else{ showToast('Menu ⋮ -> Installa e crea scorciatoia');}
};
document.querySelectorAll('.tf').forEach(el=>{
 el.onclick=()=>{
  document.querySelectorAll('.tf').forEach(x=>x.classList.remove('active'));
  el.classList.add('active');
  currentTF=el.dataset.tf;
  document.getElementById('tfLabel').textContent=currentTF.toUpperCase();
  refresh(true);
 };
});
function calcRSI(prices,p=14){
 if(prices.length<p+1) return 50;
 let gains=0,losses=0;
 for(let i=1;i<=p;i++){let d=prices[i]-prices[i-1]; if(d>=0) gains+=d; else losses-=d;}
 let avgG=gains/p, avgL=losses/p;
 if(avgL===0) return 85;
 for(let i=p+1;i<prices.length;i++){let d=prices[i]-prices[i-1]; let g=d>0?d:0; let l=d<0?-d:0; avgG=(avgG*(p-1)+g)/p; avgL=(avgL*(p-1)+l)/p;}
 let rs=avgG/avgL; return 100-100/(1+rs);
}
function calcEMA(prices,period){let k=2/(period+1); let ema=prices[0]; for(let i=1;i<prices.length;i++) ema=prices[i]*k+ema*(1-k); return ema;}
async function fetchKlines(sym,interval,limit=100){
 const urls=[`https://api.binance.com/api/v3/klines?symbol=${sym}&interval=${interval}&limit=${limit}`,`https://data-api.binance.vision/api/v3/klines?symbol=${sym}&interval=${interval}&limit=${limit}`];
 for(let u of urls){ try{let r=await fetch(u); if(!r.ok) continue; let j=await r.json(); if(j.length) return j;}catch(e){} }
 return [];
}
function calcConfidence(o){
 let conf=50; let reasons=[];
 let div = Math.abs(o.ema20-o.ema50)/o.ema50*100;
 if(o.stato==='COMPRA'){
  if(o.rsi<25){conf+=28; reasons.push('RSI ipervenduto '+o.rsi.toFixed(0));}
  else if(o.rsi<35){conf+=18; reasons.push('RSI basso');}
  else if(o.rsi<45){conf+=8;}
  else if(o.rsi>60){conf-=12; reasons.push('RSI alto per COMPRA');}
  if(o.ema20>o.ema50){conf+=14; reasons.push('Trend rialzista'); if(div>1.5){conf+=10; reasons.push('Div EMA +'+div.toFixed(1)+'%');}}
  else{conf-=14; reasons.push('Contro-trend');}
  if(o.volLabel==='VOL ALTO'){conf+=14; reasons.push('Volume alto');}
  else if(o.volLabel==='VOL BASSO'){conf-=16; reasons.push('Volume basso');}
 } else if(o.stato==='VENDI'){
  if(o.rsi>75){conf+=28; reasons.push('RSI ipercomprato '+o.rsi.toFixed(0));}
  else if(o.rsi>65){conf+=18; reasons.push('RSI alto');}
  else if(o.rsi>55){conf+=8;}
  else if(o.rsi<40){conf-=12; reasons.push('RSI basso per VENDI');}
  if(o.ema20<o.ema50){conf+=14; reasons.push('Trend ribassista'); if(div>1.5){conf+=10; reasons.push('Div EMA -'+div.toFixed(1)+'%');}}
  else{conf-=14; reasons.push('Contro-trend');}
  if(o.volLabel==='VOL ALTO'){conf+=14; reasons.push('Volume alto');}
  else if(o.volLabel==='VOL BASSO'){conf-=16; reasons.push('Volume debole');}
 } else {
  conf=45 + (Math.abs(o.rsi-50)/2);
  if(o.volLabel==='VOL BASSO') conf-=10;
  reasons.push('Laterale');
 }
 conf=Math.max(12,Math.min(94,Math.round(conf)));
 return {conf,reasons};
}
async function loadCoin(sym){
 try{
  let kl=await fetchKlines(sym,currentTF,100);
  if(!kl.length) return null;
  let closes=kl.map(c=>parseFloat(c[4]));
  let volumes=kl.map(c=>parseFloat(c[5]));
  let price=closes[closes.length-1];
  let open=closes[Math.max(0,closes.length-24)];
  let change=((price-open)/open*100);
  let rsi=calcRSI(closes,14);
  let ema20=calcEMA(closes,20);
  let ema50=calcEMA(closes,50);
  let volNow=volumes[volumes.length-1];
  let volAvg=volumes.slice(-21,-1).reduce((a,b)=>a+b,0)/20;
  let volLabel=volNow < volAvg*0.7 ? 'VOL BASSO' : volNow > volAvg*1.9 ? 'VOL ALTO' : 'VOL NORMALE';
  let trend=ema20>ema50?'Rialzista':'Ribassista';
  let stato='FERMO'; let col='#fbbf24'; let textCol='#000';
  if(rsi>70){stato='VENDI'; col='#ef4444'; textCol='#fff';}
  else if(rsi<30){stato='COMPRA'; col='#10b981'; textCol='#000';}
  else if(ema20>ema50 && rsi>55){stato='COMPRA'; col='#10b981'; textCol='#000';}
  else if(ema20<ema50 && rsi<45){stato='VENDI'; col='#ef4444'; textCol='#fff';}
  let cr=calcConfidence({stato,rsi,ema20,ema50,volLabel,price});
  return {sym,closes,kl,price,change,rsi,ema20,ema50,trend,stato,col,textCol,volLabel,conf:cr.conf,reasons:cr.reasons,volNow,volAvg};
 }catch(e){ return null; }
}
function renderChart(sym, closes, col){
 const id='chart-'+sym;
 const canvas=document.getElementById(id);
 if(!canvas) return;
 if(charts[sym]){ charts[sym].destroy(); }
 charts[sym]=new Chart(canvas,{
  type:'line',
  data:{ labels:closes.map((_,i)=>i), datasets:[{ data:closes, borderColor:col, backgroundColor:col+'33', borderWidth:2, fill:true, tension:0.4, pointRadius:0 }]},
  options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{display:false}, y:{display:true, grid:{color:'#1e2a4a'}, ticks:{color:'#64748b', font:{size:10}}}} }
 });
}
async function refresh(forceChart=false){
 let html=''; let segnali=[];
 let results=await Promise.all(SYMBOLS.map(s=>loadCoin(s)));
 results=results.filter(Boolean);
 window._lastData=results;
 for(let d of results){
  segnali.push(d.stato);
  if(prevSignals[d.sym] && prevSignals[d.sym]!==d.stato && (d.stato==='COMPRA' || d.stato==='VENDI')){
   playSound(d.stato);
   showToast(`🔔 ${d.sym}: ${prevSignals[d.sym]} → ${d.stato} (${d.conf}%)`);
  }
  prevSignals[d.sym]=d.stato;
  let name=d.sym.replace('EUR','');
  let confColor = d.conf>=75 ? '#10b981' : d.conf>=55 ? '#fbbf24' : '#ef4444';
  let reasonText = d.reasons.slice(0,2).join(' • ');
  html+=`<div class="card">
   <div style="display:flex;justify-content:space-between;align-items:center">
    <div style="display:flex;gap:10px;align-items:center"><div style="width:42px;height:42px;background:#0f172a;border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:900;border:1px solid #1e2a4a">${name[0]}</div><div><div style="font-weight:900">${d.sym}</div><div style="font-size:11px;opacity:.6">${name} • ${d.volLabel}</div></div></div>
    <div style="text-align:right"><div class="badge" style="background:${d.col};color:${d.textCol}">${d.stato}</div><div style="font-size:11px;margin-top:4px;font-weight:800;color:${confColor}">${d.conf}% affidabile</div></div>
   </div>
   <div class="price" style="margin:10px 0">€${d.price.toLocaleString('it-IT',{minimumFractionDigits:2,maximumFractionDigits:2})} <span style="font-size:13px" class="${d.change>=0?'pos':'neg'}">${d.change>=0?'+':''}${d.change.toFixed(2)}%</span></div>
   <div style="margin:8px 0"><div style="display:flex;justify-content:space-between;font-size:11px"><span style="opacity:.6">Affidabilità</span><span style="font-weight:800;color:${confColor}">${reasonText}</span></div><div class="conf-bar"><div class="conf-fill" style="width:${d.conf}%;background:${confColor}"></div></div></div>
   <div class="grid3">
    <div class="card" style="margin:0;background:#0a1020"><div class="mini">RSI 14</div><span class="val" style="color:${d.rsi>70?'#ef4444':d.rsi<30?'#10b981':'#fff'}">${d.rsi.toFixed(1)}</span></div>
    <div class="card" style="margin:0;background:#0a1020"><div class="mini">Trend EMA</div><span class="val" style="color:${d.trend==='Rialzista'?'#10b981':'#ef4444'}">${d.trend}</span><div style="font-size:10px;opacity:.5">20: €${d.ema20.toFixed(0)} • 50: €${d.ema50.toFixed(0)}</div></div>
    <div class="card" style="margin:0;background:#0a1020"><div class="mini">Volume ${currentTF}</div><span class="val">${d.volLabel.replace('VOL ','')}</span><div style="font-size:10px;opacity:.5">${d.volNow.toFixed(1)} vs ${d.volAvg.toFixed(1)}</div></div>
   </div>
   <button class="btn btn-chart" onclick="toggleChart('${d.sym}')">📈 Grafico ${currentTF.toUpperCase()}</button>
   <div class="chart-wrap" id="wrap-${d.sym}"><div style="height:180px"><canvas id="chart-${d.sym}"></canvas></div></div>
  </div>`;
 }
 document.getElementById('coins').innerHTML=html;
 results.forEach(d=>{
  const wrap=document.getElementById('wrap-'+d.sym);
  if(wrap && wrap.classList.contains('open')){ setTimeout(()=>renderChart(d.sym,d.closes,d.col),50); }
 });
 let comp=segnali.filter(s=>s==='COMPRA').length, vend=segnali.filter(s=>s==='VENDI').length;
 let glob=document.getElementById('globale'), sub=document.getElementById('globaleSub');
 if(comp>=3){glob.textContent='MERCATO COMPRA FORTE'; glob.style.color='#10b981'; sub.textContent=comp+' su '+SYMBOLS.length+' in COMPRA • alta affidabilità';}
 else if(vend>=3){glob.textContent='MERCATO VENDI FORTE'; glob.style.color='#ef4444'; sub.textContent=vend+' su '+SYMBOLS.length+' in VENDI';}
 else if(comp>=2){glob.textContent='MERCATO COMPRA'; glob.style.color='#10b981'; sub.textContent='Rialzisti prevalenti';}
 else if(vend>=2){glob.textContent='MERCATO VENDI'; glob.style.color='#ef4444'; sub.textContent='Ribassisti prevalenti';}
 else{glob.textContent='MERCATO FERMO / LATERALE'; glob.style.color='#fbbf24'; sub.textContent='Nessuna direzione chiara';}
 document.getElementById('upd').textContent='Aggiornato: '+new Date().toLocaleTimeString('it-IT')+' • TF: '+currentTF+' • Auto 60s';
}
function toggleChart(sym){
 const wrap=document.getElementById('wrap-'+sym);
 const isOpen=wrap.classList.contains('open');
 document.querySelectorAll('.chart-wrap').forEach(w=>w.classList.remove('open'));
 if(!isOpen){ wrap.classList.add('open'); const d=window._lastData?.find(x=>x.sym===sym); if(d) setTimeout(()=>renderChart(sym,d.closes,d.col),80); else refresh(); }
}
refresh(); setInterval(()=>refresh(false),60000);
</script>
</body>
</html>
'''
    return Response(html, mimetype="text/html")

bot_thread = threading.Thread(target=loop_bot, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
