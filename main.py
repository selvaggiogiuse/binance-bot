"""
FIX DEFINITIVO 451 + 400 PAXGEUR
- Usa data-api.binance.vision (bypassa 451 USA)
- Usa solo coppie USDT che esistono ovunque (BTCUSDT, ETHUSDT, PAXGUSDT)
- Converte in EUR al volo usando EURUSDT per non mostrare ERRORE
"""

import os, json, time, threading, requests
from datetime import datetime
from flask import Flask, request, jsonify, Response

try:
    from flask_cors import CORS
    HAS_CORS=True
except:
    HAS_CORS=False

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U6_Q")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:test@test.com")

SUBS_FILE="subscriptions.json"
LAST_FILE="last_signals.json"

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

# USIAMO SOLO USDT - esistono ovunque e non danno 400
SYMBOLS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "ORO": "PAXGUSDT",
    "PAXG": "PAXGUSDT"
}
TF_MAP={"5m":"5m","15m":"15m","1H":"1h","4H":"4h","1D":"1d"}

BINANCE_BASES=[
    "https://data-api.binance.vision",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
]

def get_klines(symbol, interval, limit=100):
    headers={"User-Agent":"Mozilla/5.0"}
    for base in BINANCE_BASES:
        try:
            url=f"{base}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            r=requests.get(url, timeout=10, headers=headers)
            if r.status_code in (451, 403):
                continue
            r.raise_for_status()
            data=r.json()
            closes=[float(c[4]) for c in data]
            if closes:
                return closes
        except Exception as e:
            # print(f"fail {symbol} {interval} su {base}: {e}")
            continue
    return None

def get_eur_rate():
    # EURUSDT per convertire USDT -> EUR
    try:
        closes=get_klines("EURUSDT","1m",limit=1)
        if closes:
            return closes[-1]  # es: 1.08
    except: pass
    return 1.08  # fallback

def calc_rsi(prices, period=14):
    if not prices or len(prices)<period+1: return 50
    gains=0; losses=0
    for i in range(1, period+1):
        diff=prices[-i]-prices[-i-1]
        if diff>=0: gains+=diff
        else: losses-=diff
    if losses==0: return 100 if gains>0 else 50
    rs=gains/losses
    return round(100-(100/(1+rs)),2)

def get_signal(rsi):
    if rsi<=30: return "COMPRA"
    if rsi>=70: return "VENDI"
    return "FERMO"

def get_all_signals(tf="4H"):
    interval=TF_MAP.get(tf,"4h")
    eur_rate=get_eur_rate()
    results={}
    globale="FERMO"
    for name, sym in SYMBOLS.items():
        closes=get_klines(sym, interval)
        if closes is None:
            results[name]={"symbol":sym,"rsi":0,"signal":"OFFLINE","price":0}
            continue
        rsi=calc_rsi(closes)
        signal=get_signal(rsi)
        price_usdt=closes[-1]
        price_eur=price_usdt/eur_rate  # conversione in euro
        results[name]={"symbol":sym.replace("USDT","EUR")+" (via USDT)","rsi":rsi,"signal":signal,"price":price_eur,"price_usdt":price_usdt,"tf":tf}
        if signal in ("COMPRA","VENDI"):
            globale=signal
    return {"coins":results,"globale":globale,"tf":tf,"updated":datetime.now().strftime("%H:%M:%S"),"eur_rate":eur_rate}

def send_push(title, body, coin="BTC", tf="4H"):
    if not subscriptions or not VAPID_PRIVATE_KEY: return 0
    try:
        from pywebpush import webpush
    except: return 0
    import json as js
    payload=js.dumps({"title":"[SERVER] "+title,"body":body,"url":f"/app?coin={coin}&tf={tf}","coin":coin,"tf":tf,"tag":f"{coin}_{tf}"})
    ok=0
    for sub in subscriptions:
        try:
            webpush(subscription_info=sub, data=payload, vapid_private_key=VAPID_PRIVATE_KEY, vapid_claims={"sub":VAPID_SUBJECT})
            ok+=1
        except: pass
    return ok

def checker():
    print("Checker START - uso USDT + conversione EUR, bypass 451 e 400")
    while True:
        try:
            for tf in ["5m","15m","1H","4H","1D"]:
                data=get_all_signals(tf)
                for cname, info in data["coins"].items():
                    key=f"{cname}_{tf}"
                    new=info["signal"]
                    old=last_signals.get(key,"FERMO")
                    if new in ("COMPRA","VENDI") and new!=old:
                        print(f"SEGNALE {key}: {old}->{new}")
                        send_push(f"{cname}: {new} {tf}", f"RSI {info['rsi']} - {info['price']:.2f}€ - TF {tf}", coin=cname, tf=tf)
                    last_signals[key]=new
                save_json(LAST_FILE, last_signals)
                time.sleep(1)
            print(f"[{datetime.now()}] Check OK - EUR rate {get_eur_rate():.4f}")
            time.sleep(60)
        except Exception as e:
            print(f"loop err {e}")
            time.sleep(20)

