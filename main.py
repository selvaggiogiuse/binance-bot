"""
Vendi STABILE - PUSH VERO DEFINITIVO - FIXED per Render
Corretto errore f-string alla riga 425
"""

import os
import json
import time
import threading
import requests
from datetime import datetime
from flask import Flask, request, jsonify, Response
from flask_cors import CORS

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U6_Q")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:test@test.com")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SUBS_FILE = "subscriptions.json"
LAST_SIGNALS_FILE = "last_signals.json"

app = Flask(__name__)
CORS(app)

def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except:
        pass
    return default

def save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Save error {path}: {e}")

subscriptions = load_json(SUBS_FILE, [])
last_signals = load_json(LAST_SIGNALS_FILE, {})

SYMBOLS = {
    "BTC": "BTCEUR",
    "ETH": "ETHEUR",
    "ORO": "PAXGEUR",
    "PAXG": "PAXGEUR"
}

TF_MAP = {
    "5m": "5m",
    "15m": "15m",
    "1H": "1h",
    "4H": "4h",
    "1D": "1d"
}

def get_klines(symbol, interval, limit=100):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        data = r.json()
        closes = [float(c[4]) for c in data]
        return closes
    except Exception as e:
        print(f"Klines error {symbol} {interval}: {e}")
        return None

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    gains = 0
    losses = 0
    for i in range(1, period+1):
        diff = prices[-i] - prices[-i-1]
        if diff >=0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100 if gains>0 else 50
    rs = gains / losses if losses!=0 else 0
    rsi = 100 - (100/(1+rs))
    return round(rsi,2)

def get_signal_from_rsi(rsi):
    if rsi <= 30:
        return "COMPRA"
    if rsi >= 70:
        return "VENDI"
    return "FERMO"

def get_all_signals(tf="4H"):
    interval = TF_MAP.get(tf, "4h")
    results = {}
    globale = "FERMO"
    for name, binance_symbol in SYMBOLS.items():
        closes = get_klines(binance_symbol, interval)
        if closes is None:
            results[name] = {"symbol": binance_symbol, "rsi": 0, "signal": "ERRORE", "price": 0}
            continue
        rsi = calc_rsi(closes)
        signal = get_signal_from_rsi(rsi)
        results[name] = {
            "symbol": binance_symbol,
            "rsi": rsi,
            "signal": signal,
            "price": closes[-1],
            "tf": tf
        }
        if signal in ["COMPRA","VENDI"]:
            globale = signal
    return {"coins": results, "globale": globale, "tf": tf, "updated": datetime.now().strftime("%H:%M:%S")}

def send_push_to_all(title, body, url="/app", coin="BTC", tf="4H", tag="signal"):
    if not subscriptions:
        print("Nessun abbonato push")
        return 0
    if not VAPID_PRIVATE_KEY:
        print("VAPID_PRIVATE_KEY mancante! Setta env var")
        return 0
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        print("pywebpush non installato")
        return 0
    
    success = 0
    to_remove = []
    payload = json.dumps({
        "title": "[SERVER] " + title,
        "body": body,
        "url": url + "?coin=" + coin + "&tf=" + tf,
        "coin": coin,
        "tf": tf,
        "icon": "https://cdn-icons-png.flaticon.com/512/138/138292.png",
        "tag": tag
    })
    
    for sub in subscriptions:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT}
            )
            success +=1
        except Exception as ex:
            print(f"Push fallita: {ex}")
            # se 404/410 rimuovi
            try:
                if hasattr(ex, 'response') and ex.response and ex.response.status_code in [404,410]:
                    to_remove.append(sub)
            except:
                pass
    
    if to_remove:
        for r in to_remove:
            if r in subscriptions:
                subscriptions.remove(r)
        save_json(SUBS_FILE, subscriptions)
    
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            tg_text = f"{title}\n{body}\n{url}?coin={coin}&tf={tf}"
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                          json={"chat_id": TELEGRAM_CHAT_ID, "text": tg_text}, timeout=5)
        except Exception as e:
            print(f"Telegram error: {e}")
    
    print(f"Push inviate: {success}/{len(subscriptions)}")
    return success

def background_checker():
    print("Background checker PUSH VERO avviato")
    while True:
        try:
            for tf in ["5m","15m","1H","4H","1D"]:
                data = get_all_signals(tf)
                for coin_name, info in data["coins"].items():
                    key = f"{coin_name}_{tf}"
                    new_sig = info["signal"]
                    old_sig = last_signals.get(key, "FERMO")
                    if new_sig in ["COMPRA","VENDI"] and new_sig != old_sig:
                        title = f"{coin_name}: {new_sig} {tf}"
                        body = f"RSI {info['rsi']} - Prezzo {info['price']:.2f} - TF {tf}"
                        print(f"NUOVO SEGNALE {key}: {old_sig} -> {new_sig}")
                        send_push_to_all(title, body, coin=coin_name, tf=tf, tag=key)
                    last_signals[key] = new_sig
                save_json(LAST_SIGNALS_FILE, last_signals)
                time.sleep(2)
            print(f"[{datetime.now()}] Check completato, dormo 60s")
            time.sleep(60)
        except Exception as e:
            print(f"Errore loop checker: {e}")
            time.sleep(30)

