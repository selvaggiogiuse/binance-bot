"""
FIX per errore 451 di Binance su Render
Cambia endpoint da api.binance.com -> data-api.binance.vision che non blocca
"""

import os
import json
import time
import threading
import requests
from datetime import datetime
from flask import Flask, request, jsonify, Response

try:
    from flask_cors import CORS
    HAS_CORS = True
except ImportError:
    HAS_CORS = False

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U6_Q")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:test@test.com")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SUBS_FILE = "subscriptions.json"
LAST_SIGNALS_FILE = "last_signals.json"

app = Flask(__name__)
if HAS_CORS:
    CORS(app)

def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except: pass
    return default

def save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except: pass

subscriptions = load_json(SUBS_FILE, [])
last_signals = load_json(LAST_SIGNALS_FILE, {})

SYMBOLS = {
    "BTC": "BTCEUR",
    "ETH": "ETHEUR",
    "ORO": "PAXGEUR",
    "PAXG": "PAXGEUR"
}

TF_MAP = {"5m":"5m","15m":"15m","1H":"1h","4H":"4h","1D":"1d"}

# ENDPOINTS FIX 451 - lista di fallback
BINANCE_BASES = [
    "https://data-api.binance.vision",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
]

def get_klines(symbol, interval, limit=100):
    headers = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for base in BINANCE_BASES:
        try:
            url = f"{base}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            r = requests.get(url, timeout=10, headers=headers)
            if r.status_code == 451:
                print(f"451 su {base} per {symbol}, provo prossimo")
                continue
            r.raise_for_status()
            data = r.json()
            closes = [float(c[4]) for c in data]
            if len(closes) > 0:
                # print(f"OK {symbol} {interval} da {base}")
                return closes
        except Exception as e:
            print(f"Klines error {symbol} {interval} su {base}: {e}")
            continue
    print(f"TUTTI GLI ENDPOINT FALLITI per {symbol} {interval}")
    return None

def calc_rsi(prices, period=14):
    if not prices or len(prices) < period + 1:
        return 50
    gains = 0
    losses = 0
    for i in range(1, period+1):
        diff = prices[-i] - prices[-i-1]
        if diff >=0: gains += diff
        else: losses -= diff
    if losses == 0:
        return 100 if gains>0 else 50
    rs = gains / losses if losses!=0 else 0
    return round(100 - (100/(1+rs)),2)

def get_signal_from_rsi(rsi):
    if rsi <= 30: return "COMPRA"
    if rsi >= 70: return "VENDI"
    return "FERMO"

def get_all_signals(tf="4H"):
    interval = TF_MAP.get(tf, "4h")
    results = {}
    globale = "FERMO"
    for name, binance_symbol in SYMBOLS.items():
        closes = get_klines(binance_symbol, interval)
        if closes is None:
            # fallback: prova con USDT se EUR bloccato
            if binance_symbol.endswith("EUR"):
                alt = binance_symbol.replace("EUR","USDT")
                closes = get_klines(alt, interval)
        if closes is None:
            results[name] = {"symbol": binance_symbol, "rsi": 0, "signal": "ERRORE", "price": 0}
            continue
        rsi = calc_rsi(closes)
        signal = get_signal_from_rsi(rsi)
        results[name] = {"symbol": binance_symbol, "rsi": rsi, "signal": signal, "price": closes[-1], "tf": tf}
        if signal in ["COMPRA","VENDI"]:
            globale = signal
    return {"coins": results, "globale": globale, "tf": tf, "updated": datetime.now().strftime("%H:%M:%S")}

def send_push_to_all(title, body, url="/app", coin="BTC", tf="4H", tag="signal"):
    if not subscriptions or not VAPID_PRIVATE_KEY:
        return 0
    try:
        from pywebpush import webpush
    except: return 0
    success=0
    payload=json.dumps({"title":"[SERVER] "+title,"body":body,"url":url+"?coin="+coin+"&tf="+tf,"coin":coin,"tf":tf,"tag":tag})
    for sub in subscriptions:
        try:
            webpush(subscription_info=sub, data=payload, vapid_private_key=VAPID_PRIVATE_KEY, vapid_claims={"sub":VAPID_SUBJECT})
            success+=1
        except: pass
    return success

