"""
Vendi STABILE PRO - STORICO SEGNALI >60% per 1H e 4H
"""

import os, json, time, threading, requests
from datetime import datetime
from flask import Flask, request, jsonify, Response

try:
    from flask_cors import CORS
    HAS_CORS=True
except: HAS_CORS=False

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U6_Q")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:test@test.com")

SUBS_FILE="subscriptions.json"
LAST_FILE="last_signals.json"
HISTORY_FILE="signals_history.json"

app=Flask(__name__)
if HAS_CORS: CORS(app)

def load_json(p,d):
    try:
        if os.path.exists(p):
            with open(p,"r") as f: return json.load(f)
    except: pass
    return d
def save_json(p,d):
    try:
        with open(p,"w") as f: json.dump(f,d)
    except: pass

subscriptions=load_json(SUBS_FILE, [])
last_signals=load_json(LAST_FILE, {})
history=load_json(HISTORY_FILE, [])

SYMBOLS = {"BTC": "BTCUSDT","ETH": "ETHUSDT","ORO": "PAXGUSDT",}
TF_MAP={"5m":"5m","15m":"15m","1H":"1h","4H":"4h","1D":"1d"}
BINANCE_BASES=["https://data-api.binance.vision","https://api1.binance.com","https://api2.binance.com"]

def get_klines(symbol, interval, limit=100):
    headers={"User-Agent":"Mozilla/5.0"}
    for base in BINANCE_BASES:
        try:
            url=f"{base}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            r=requests.get(url, timeout=10, headers=headers)
            if r.status_code in (451,403,400): continue
            r.raise_for_status()
            return [float(c[4]) for c in r.json()]
        except: continue
    return None

def get_eur_rate():
    try:
        c=get_klines("EURUSDT","1m",1)
        if c: return c[-1]
    except: pass
    return 1.1561

def calc_rsi(prices, period=14):
    if not prices or len(prices)<period+1: return 50
    gains=sum(max(0, prices[-i]-prices[-i-1]) for i in range(1, period+1))
    losses=sum(max(0, prices[-i-1]-prices[-i]) for i in range(1, period+1))
    if losses==0: return 95 if gains>0 else 50
    return round(100-(100/(1+gains/losses)),2)

def get_signal(rsi): return "COMPRA" if rsi<=30 else "VENDI" if rsi>=70 else "FERMO"
def get_conf(rsi): return min(95, max(52, int(50 + abs(rsi-50)*1.8)))
def get_trend(rsi): return "Rialzista" if rsi>=60 else "Ribassista" if rsi<=40 else "Laterale"

def add_history(coin, tf, info):
    if tf not in ("1H","4H"): return
    if info["conf"]<60: return
    if info["signal"] not in ("COMPRA","VENDI"): return
    now=datetime.now()
    # evita duplicati uguali entro 1h
    if history:
        try:
            last=history[-1]
            lt=datetime.fromisoformat(last["timestamp"])
            if last["coin"]==coin and last["tf"]==tf and last["signal"]==info["signal"] and (now-lt).total_seconds()<3600:
                return
        except: pass
    entry={"timestamp":now.isoformat(),"time":now.strftime("%d/%m %H:%M"),"coin":coin,"tf":tf,"signal":info["signal"],"conf":info["conf"],"rsi":info["rsi"],"price":info["price"],"trend":info["trend"]}
    history.append(entry)
    if len(history)>200: del history[0:len(history)-200]
    save_json(HISTORY_FILE, history)
    print(f"STORICO salvato: {entry}")

def get_all_signals(tf="4H"):
    interval=TF_MAP.get(tf,"4h")
    eur_rate=get_eur_rate()
    results={}
    globale="FERMO"
    for name, sym in SYMBOLS.items():
        closes=get_klines(sym, interval)
        if not closes:
            results[name]={"symbol":sym,"rsi":0,"signal":"OFFLINE","price":0,"conf":0,"trend":"-"}
            continue
        rsi=calc_rsi(closes)
        signal=get_signal(rsi)
        results[name]={"symbol":sym.replace("USDT","EUR"),"rsi":rsi,"signal":signal,"price":closes[-1]/eur_rate,"conf":get_conf(rsi),"trend":get_trend(rsi),"tf":tf}
        if signal in ("COMPRA","VENDI"): globale=signal
    return {"coins":results,"globale":globale,"tf":tf,"updated":datetime.now().strftime("%H:%M:%S"),"eur_rate":eur_rate}