@app.route("/api/ping")
def ping():
    return jsonify({"ok": True, "time": datetime.now().isoformat(), "subs": len(subscriptions)})

@app.route("/api/signals")
def signals():
    tf = request.args.get("tf", "4H")
    try:
        data = get_all_signals(tf)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e), "coins": {}, "globale": "ERRORE"}), 500

@app.route("/api/status")
def status():
    return jsonify({
        "subscriptions": len(subscriptions),
        "last_signals": last_signals,
        "vapid_configured": bool(VAPID_PRIVATE_KEY),
        "telegram_configured": bool(TELEGRAM_TOKEN),
        "now": datetime.now().isoformat()
    })

@app.route("/api/push/subscribe", methods=["POST"])
def subscribe():
    sub = request.get_json()
    if not sub or "endpoint" not in sub:
        return jsonify({"error": "invalid sub"}), 400
    if sub not in subscriptions:
        subscriptions.append(sub)
        save_json(SUBS_FILE, subscriptions)
        print(f"Nuovo abbonato push")
    return jsonify({"ok": True, "count": len(subscriptions)})

@app.route("/api/push/test", methods=["POST"])
def test_push():
    data = request.get_json(silent=True) or {}
    coin = data.get("coin","BTC")
    tf = data.get("tf","4H")
    send_push_to_all(f"TEST {coin} COMPRA", f"Questa e' una prova PUSH VERO SERVER - TF {tf} - Se la vedi ad app chiusa, funziona!", coin=coin, tf=tf, tag="test")
    return jsonify({"ok": True, "sent_to": len(subscriptions)})

@app.route("/sw.js")
def sw():
    # Niente f-string qui, cosi niente errore di graffe
    js_code = """
const VAPID_PUBLIC = "PLACEHOLDER_VAPID_PUBLIC";
self.addEventListener('push', function(event) {
    let data = {};
    try { data = event.data.json(); } catch(e) { data = {title: 'Vendi STABILE', body: event.data.text()} }
    const title = data.title || 'Vendi STABILE [SERVER]';
    const options = {
        body: data.body || 'Nuovo segnale',
        icon: data.icon || 'https://cdn-icons-png.flaticon.com/512/138/138292.png',
        badge: 'https://cdn-icons-png.flaticon.com/512/138/138292.png',
        tag: data.tag || 'signal',
        data: { url: data.url || '/app' },
        actions: [
            {action: 'open', title: 'APRI APP'},
            {action: 'chart', title: 'VEDI GRAFICO'}
        ],
        requireInteraction: true,
        vibrate: [200, 100, 200]
    };
    event.waitUntil(self.registration.showNotification(title, options));
});
self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    const url = event.notification.data.url || '/app';
    event.waitUntil(
        clients.matchAll({type: 'window'}).then(windowClients => {
            for (let client of windowClients) {
                if (client.url.includes('/app') && 'focus' in client) {
                    client.navigate(url);
                    return client.focus();
                }
            }
            if (clients.openWindow) return clients.openWindow(url);
        })
    );
});
"""
    js_code = js_code.replace("PLACEHOLDER_VAPID_PUBLIC", VAPID_PUBLIC_KEY)
    return Response(js_code, mimetype="application/javascript")

@app.route("/app")
@app.route("/")
def app_page():
    html_template = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vendi STABILE PUSH VERO</title>