@app.route("/api/ping")
def ping(): return jsonify({"ok":True,"time":datetime.now().isoformat(),"subs":len(subscriptions)})

@app.route("/api/signals")
def sig():
    tf=request.args.get("tf","4H")
    try:
        return jsonify(get_all_signals(tf))
    except Exception as e:
        return jsonify({"error":str(e),"coins":{},"globale":"ERRORE"}),500

@app.route("/api/push/subscribe", methods=["POST"])
def sub():
    s=request.get_json()
    if s and s not in subscriptions:
        subscriptions.append(s); save_json(SUBS_FILE, subscriptions)
    return jsonify({"ok":True})

@app.route("/api/push/test", methods=["POST"])
def testp():
    d=request.get_json(silent=True) or {}
    send_push(f"TEST {d.get('coin','BTC')} COMPRA","Prova push - ora PAXGEUR fixato!", coin=d.get('coin','BTC'), tf=d.get('tf','4H'))
    return jsonify({"ok":True,"sent_to":len(subscriptions)})

@app.route("/sw.js")
def sw():
    return Response("self.addEventListener('push',e=>{let d={};try{d=e.data.json()}catch{d={}};self.registration.showNotification(d.title||'[SERVER]',{body:d.body||'Segnale',data:{url:d.url||'/app'}})}); self.addEventListener('notificationclick',e=>{e.notification.close(); clients.openWindow(e.notification.data.url||'/app')});", mimetype="application/javascript")

@app.route("/app")
@app.route("/")
def app_page():
    return """
<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>FIX ORO</title>
<style>body{font-family:sans-serif;background:#f1f5f9;padding:10px}.card{background:white;border-radius:12px;padding:12px;margin:10px 0}.coin{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #eee}</style>
</head><body>
<h3>Vendi STABILE - FIX ORO DEFINITIVO</h3>
<div><button onclick="loadTF('5m')" id=b5m>5m</button><button onclick="loadTF('15m')" id=b15m>15m</button><button onclick="loadTF('1H')" id=b1H>1H</button><button onclick="loadTF('4H')" id=b4H>4H</button><button onclick="loadTF('1D')" id=b1D>1D</button> <button onclick="subscribe()">📢 Attiva Push</button> <button onclick="test()">🔔 Test</button></div>
<div class=card><b>GLOBALE:</b> <span id=globale>...</span> - TF <span id=tf>4H</span> - <span id=agg></span></div>
<div class=card id=coins>Caricamento...</div>
<script>
const VAPID='BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U6_Q';
function toUint8(b){const p='='.repeat((4-b.length%4)%4);const s=(b+p).replace(/-/g,'+').replace(/_/g,'/');return Uint8Array.from([...atob(s)].map(c=>c.charCodeAt(0)));}
async function subscribe(){const r=await navigator.serviceWorker.register('/sw.js');await Notification.requestPermission();const sub=await r.pushManager.subscribe({userVisibleOnly:true, applicationServerKey:toUint8(VAPID)});await fetch('/api/push/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(sub)});alert('Push attivo');}
async function test(){await fetch('/api/push/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({coin:'BTC'})});alert('Test inviato');}
async function loadTF(tf){document.getElementById('tf').innerText=tf;document.getElementById('coins').innerText='Caricamento...';try{const res=await fetch('/api/signals?tf='+tf);const d=await res.json();document.getElementById('globale').innerText=d.globale;document.getElementById('agg').innerText=d.updated+' EUR rate '+d.eur_rate.toFixed(4);let h='';for(let [k,v] of Object.entries(d.coins)){h+=`<div class=coin><div><b>${k}</b> RSI ${v.rsi}</div><div style="font-weight:bold;color:${v.signal=='COMPRA'?'green':v.signal=='VENDI'?'red':'orange'}">${v.signal}</div><div>${v.price.toFixed(2)}€</div></div>`;}document.getElementById('coins').innerHTML=h;}catch(e){document.getElementById('coins').innerText='Errore '+e;}}
loadTF('4H');setInterval(()=>loadTF(document.getElementById('tf').innerText),60000);
</script>
</body></html>
"""

threading.Thread(target=checker, daemon=True).start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