def background_checker():
    print("Checker avviato - usando data-api.binance.vision per bypassare 451")
    while True:
        try:
            for tf in ["5m","15m","1H","4H","1D"]:
                data=get_all_signals(tf)
                for coin_name, info in data["coins"].items():
                    key=f"{coin_name}_{tf}"
                    new_sig=info["signal"]
                    old_sig=last_signals.get(key,"FERMO")
                    if new_sig in ["COMPRA","VENDI"] and new_sig!=old_sig:
                        send_push_to_all(f"{coin_name}: {new_sig} {tf}", f"RSI {info['rsi']} - {info['price']:.2f} - TF {tf}", coin=coin_name, tf=tf, tag=key)
                    last_signals[key]=new_sig
                save_json(LAST_SIGNALS_FILE, last_signals)
                time.sleep(1)
            print(f"[{datetime.now()}] Check OK")
            time.sleep(60)
        except Exception as e:
            print(f"Errore loop: {e}")
            time.sleep(30)

@app.route("/api/ping")
def ping(): return jsonify({"ok":True,"time":datetime.now().isoformat(),"subs":len(subscriptions)})

@app.route("/api/signals")
def signals():
    tf=request.args.get("tf","4H")
    try:
        data=get_all_signals(tf)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error":str(e),"coins":{},"globale":"ERRORE"}),500

@app.route("/api/status")
def status(): return jsonify({"subs":len(subscriptions),"last":last_signals})

@app.route("/api/push/subscribe", methods=["POST"])
def subscribe():
    sub=request.get_json()
    if sub and sub not in subscriptions:
        subscriptions.append(sub); save_json(SUBS_FILE, subscriptions)
    return jsonify({"ok":True})

@app.route("/api/push/test", methods=["POST"])
def test_push():
    data=request.get_json(silent=True) or {}
    send_push_to_all(f"TEST {data.get('coin','BTC')} COMPRA","Prova PUSH SERVER - funziona anche ad app chiusa!", coin=data.get('coin','BTC'), tf=data.get('tf','4H'), tag="test")
    return jsonify({"ok":True,"sent_to":len(subscriptions)})

@app.route("/sw.js")
def sw():
    return Response("""
self.addEventListener('push', function(event) {
    let data={}; try{data=event.data.json();}catch(e){data={title:'Vendi', body:event.data.text()}}
    const title=data.title||'[SERVER] Segnale';
    const opt={body:data.body||'Nuovo segnale', icon:'https://cdn-icons-png.flaticon.com/512/138/138292.png', tag:data.tag||'sig', data:{url:data.url||'/app'}, requireInteraction:true};
    event.waitUntil(self.registration.showNotification(title, opt));
});
self.addEventListener('notificationclick', function(e){e.notification.close(); const url=e.notification.data.url||'/app'; e.waitUntil(clients.openWindow(url));});
""", mimetype="application/javascript")

