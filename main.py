from flask import Flask, jsonify, Response
import os, random
from datetime import datetime

app = Flask(__name__)

def fake_data(tf):
    now = datetime.now().strftime("%H:%M:%S")
    return {
        "coins": {
            "BTC": {"symbol":"BTCUSDT","price":65432.12,"rsi":62.5,"signal":"FERMO","conf":68,"trend":"Rialzista","tf":tf,"ema50":64800,"ema200":63200,"bb_up":66500,"bb_low":64300,"macd":5.2,"macd_signal":3.1,"vol_ratio":1.2,"adx":22,"atr":320,"sl":65000,"tp":66200,"reasons":["SBLOCCATO OK","EMA rialzista"],"bullish":62,"bearish":38},
            "ETH": {"symbol":"ETHUSDT","price":2520.5,"rsi":58.1,"signal":"COMPRA","conf":72,"trend":"Rialzista","tf":tf,"ema50":2480,"ema200":2400,"bb_up":2600,"bb_low":2440,"macd":2.1,"macd_signal":1.5,"vol_ratio":1.4,"adx":24,"atr":35,"sl":2490,"tp":2590,"reasons":["RSI basso","BB low"],"bullish":72,"bearish":28},
            "ORO": {"symbol":"PAXGUSDT","price":3765.8,"rsi":73.2,"signal":"VENDI","conf":78,"trend":"Ribassista","tf":tf,"ema50":3780,"ema200":3800,"bb_up":3790,"bb_low":3740,"macd":-1.2,"macd_signal":-0.5,"vol_ratio":0.9,"adx":26,"atr":12,"sl":3780,"tp":3740,"reasons":["RSI alto 73","BB high"],"bullish":30,"bearish":78}
        },
        "globale": "COMPRA",
        "tf": tf,
        "updated": now,
        "source": "STATICO SBLOCCATO - SE VEDI QUESTO IL DEPLOY FUNZIONA"
    }

@app.route("/api/ping")
def ping():
    return jsonify({"ok": True, "msg": "FINALE STATICO V3 - DEPLOY OK", "time": datetime.now().isoformat()})

@app.route("/api/signals")
def sig():
    tf = __import__('flask').request.args.get("tf","4H")
    return jsonify(fake_data(tf))

@app.route("/api/history")
def hist():
    return jsonify([
        {"coin":"BTC","tf":"4H","signal":"VENDI","conf":72,"rsi":71,"price":65200,"time":"Oggi 06:04","adx":24,"reasons":["RSI alto"]},
        {"coin":"ETH","tf":"15m","signal":"COMPRA","conf":68,"rsi":28,"price":2510,"time":"Oggi 05:40","adx":22,"reasons":["RSI basso"]}
    ])

@app.route("/api/push/subscribe", methods=["POST"])
def sub(): return jsonify({"ok":True,"total":1})
@app.route("/api/push/test", methods=["POST"])
def testp(): return jsonify({"ok":True,"sent_to":1,"subs":1})
@app.route("/sw.js")
def sw(): return Response("self.addEventListener('push',e=>{self.registration.showNotification('TEST')})", mimetype="application/javascript")

@app.route("/")
@app.route("/app")
def app_page():
    return """
<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>FINALE SBLOCCATO</title>
<style>body{font-family:sans-serif;background:#f8fafc;padding:12px} .card{background:white;border-radius:16px;padding:16px;box-shadow:0 4px 20px rgba(0,0,0,.05);margin-bottom:12px} .ok{background:#10b981;color:white;padding:16px;border-radius:16px;font-weight:800;margin-bottom:12px} .coin{display:flex;justify-content:space-between;padding:12px;border-bottom:1px solid #f1f5f9} .badge{padding:4px 8px;border-radius:99px;font-weight:800;font-size:12px} .COMPRA{background:#dcfce7;color:#166534} .VENDI{background:#fee2e2;color:#991b1b} .FERMO{background:#fef3c7;color:#92400e}</style>
</head><body>
<div class="ok">✅ FINALE STATICO V3 - SE VEDI QUESTO IL DEPLOY È OK - ORA CLICCA SOTTO</div>
<div class="card" id="status">Caricamento API...</div>
<div class="card" id="coins">Caricamento monete...</div>
<script>
fetch('/api/ping').then(r=>r.json()).then(d=>{
  document.getElementById('status').innerHTML='<b>PING:</b> '+JSON.stringify(d)+'<br><br>Se vedi FINALE STATICO V3, il deploy funziona. Sotto devono apparire le 3 monete.';
}).catch(e=>{document.getElementById('status').innerHTML='ERRORE PING: '+e+'<br>Render non ha aggiornato il codice. Controlla i Logs su render.com';});

fetch('/api/signals?tf=4H').then(r=>r.json()).then(d=>{
  let h='';
  for(let [k,v] of Object.entries(d.coins)){
    h+=`<div class="coin"><div><b>${k}</b> $${v.price} - RSI ${v.rsi}</div><div><span class="badge ${v.signal}">${v.signal} ${v.conf}%</span></div></div>`;
  }
  h+=`<br><small>Globale: ${d.globale} - Aggiornato: ${d.updated} - ${d.source}</small>`;
  document.getElementById('coins').innerHTML=h;
}).catch(e=>{document.getElementById('coins').innerHTML='ERRORE SIGNALS: '+e;});
</script>
</body></html>
"""

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
