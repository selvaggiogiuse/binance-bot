import os
from flask import Flask, Response
app = Flask(__name__)

HTML = """<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#7c3aed">
<script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
<style>:root{--bg:#070b18;--card:#131a2e;--card2:#0a1020;--border:#1e2a4a;--text:#e2e8f0;--muted:#94a3b8}.light{--bg:#f1f5f9;--card:#fff;--card2:#f8fafc;--border:#e2e8f0;--text:#0f172a;--muted:#64748b}*{margin:0;padding:0;box-sizing:border-box}body{background:var(--bg);color:var(--text);font-family:system-ui;padding:12px;padding-bottom:90px} .header{position:sticky;top:0;z-index:20;background:var(--bg);padding:10px 0;margin:-12px -12px 14px;padding-left:12px;padding-right:12px;border-bottom:1px solid var(--border)}.h-row{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.logo{width:42px;height:42px;background:linear-gradient(135deg,#7c3aed,#3b82f6);border-radius:14px;display:flex;align-items:center;justify-content:center;font-weight:900;color:#fff}.btn{border:none;padding:7px 11px;border-radius:20px;font-weight:700;cursor:pointer;font-size:12px}.btn-install{background:var(--text);color:var(--bg)}.btn-icon{background:var(--card);color:var(--text);border:1px solid var(--border)}.btn-icon.on{background:#10b981;color:#000}.tf-bar{display:flex;gap:6px;overflow-x:auto;margin-top:10px}.tf{padding:6px 14px;border-radius:20px;background:var(--card);border:1px solid var(--border);color:var(--muted);font-weight:700;font-size:13px;cursor:pointer}.tf.active{background:var(--text);color:var(--bg)}.card{background:var(--card);border:1px solid var(--border);border-radius:18px;padding:14px;margin-bottom:12px}.price{font-size:26px;font-weight:900}.badge{padding:5px 10px;border-radius:20px;font-weight:900;font-size:11px}.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:10px 0}.mini{font-size:10px;opacity:.6;text-transform:uppercase;color:var(--muted)}.val{font-size:13px;font-weight:800;display:block;margin-top:2px}.conf-bar{height:6px;background:var(--card2);border-radius:10px;overflow:hidden;margin-top:6px}.conf-fill{height:100%;border-radius:10px}.chart-wrap{margin-top:12px;background:var(--card2);border-radius:14px;padding:8px;display:none;border:1px solid var(--border)}.chart-wrap.open{display:block}.chart-box{width:100%;height:300px}.btn-chart{background:var(--card2);border:1px solid var(--border);color:var(--muted);width:100%;margin-top:8px;padding:8px;border-radius:20px}.toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:var(--text);color:var(--bg);padding:12px 20px;border-radius:30px;font-weight:800;z-index:99;display:none;max-width:90%;text-align:center}.hist-table{width:100%;font-size:12px;border-collapse:collapse}.hist-table th{font-size:10px;opacity:.5;text-align:left;padding:6px}.hist-table td{padding:8px 6px;border-top:1px solid var(--border)}.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px}
.modal{position:fixed;top:0;left:0;right:0;bottom:0;background:#000c;backdrop-filter:blur(8px);z-index:100;display:none;align-items:center;justify-content:center;padding:20px}.modal.open{display:flex}.modal-box{background:var(--card);border:1px solid var(--border);border-radius:20px;padding:20px;width:100%;max-width:360px}.input{width:100%;background:var(--card2);border:1px solid var(--border);color:var(--text);padding:12px;border-radius:12px;margin:8px 0;font-size:15px}
</style></head><body>
<div class="header"><div class="h-row"><div class="logo">V€</div><div style="flex:1"><div style="font-weight:900;font-size:14px">Vendi STABILE</div><div style="font-size:10px;opacity:.6">Solo BTC • ETH • ORO (PAXG) | 5M+ no 1M | TF nello storico</div></div><button class="btn btn-icon" id="themeBtn">☀️</button><button class="btn btn-icon" id="notifBtn">🔔</button><button class="btn btn-icon" id="soundBtn">🔊</button><button class="btn btn-icon" id="histBtn">📜</button></div>
<div class="tf-bar"><div class="tf" data-tf="5m">5m</div><div class="tf" data-tf="15m">15m</div><div class="tf active" data-tf="1h">1H</div><div class="tf" data-tf="4h">4H</div><div class="tf" data-tf="1d">1D</div></div></div>

<div class="card" style="display:flex;align-items:center;gap:12px"><div style="width:44px;height:44px;background:var(--card2);border-radius:50%;display:flex;align-items:center;justify-content:center;border:1px solid var(--border)">📊</div><div style="flex:1"><div style="font-size:10px;letter-spacing:2px;opacity:.6">GLOBALE</div><div id="globale" style="font-size:17px;font-weight:900;color:#fbbf24">CARICAMENTO...</div><div id="globaleSub" style="font-size:11px;opacity:.6"></div></div><div style="text-align:right"><div style="font-size:9px;opacity:.5">TF</div><div id="tfLabel" style="font-weight:900">1H</div></div></div>

<div id="coins"></div>
<div class="card" id="historyCard" style="display:none"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><div style="font-weight:900">📜 Storico con TF</div><div style="display:flex;gap:6px"><button class="btn btn-icon" onclick="clearHistory()">🗑️</button><button class="btn btn-icon" onclick="document.getElementById('historyCard').style.display='none'">✕</button></div></div><div style="max-height:400px;overflow-y:auto"><table class="hist-table"><thead><tr><th>ORA</th><th>COIN</th><th>SEGNALE</th><th>%</th><th>PREZZO</th><th>TF</th></tr></thead><tbody id="histBody"></tbody></table></div></div>
<div style="text-align:center;margin-top:10px;font-size:11px;opacity:.4" id="upd"></div><div class="toast" id="toast"></div>

<script>
let soundOn=false,notifOn=false,currentTF='1h',prevSignals={},charts={};
// STABILE: solo i più prevedibili
const SYMBOLS=['BTCEUR','ETHEUR','PAXGEUR'];
const SCAN_TFS=['5m','15m','1h','4h','1d'];
let audioCtx, historyData=JSON.parse(localStorage.getItem('vendi-history-stabile')||'[]');
let savedTheme=localStorage.getItem('vendi-theme')||'dark';
if(savedTheme==='light'){document.body.classList.add('light');document.getElementById('themeBtn').textContent='🌙';}
document.getElementById('themeBtn').onclick=()=>{if(document.body.classList.contains('light')){document.body.classList.remove('light');localStorage.setItem('vendi-theme','dark');document.getElementById('themeBtn').textContent='☀️';} else {document.body.classList.add('light');localStorage.setItem('vendi-theme','light');document.getElementById('themeBtn').textContent='🌙';}};
function showToast(m){const t=document.getElementById('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',3500);}
function pushNotif(title,body){if(!notifOn)return;try{if('serviceWorker' in navigator){navigator.serviceWorker.ready.then(reg=>{reg.showNotification(title,{body,icon:'/icon.png',vibrate:[200,100,200],tag:title})});} else {new Notification(title,{body});}}catch(e){try{new Notification(title,{body})}catch{}}}
async function enableNotif(){let p=await Notification.requestPermission();if(p==='granted'){notifOn=true;localStorage.setItem('vendi-notif','on');document.getElementById('notifBtn').classList.add('on');showToast('🔔 Notifiche attive');pushNotif('Vendi STABILE','Notifiche attive!');}}
document.getElementById('notifBtn').onclick=()=>{if(notifOn){notifOn=false;localStorage.setItem('vendi-notif','off');document.getElementById('notifBtn').classList.remove('on');} else enableNotif();};
if(localStorage.getItem('vendi-notif')==='on'){notifOn=true;document.getElementById('notifBtn').classList.add('on');}
function playSound(t){if(!soundOn)return;try{if(!audioCtx)audioCtx=new (window.AudioContext||window.webkitAudioContext)();const o=audioCtx.createOscillator(),g=audioCtx.createGain();o.connect(g);g.connect(audioCtx.destination);if(t==='COMPRA'){o.frequency.value=880;g.gain.value=0.15;o.start();g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.6);o.stop(audioCtx.currentTime+0.6);} else {o.frequency.value=220;g.gain.value=0.2;o.type='sawtooth';o.start();g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.8);o.stop(audioCtx.currentTime+0.8);}}catch{}}
document.getElementById('soundBtn').onclick=()=>{soundOn=!soundOn;const b=document.getElementById('soundBtn');if(soundOn){b.classList.add('on');if(!audioCtx)audioCtx=new (window.AudioContext||window.webkitAudioContext)();audioCtx.resume();localStorage.setItem('vendi-sound','on');} else {b.classList.remove('on');localStorage.setItem('vendi-sound','off');}};
if(localStorage.getItem('vendi-sound')==='on'){soundOn=true;document.getElementById('soundBtn').classList.add('on');}
document.getElementById('histBtn').onclick=()=>{const c=document.getElementById('historyCard');c.style.display=c.style.display==='none'?'block':'none';renderHistory();};
function clearHistory(){if(confirm('Pulire?')){historyData=[];localStorage.setItem('vendi-history-stabile','[]');renderHistory();}}
function addHistory(sym,stato,conf,price,reasons,tf){
 if(conf<60) return;
 const last = historyData[0];
 if(last && last.sym===sym && last.stato===stato && last.tf===tf && Date.now()-last.time<300000) return;
 historyData.unshift({time:Date.now(),sym,stato,conf,price,reasons:reasons[0]||'',tf:tf||currentTF});
 if(historyData.length>200)historyData.pop();
 localStorage.setItem('vendi-history-stabile',JSON.stringify(historyData));renderHistory();
}
function renderHistory(){
 const tb=document.getElementById('histBody');
 let filtered=historyData.filter(h=>h.conf>=60);
 if(!filtered.length){tb.innerHTML='<tr><td colspan=6 style="text-align:center;opacity:.5;padding:20px">Nessun segnale</td></tr>';return;}
 tb.innerHTML=filtered.slice(0,80).map(h=>{
  const d=new Date(h.time);const t=d.toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'});
  const col=h.stato==='COMPRA'?'#10b981':h.stato==='VENDI'?'#ef4444':'#fbbf24';
  const tfLabel=(h.tf||'').toUpperCase();
  return `<tr><td>${t}</td><td><b>${h.sym}</b></td><td><span class="dot" style="background:${col}"></span>${h.stato}</td><td>${h.conf}%</td><td>€${h.price.toFixed(2)}</td><td><b>${tfLabel}</b></td></tr>`;
 }).join('');
}
document.querySelectorAll('.tf').forEach(el=>{el.onclick=()=>{document.querySelectorAll('.tf').forEach(x=>x.classList.remove('active'));el.classList.add('active');currentTF=el.dataset.tf;document.getElementById('tfLabel').textContent=currentTF.toUpperCase();refresh();};});
function calcRSI(p,period=14){if(p.length<period+1)return 50;let g=0,l=0;for(let i=1;i<=period;i++){let d=p[i]-p[i-1];if(d>=0)g+=d;else l-=d;}let ag=g/period,al=l/period;if(al===0)return 85;for(let i=period+1;i<p.length;i++){let d=p[i]-p[i-1];let gg=d>0?d:0,ll=d<0?-d:0;ag=(ag*(period-1)+gg)/period;al=(al*(period-1)+ll)/period;}return 100-100/(1+ag/al);}
function calcEMA(p,period){let k=2/(period+1);let ema=p[0];for(let i=1;i<p.length;i++)ema=p[i]*k+ema*(1-k);return ema;}
function calcEMAArray(p,period){let k=2/(period+1);let ema=p[0];let arr=[ema];for(let i=1;i<p.length;i++){ema=p[i]*k+ema*(1-k);arr.push(ema);}return arr;}
function calcConfidence(o){let c=50,r=[];let div=Math.abs(o.ema20-o.ema50)/o.ema50*100;if(o.stato==='COMPRA'){if(o.rsi<25){c+=28;r.push('Ipervenduto');} else if(o.rsi<35){c+=18;r.push('RSI basso');} else if(o.rsi>60){c-=12;r.push('RSI alto');}if(o.ema20>o.ema50){c+=14;r.push('Rialzista');} else {c-=14;r.push('Contro-trend');}if(o.volLabel==='VOL ALTO'){c+=14;r.push('Vol alto');} else if(o.volLabel==='VOL BASSO'){c-=16;r.push('Vol basso');}} else if(o.stato==='VENDI'){if(o.rsi>75){c+=28;r.push('Ipercomprato');} else if(o.rsi>65){c+=18;r.push('RSI alto');} else if(o.rsi<40){c-=12;r.push('RSI basso');}if(o.ema20<o.ema50){c+=14;r.push('Ribassista');} else {c-=14;r.push('Contro-trend');}if(o.volLabel==='VOL ALTO'){c+=14;r.push('Vol alto');} else if(o.volLabel==='VOL BASSO'){c-=16;r.push('Vol debole');}} else {c=45+(Math.abs(o.rsi-50)/2);r.push('Laterale');}return {conf:Math.max(12,Math.min(94,Math.round(c))),reasons:r};}
async function fetchKlines(sym,interval,limit=150){const urls=[`https://api.binance.com/api/v3/klines?symbol=${sym}&interval=${interval}&limit=${limit}`,`https://data-api.binance.vision/api/v3/klines?symbol=${sym}&interval=${interval}&limit=${limit}`];for(let u of urls){try{let r=await fetch(u);if(!r.ok)continue;let j=await r.json();if(j.length)return j;}catch{} }return [];}
async function loadCoinForTF(sym, tf){
 try{
  let kl=await fetchKlines(sym,tf,150); if(!kl.length) return null;
  let closes=kl.map(c=>parseFloat(c[4]));let volumes=kl.map(c=>parseFloat(c[5]));
  let price=closes[closes.length-1]; let rsi=calcRSI(closes,14);let ema20=calcEMA(closes,20);let ema50=calcEMA(closes,50);
  let volNow=volumes[volumes.length-1];let volAvg=volumes.slice(-21,-1).reduce((a,b)=>a+b,0)/20;
  let volLabel=volNow < volAvg*0.7 ? 'VOL BASSO' : volNow > volAvg*1.9 ? 'VOL ALTO' : 'VOL NORMALE';
  let trend=ema20>ema50?'Rialzista':'Ribassista';let stato='FERMO',col='#fbbf24',tc='#000';
  if(rsi>70){stato='VENDI';col='#ef4444';tc='#fff';} else if(rsi<30){stato='COMPRA';col='#10b981';} else if(ema20>ema50 && rsi>55){stato='COMPRA';col='#10b981';} else if(ema20<ema50 && rsi<45){stato='VENDI';col='#ef4444';tc='#fff';}
  let cr=calcConfidence({stato,rsi,ema20,ema50,volLabel,price});
  if(cr.conf>=60 && (stato==='COMPRA'||stato==='VENDI')){
    const key=sym+'_'+tf;
    if(!prevSignals[key] || prevSignals[key]!==stato){
      const lastSame=historyData.find(h=>h.sym===sym && h.tf===tf && h.stato===stato);
      const canNotify=!lastSame || (Date.now()-lastSame.time>600000);
      if(canNotify){addHistory(sym,stato,cr.conf,price,cr.reasons,tf); playSound(stato); pushNotif(`${sym}: ${stato} ${cr.conf}% [${tf.toUpperCase()}]`,`€${price.toFixed(2)} - ${cr.reasons[0]||''}`); showToast(`${sym} ${stato} ${cr.conf}% su ${tf.toUpperCase()}`);}
    }
    prevSignals[key]=stato;
  }
  return {sym,price,rsi,ema20,ema50,trend,stato,col,tc,volLabel,conf:cr.conf,reasons:cr.reasons,kl};
 }catch(e){return null;}
}
async function loadCoin(sym){return await loadCoinForTF(sym,currentTF);}
function renderCandle(sym,kl){
 const container=document.getElementById('chart-'+sym);if(!container)return;container.innerHTML='';const chart=LightweightCharts.createChart(container,{width:container.clientWidth,height:300,layout:{background:{type:'solid',color:'transparent'},textColor:getComputedStyle(document.body).getPropertyValue('--muted')},grid:{vertLines:{color:getComputedStyle(document.body).getPropertyValue('--border')},horzLines:{color:getComputedStyle(document.body).getPropertyValue('--border')}},rightPriceScale:{borderColor:getComputedStyle(document.body).getPropertyValue('--border')},timeScale:{borderColor:getComputedStyle(document.body).getPropertyValue('--border')}});
 const candleSeries=chart.addCandlestickSeries({upColor:'#10b981',downColor:'#ef4444',borderVisible:false,wickUpColor:'#10b981',wickDownColor:'#ef4444'});
 const data=kl.map(k=>({time:Math.floor(k[0]/1000),open:parseFloat(k[1]),high:parseFloat(k[2]),low:parseFloat(k[3]),close:parseFloat(k[4])}));candleSeries.setData(data);
 const closes=kl.map(k=>parseFloat(k[4]));const ema20Arr=calcEMAArray(closes,20);const ema50Arr=calcEMAArray(closes,50);
 const ema20Line=chart.addLineSeries({color:'#3b82f6',lineWidth:1});ema20Line.setData(data.map((d,i)=>({time:d.time,value:ema20Arr[i]})).filter((_,i)=>i>=20));
 const ema50Line=chart.addLineSeries({color:'#f59e0b',lineWidth:1});ema50Line.setData(data.map((d,i)=>({time:d.time,value:ema50Arr[i]})).filter((_,i)=>i>=50));
 chart.timeScale().fitContent();charts[sym]={chart};
}
async function refresh(){
 let html='',segnali=[];let results=await Promise.all(SYMBOLS.map(s=>loadCoin(s)));results=results.filter(Boolean);
 for(let d of results){
  segnali.push(d.stato); let name=d.sym.replace('EUR',''); let confColor=d.conf>=75?'#10b981':d.conf>=55?'#fbbf24':'#ef4444';
  html+=`<div class="card"><div style="display:flex;justify-content:space-between;align-items:center"><div style="display:flex;gap:10px;align-items:center"><div style="width:42px;height:42px;background:var(--card2);border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:900;border:1px solid var(--border)">${name[0]}</div><div><div style="font-weight:900">${d.sym}</div><div style="font-size:11px;opacity:.6">${name} • ${d.volLabel}</div></div></div><div style="text-align:right"><div class="badge" style="background:${d.col};color:${d.tc}">${d.stato}</div><div style="font-size:11px;margin-top:4px;font-weight:800;color:${confColor}">${d.conf}%</div></div></div><div class="price" style="margin:10px 0">€${d.price.toLocaleString('it-IT',{minimumFractionDigits:2,maximumFractionDigits:2})}</div><div style="display:flex;justify-content:space-between;font-size:11px"><span style="opacity:.6">${d.reasons.slice(0,2).join(' • ')}</span><span style="font-weight:800;color:${confColor}">${d.conf}% affidabile</span></div><div class="conf-bar"><div class="conf-fill" style="width:${d.conf}%;background:${confColor}"></div></div><div class="grid3"><div class="card" style="margin:0;background:var(--card2)"><div class="mini">RSI</div><span class="val">${d.rsi.toFixed(1)}</span></div><div class="card" style="margin:0;background:var(--card2)"><div class="mini">EMA</div><span class="val" style="color:${d.trend==='Rialzista'?'#10b981':'#ef4444'}">${d.trend}</span></div><div class="card" style="margin:0;background:var(--card2)"><div class="mini">Vol</div><span class="val">${d.volLabel.replace('VOL ','')}</span></div></div><div style="display:flex;gap:6px"><button class="btn btn-chart" style="flex:1" onclick="toggleChart('${d.sym}')">🕯️ Candele</button></div><div class="chart-wrap" id="wrap-${d.sym}"><div class="chart-box" id="chart-${d.sym}"></div></div></div>`;
 }
 document.getElementById('coins').innerHTML=html;
 let comp=segnali.filter(s=>s==='COMPRA').length,vend=segnali.filter(s=>s==='VENDI').length;
 let glob=document.getElementById('globale'),sub=document.getElementById('globaleSub');
 if(comp>=2){glob.textContent='COMPRA';glob.style.color='#10b981';sub.textContent=comp+'/'+SYMBOLS.length+' COMPRA';}
 else if(vend>=2){glob.textContent='VENDI';glob.style.color='#ef4444';sub.textContent=vend+'/'+SYMBOLS.length+' VENDI';}
 else {glob.textContent='FERMO';glob.style.color='#fbbf24';sub.textContent='Laterale';}
 document.getElementById('upd').textContent='Agg: '+new Date().toLocaleTimeString('it-IT')+' • TF:'+currentTF+' • Scan 5M-1D (no 1M) | BTC ETH ORO';
 setTimeout(async ()=>{for(let tf of SCAN_TFS){if(tf===currentTF) continue; for(let sym of SYMBOLS){await loadCoinForTF(sym,tf); await new Promise(r=>setTimeout(r,300));}}},2000);
}
function toggleChart(sym){const wrap=document.getElementById('wrap-'+sym);const isOpen=wrap.classList.contains('open');document.querySelectorAll('.chart-wrap').forEach(w=>w.classList.remove('open'));if(!isOpen){wrap.classList.add('open');const d=window._lastData?.find(x=>x.sym===sym);}}
refresh();setInterval(refresh,60000);renderHistory();
</script></body></html>
"""

@app.route("/")
def home():
    return '<a href="/app">Vai alla versione STABILE - BTC ETH ORO</a>'

@app.route("/app")
def app_route():
    return Response(HTML, mimetype="text/html")

@app.route("/icon.png")
def icon():
    import base64
    png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
    return Response(base64.b64decode(png), mimetype="image/png")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