def send_push(title, body, coin="BTC", tf="4H"):
    if not subscriptions or not VAPID_PRIVATE_KEY: return 0
    try:
        from pywebpush import webpush
    except: return 0
    payload=json.dumps({"title":"[SERVER] "+title,"body":body,"url":f"/app?coin={coin}&tf={tf}"})
    ok=0
    for sub in subscriptions:
        try:
            webpush(subscription_info=sub, data=payload, vapid_private_key=VAPID_PRIVATE_KEY, vapid_claims={"sub":VAPID_SUBJECT}); ok+=1
        except: pass
    return ok

def checker():
    print("Checker con STORICO >60% 1H/4H avviato")
    while True:
        try:
            for tf in ["1H","4H"]:
                data=get_all_signals(tf)
                for cname, info in data["coins"].items():
                    add_history(cname, tf, info)
                    key=f"{cname}_{tf}"
                    if info["signal"] in ("COMPRA","VENDI") and info["signal"]!=last_signals.get(key,"FERMO") and info["conf"]>=60:
                        send_push(f"{cname}: {info['signal']} {info['conf']}%", f"€{info['price']:.2f} - {info['trend']} RSI {info['rsi']} TF {tf}", coin=cname, tf=tf)
                    last_signals[key]=info["signal"]
                save_json(LAST_FILE, last_signals)
                time.sleep(2)
            # check anche altri TF per UI ma senza storico
            for tf in ["5m","15m","1D"]:
                data=get_all_signals(tf)
                for cname, info in data["coins"].items():
                    last_signals[f"{cname}_{tf}"]=info["signal"]
            time.sleep(60)
        except Exception as e:
            print(f"loop err {e}"); time.sleep(20)

@app.route("/api/ping")
def ping(): return jsonify({"ok":True,"history":len(history)})
@app.route("/api/signals")
def sig(): return jsonify(get_all_signals(request.args.get("tf","4H")))
@app.route("/api/history")
def hist_api():
    coin=request.args.get("coin")
    min_conf=int(request.args.get("min_conf","60"))
    filtered=[h for h in history if h["conf"]>=min_conf and h["tf"] in ("1H","4H")]
    if coin: filtered=[h for h in filtered if h["coin"]==coin]
    filtered=sorted(filtered, key=lambda x: x["timestamp"], reverse=True)[:100]
    return jsonify(filtered)

@app.route("/api/push/subscribe", methods=["POST"])
def sub():
    s=request.get_json()
    if s and s not in subscriptions:
        subscriptions.append(s); save_json(SUBS_FILE, subscriptions)
    return jsonify({"ok":True})
@app.route("/api/push/test", methods=["POST"])
def testp():
    d=request.get_json(silent=True) or {}
    send_push(f"TEST {d.get('coin','BTC')} COMPRA 75%", "Test storico", coin=d.get('coin','BTC'), tf=d.get('tf','4H'))
    return jsonify({"ok":True,"sent_to":len(subscriptions)})
@app.route("/sw.js")
def sw(): return Response("self.addEventListener('push',e=>{let d={};try{d=e.data.json()}catch{};self.registration.showNotification(d.title||'[SERVER]',{body:d.body||'',data:{url:d.url||'/app'}})});self.addEventListener('notificationclick',e=>{e.notification.close();clients.openWindow(e.notification.data.url||'/app')});", mimetype="application/javascript")