<style>
body{font-family:sans-serif;background:#f1f5f9;margin:0;padding:0 12px}
.header{background:white;border-radius:16px;padding:12px;margin:12px 0;display:flex;align-items:center;justify-content:space-between}
.badge{background:#6366f1;color:white;width:48px;height:48px;border-radius:14px;display:flex;align-items:center;justify-content:center;font-weight:bold}
.tfs button{border:1px solid #ddd;background:white;padding:8px 14px;border-radius:20px;margin:3px}
.tfs button.active{background:#0f172a;color:white}
.card{background:white;border-radius:16px;padding:14px;margin:10px 0}
.globale.FERMO{color:#f59e0b} .globale.COMPRA{color:#22c55e} .globale.VENDI{color:#ef4444}
.coin{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #eee}
</style>
</head>
<body>
<div class="header">
  <div style="display:flex;align-items:center;gap:10px">
    <div class="badge">VE</div>
    <div><b>Vendi STABILE PUSH</b><br><small>BTC - ETH - ORO | PUSH VERO | CLICK APRE APP</small><br><small id="subStatus">Push: verifica...</small></div>
  </div>
  <div>
    <button onclick="testPush()">🔔</button>
    <button onclick="subscribePush()">📢</button>
  </div>
</div>
<div class="tfs">
  <button onclick="loadTF('5m')" id="b5m">5m</button>
  <button onclick="loadTF('15m')" id="b15m">15m</button>
  <button onclick="loadTF('1H')" id="b1H">1H</button>
  <button onclick="loadTF('4H')" id="b4H" class="active">4H</button>
  <button onclick="loadTF('1D')" id="b1D">1D</button>
</div>
<div class="card">
  <div style="display:flex;justify-content:space-between"><div><small>GLOBALE</small><div id="globale" class="globale FERMO" style="font-size:22px;font-weight:bold">FERMO</div><small id="globaleSub">Laterale</small></div><div><small>TF</small><div id="tfLabel" style="font-size:20px;font-weight:bold">4H</div></div></div>
</div>
<div class="card" id="coins">Caricamento...</div>
<div style="text-align:center;color:#888;font-size:12px" id="agg"></div>
<div style="margin:20px 0;text-align:center">
  <button onclick="testPush()" style="background:#0f172a;color:white;padding:12px 20px;border-radius:10px;border:none">TEST PUSH SERVER</button>
  <p style="font-size:11px;color:#666">Se ti arriva a app chiusa, il PUSH VERO funziona. Se arriva solo ad app aperta, e' locale.</p>
</div>
<script>
let curTF='4H';
const VAPID_PUBLIC='VAPID_PUBLIC_PLACEHOLDER';

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map(c=>c.charCodeAt(0)));
}

async function subscribePush() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) { alert('Push non supportato'); return; }
  try {
    const reg = await navigator.serviceWorker.register('/sw.js');
    await Notification.requestPermission();
    if (Notification.permission!=='granted') { alert('Permesso notifiche negato'); return; }
    const sub = await reg.pushManager.subscribe({userVisibleOnly:true, applicationServerKey:urlBase64ToUint8Array(VAPID_PUBLIC)});
    await fetch('/api/push/subscribe', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(sub)});
    document.getElementById('subStatus').innerText='Push: ATTIVO [SERVER]';
    alert('Push SERVER attivato! Ora ricevi anche ad app chiusa.');
  } catch(e) { alert('Errore push: '+e); console.error(e); }
}

async function testPush() {
  try {
    const r = await fetch('/api/push/test', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({coin:'BTC', tf:curTF})});
    const j = await r.json();
    alert('Test inviato a '+j.sent_to+' dispositivi. Chiudi l app e aspetta 5 sec.');
  } catch(e) { alert('Errore test: '+e)}
}

async function loadTF(tf) {
  curTF=tf;
  document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active'));
  document.getElementById('b'+tf).classList.add('active');
  document.getElementById('tfLabel').innerText=tf;
  document.getElementById('coins').innerHTML='Caricamento...';
  try {
    const controller = new AbortController();
    const timeout = setTimeout(()=>controller.abort(), 10000);
    const res = await fetch('/api/signals?tf='+tf, {signal:controller.signal});
    clearTimeout(timeout);
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    document.getElementById('globale').innerText=data.globale;
    document.getElementById('globale').className='globale '+data.globale;
    document.getElementById('globaleSub').innerText=data.globale==='FERMO'?'Laterale':data.globale;
    let html='';
    for (let [name, info] of Object.entries(data.coins)) {
      let color = info.signal==='COMPRA'?'#22c55e':info.signal==='VENDI'?'#ef4444':'#f59e0b';
      html+= '<div class="coin"><div><b>'+name+'</b> <small>'+info.symbol+' RSI '+info.rsi+'</small></div><div style="font-weight:bold;color:'+color+'">'+info.signal+'</div><div>'+info.price.toFixed(2)+'€</div></div>';
    }
    document.getElementById('coins').innerHTML=html||'Nessun dato';
    document.getElementById('agg').innerText='Agg: '+data.updated+' - TF:'+tf+' - PUSH VERO [SERVER]';
  } catch(e) {
    document.getElementById('coins').innerHTML='Errore caricamento: '+e+'<br><small>Render si e svegliato, riprova tra 10 sec</small>';
  }
}

(async()=>{
  if ('serviceWorker' in navigator) {
    try { await navigator.serviceWorker.register('/sw.js'); } catch(e) {}
  }
  loadTF('4H');
  setInterval(()=>loadTF(curTF), 60000);
})();
</script>
</body>
</html>
"""
    html_final = html_template.replace("VAPID_PUBLIC_PLACEHOLDER", VAPID_PUBLIC_KEY)
    return html_final

threading.Thread(target=background_checker, daemon=True).start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