@app.route("/app")
@app.route("/")
def app_page():
    html="""
<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vendi PUSH VERO 451 FIX</title>
<style>body{font-family:sans-serif;background:#f1f5f9;margin:0;padding:0 12px}.header{background:white;border-radius:16px;padding:12px;margin:12px 0;display:flex;justify-content:space-between}.badge{background:#6366f1;color:white;width:48px;height:48px;border-radius:14px;display:flex;align-items:center;justify-content:center;font-weight:bold}.tfs button{border:1px solid #ddd;background:white;padding:8px 14px;border-radius:20px;margin:3px}.tfs button.active{background:#0f172a;color:white}.card{background:white;border-radius:16px;padding:14px;margin:10px 0}.globale.FERMO{color:#f59e0b}.globale.COMPRA{color:#22c55e}.globale.VENDI{color:#ef4444}.coin{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #eee}</style>
</head><body>
<div class="header"><div style="display:flex;gap:10px;align-items:center"><div class="badge">VE</div><div><b>Vendi STABILE PUSH</b><br><small>FIX 451 - data-api.binance.vision</small><br><small id="subStatus">Push: verifica...</small></div></div><div><button onclick="testPush()">🔔</button><button onclick="subscribePush()">📢</button></div></div>
<div class="tfs"><button onclick="loadTF('5m')" id="b5m">5m</button><button onclick="loadTF('15m')" id="b15m">15m</button><button onclick="loadTF('1H')" id="b1H">1H</button><button onclick="loadTF('4H')" id="b4H" class="active">4H</button><button onclick="loadTF('1D')" id="b1D">1D</button></div>
<div class="card"><div style="display:flex;justify-content:space-between"><div><small>GLOBALE</small><div id="globale" class="globale FERMO" style="font-size:22px;font-weight:bold">...</div></div><div><small>TF</small><div id="tfLabel" style="font-size:20px;font-weight:bold">4H</div></div></div></div>
<div class="card" id="coins">Caricamento...</div>
<div style="text-align:center;color:#888;font-size:12px" id="agg"></div>
<div style="margin:20px 0;text-align:center"><button onclick="testPush()" style="background:#0f172a;color:white;padding:12px 20px;border-radius:10px;border:none">TEST PUSH SERVER</button></div>
<script>
let curTF='4H'; const VAPID_PUBLIC='BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U6_Q';
function urlBase64ToUint8Array(b){const p='='.repeat((4-b.length%4)%4);const base64=(b+p).replace(/-/g,'+').replace(/_/g,'/');const raw=window.atob(base64);return Uint8Array.from([...raw].map(c=>c.charCodeAt(0)));}
async function subscribePush(){try{const reg=await navigator.serviceWorker.register('/sw.js');await Notification.requestPermission();const sub=await reg.pushManager.subscribe({userVisibleOnly:true, applicationServerKey:urlBase64ToUint8Array(VAPID_PUBLIC)});await fetch('/api/push/subscribe',{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(sub)});document.getElementById('subStatus').innerText='Push: ATTIVO [SERVER]';alert('Push attivato!');}catch(e){alert('Errore: '+e)}}
async function testPush(){const r=await fetch('/api/push/test',{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({coin:'BTC', tf:curTF})});const j=await r.json();alert('Test inviato a '+j.sent_to);}
async function loadTF(tf){curTF=tf;document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active'));document.getElementById('b'+tf).classList.add('active');document.getElementById('tfLabel').innerText=tf;document.getElementById('coins').innerHTML='Caricamento...';try{const res=await fetch('/api/signals?tf='+tf);const data=await res.json();document.getElementById('globale').innerText=data.globale;document.getElementById('globale').className='globale '+data.globale;let html='';for(let [name, info] of Object.entries(data.coins)){let color=info.signal==='COMPRA'?'#22c55e':info.signal==='VENDI'?'#ef4444':'#f59e0b';html+='<div class="coin"><div><b>'+name+'</b> <small>RSI '+info.rsi+'</small></div><div style="color:'+color+';font-weight:bold">'+info.signal+'</div><div>'+(info.price?info.price.toFixed(2):'--')+'€</div></div>';}document.getElementById('coins').innerHTML=html||'Nessun dato';document.getElementById('agg').innerText='Agg: '+data.updated;}catch(e){document.getElementById('coins').innerHTML='Errore: '+e;}}
(async()=>{if('serviceWorker' in navigator){try{await navigator.serviceWorker.register('/sw.js');}catch{}}loadTF('4H');setInterval(()=>loadTF(curTF),60000);})();
</script></body></html>
"""
    return html

threading.Thread(target=background_checker, daemon=True).start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