@app.route("/")
@app.route("/app")
def app_page():
    return """
<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Vendi STABILE PRO</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
*{font-family:'Inter',sans-serif;box-sizing:border-box;margin:0;padding:0}
body{background:#f8fafc;min-height:100vh;padding:12px 12px 100px}
.header{background:linear-gradient(135deg,#6366f1 0%,#8b5cf6 100%);border-radius:20px;padding:18px;color:white;display:flex;justify-content:space-between;align-items:center;box-shadow:0 10px 25px rgba(99,102,241,.3)}
.logo{width:48px;height:48px;background:rgba(255,255,255,.2);border-radius:14px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:20px}
.tfs{display:flex;gap:8px;margin:16px 0;overflow-x:auto}
.tfs button{border:none;background:white;padding:10px 18px;border-radius:999px;font-weight:600;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.tfs button.active{background:#0f172a;color:white}
.global-card{background:white;border-radius:20px;padding:16px 18px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 4px 20px rgba(0,0,0,.05);border:1px solid #f1f5f9}
.coin-card{background:white;border-radius:20px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.05);border:1px solid #f1f5f9;margin-top:14px}
.coin-row{display:flex;justify-content:space-between;align-items:center;padding:16px 18px;border-bottom:1px solid #f8fafc;cursor:pointer}
.coin-row:active{background:#f8fafc}
.coin-left{display:flex;gap:12px;align-items:center}
.coin-icon{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:700;color:white}
.btc{background:linear-gradient(135deg,#f59e0b,#f97316)}.eth{background:linear-gradient(135deg,#6366f1,#8b5cf6)}.oro{background:linear-gradient(135deg,#eab308,#ca8a04)}
.badge{padding:6px 12px;border-radius:999px;font-weight:700;font-size:12px}
.FERMO-bg{background:#fef3c7;color:#d97706}.COMPRA-bg{background:#dcfce7;color:#16a34a}.VENDI-bg{background:#fee2e2;color:#dc2626}
.fab{position:fixed;bottom:20px;left:12px;right:12px;display:flex;gap:10px;z-index:20}
.fab button{flex:1;padding:14px;border-radius:16px;border:none;font-weight:700;box-shadow:0 8px 20px rgba(0,0,0,.15)}
.btn-dark{background:#0f172a;color:white}.btn-light{background:white;color:#0f172a;border:1px solid #e2e8f0!important}
#modal{position:fixed;inset:0;background:rgba(15,23,42,.6);backdrop-filter:blur(8px);display:none;align-items:end;justify-content:center;z-index:50;padding:12px}
#modal.show{display:flex}
.modal-box{background:white;width:100%;max-width:480px;border-radius:28px;padding:22px;max-height:85vh;overflow:auto;animation:slide .25s ease}
@keyframes slide{from{transform:translateY(100%)}to{transform:translateY(0)}}
.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}
.detail-item{background:#f8fafc;border-radius:14px;padding:12px}
.hist-item{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;border-radius:12px;background:#f8fafc;margin:6px 0;font-size:13px}
</style>
</head><body>
<div class=header><div style="display:flex;gap:12px;align-items:center"><div class=logo>V€</div><div><div style="font-weight:800">Vendi STABILE PRO</div><div style="opacity:.8;font-size:12px">BTC • ETH • ORO • PUSH VERO</div><div style="opacity:.7;font-size:11px" id=subStatus>Push: verifica...</div></div></div>🔔</div>
<div class=tfs><button onclick="loadTF('5m')" id=b5m>5m</button><button onclick="loadTF('15m')" id=b15m>15m</button><button onclick="loadTF('1H')" id=b1H>1H</button><button onclick="loadTF('4H')" id=b4H class=active>4H</button><button onclick="loadTF('1D')" id=b1D>1D</button></div>
<div class=global-card><div><div style="font-size:11px;color:#64748b">GLOBALE</div><div style="font-weight:800;font-size:18px" id=globale>...</div><div style="font-size:12px;color:#64748b" id=globaleSub>TF 4H</div></div><div style="text-align:right"><div style="font-size:11px;color:#64748b">AGGIORNATO</div><div style="font-weight:700" id=agg>--</div><div style="font-size:11px;color:#94a3b8" id=eurRate></div></div></div>
<div class=coin-card id=coins><div style="padding:30px;text-align:center;color:#94a3b8">Caricamento...</div></div>

<div class=coin-card style="margin-top:16px"><div style="padding:14px 18px;display:flex;justify-content:space-between;align-items:center;cursor:pointer" onclick="toggleHist()"><div><b>📜 Storico segnali affidabili</b><div style="font-size:12px;color:#64748b">Solo 1H e 4H con >60% affidabilità</div></div><div id=histArrow>▼</div></div><div id=histList style="display:none;padding:0 12px 12px"></div></div>

<div class=fab><button class=btn-light onclick="testPush()">🔔 Test</button><button class=btn-dark onclick="subscribePush()">📢 Attiva Push</button></div>

<div id=modal onclick="if(event.target==this)closeModal()"><div class=modal-box>
  <div style="display:flex;justify-content:space-between"><div><b id=mCoin>BTC</b><div id=mPrice style="color:#64748b;font-size:13px"></div></div><button onclick="closeModal()" style="width:32px;height:32px;border-radius:999px;border:none;background:#f1f5f9">✕</button></div>
  <div class=detail-grid><div class=detail-item><small>SEGNALE</small><b id=mSignal>-</b><div id=mConf style="font-size:12px;color:#64748b"></div></div><div class=detail-item><small>RSI / TREND</small><b id=mRsi>-</b><div id=mTrend style="font-size:12px"></div></div></div>
  <div id=mExplain style="background:#f1f5f9;border-radius:12px;padding:12px;font-size:13px;color:#334155"></div>
  <div style="margin-top:14px"><b style="font-size:13px">Storico >60% per <span id=mHistCoin>BTC</span> (1H/4H)</b><div id=mHist style="margin-top:8px"></div></div>
  <button onclick="openChart()" style="margin-top:14px;width:100%;padding:12px;border-radius:12px;border:none;background:#0f172a;color:white;font-weight:700">📈 Apri TradingView</button>
</div></div>

<script>
let curTF='4H', lastData=null, currentDetail=null;
const VAPID='BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U6_Q';
function toUint8(b){const p='='.repeat((4-b.length%4)%4);return Uint8Array.from([...atob((b+p).replace(/-/g,'+').replace(/_/g,'/'))].map(c=>c.charCodeAt(0)));}
async function subscribePush(){try{const reg=await navigator.serviceWorker.register('/sw.js');await Notification.requestPermission();const sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:toUint8(VAPID)});await fetch('/api/push/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(sub)});document.getElementById('subStatus').innerText='Push: ATTIVO [SERVER]';alert('Push attiva');}catch(e){alert(e)}}
async function testPush(){await fetch('/api/push/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({coin:'BTC',tf:curTF})});alert('Test inviato');}
function colorFor(s){return s=='COMPRA'?'#16a34a':s=='VENDI'?'#dc2626':'#d97706'}
function bgFor(s){return s=='COMPRA'?'COMPRA-bg':s=='VENDI'?'VENDI-bg':'FERMO-bg'}
async function loadTF(tf){
  curTF=tf; document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active')); document.getElementById('b'+tf).classList.add('active');
  document.getElementById('coins').innerHTML='<div style="padding:30px;text-align:center;color:#94a3b8">Caricamento...</div>';
  try{
    const res=await fetch('/api/signals?tf='+tf); const d=await res.json(); lastData=d;
    document.getElementById('globale').innerText=d.globale; document.getElementById('globale').style.color=colorFor(d.globale);
    document.getElementById('globaleSub').innerText=d.globale+' • TF '+tf; document.getElementById('agg').innerText=d.updated; document.getElementById('eurRate').innerText='EUR '+d.eur_rate.toFixed(4);
    let html='';
    for(let [name, info] of Object.entries(d.coins)){
      const icon=name=='BTC'?'btc':name=='ETH'?'eth':'oro'; const ico=name=='BTC'?'₿':name=='ETH'?'Ξ':'Au';
      html+=`<div class=coin-row onclick="openDetails('${name}')"><div class=coin-left><div class="coin-icon ${icon}">${ico}</div><div><b>${name}</b><div style="font-size:12px;color:#64748b">RSI ${info.rsi} • ${info.trend}</div><div style="font-size:11px;color:#94a3b8">Affidabilità ${info.conf}%</div></div></div><div style="text-align:right"><span class="badge ${bgFor(info.signal)}">${info.signal} ${info.conf}%</span><div style="font-weight:800;margin-top:4px">€${info.price.toFixed(2)}</div><div style="font-size:11px;color:#94a3b8">TAP per dettagli ›</div></div></div>`;
    }
    document.getElementById('coins').innerHTML=html;
    loadHistGlobal();
  }catch(e){document.getElementById('coins').innerText='Errore '+e;}
}
async function loadHistGlobal(){
  try{
    const r=await fetch('/api/history?min_conf=60'); const list=await r.json();
    const c=document.getElementById('histList');
    if(!list.length){c.innerHTML='<div style="padding:10px;color:#94a3b8;font-size:13px">Nessun segnale >60% ancora su 1H/4H. Appena arriva un COMPRA/VENDI affidabile lo vedrai qui.</div>'; return;}
    c.innerHTML=list.map(h=>`<div class=hist-item><div><b>${h.coin}</b> <span style="padding:3px 8px;border-radius:999px;font-size:11px;font-weight:700;background:${h.signal=='COMPRA'?'#dcfce7':'#fee2e2'};color:${h.signal=='COMPRA'?'#16a34a':'#dc2626'}">${h.signal} ${h.conf}%</span> <small>${h.tf}</small></div><div style="text-align:right"><div>€${h.price.toFixed(2)}</div><div style="font-size:11px;color:#94a3b8">${h.time}</div></div></div>`).join('');
  }catch{}
}
function toggleHist(){const l=document.getElementById('histList');const a=document.getElementById('histArrow'); if(l.style.display=='none'){l.style.display='block';a.innerText='▲';loadHistGlobal();}else{l.style.display='none';a.innerText='▼'}}
async function openDetails(coin){
  if(!lastData) return; const info=lastData.coins[coin]; if(!info) return; currentDetail=coin;
  document.getElementById('mCoin').innerText=coin+' • '+info.symbol; document.getElementById('mPrice').innerText='€'+info.price.toFixed(2);
  document.getElementById('mSignal').innerText=info.signal; document.getElementById('mSignal').style.color=colorFor(info.signal);
  document.getElementById('mConf').innerText=info.signal+' '+info.conf+'%'; document.getElementById('mRsi').innerText=info.rsi; document.getElementById('mTrend').innerText=info.trend;
  document.getElementById('mHistCoin').innerText=coin;
  let txt= info.signal=='VENDI'?`RSI ${info.rsi} ipercomprato (${info.trend}). Affidabilità ${info.conf}% su ${info.tf}.` : info.signal=='COMPRA'?`RSI ${info.rsi} ipervenduto (${info.trend}). Affidabilità ${info.conf}%.` : `RSI ${info.rsi} neutro (${info.trend}). Laterale, affidabilità ${info.conf}% - meglio attendere.`;
  document.getElementById('mExplain').innerText=txt;
  document.getElementById('modal').classList.add('show');
  // storico specifico
  try{
    const r=await fetch('/api/history?coin='+coin+'&min_conf=60'); const list=await r.json();
    document.getElementById('mHist').innerHTML = list.length ? list.slice(0,8).map(h=>`<div class=hist-item><div><b>${h.tf}</b> ${h.signal} ${h.conf}%</div><div>${h.time} €${h.price.toFixed(0)}</div></div>`).join('') : '<div style="font-size:12px;color:#94a3b8">Nessuno storico >60% per questo coin ancora</div>';
  }catch{}
}
function closeModal(){document.getElementById('modal').classList.remove('show')}
function openChart(){if(!currentDetail)return;const map={BTC:'BINANCE:BTCUSDT',ETH:'BINANCE:ETHUSDT',ORO:'OANDA:XAUUSD'};window.open('https://www.tradingview.com/chart/?symbol='+map[currentDetail]+'&interval='+curTF,'_blank');}
loadTF('4H'); setInterval(()=>loadTF(curTF),60000);
if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js');}
</script>
</body></html>
"""

threading.Thread(target=checker, daemon=True).start()
if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
 
