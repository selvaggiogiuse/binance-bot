from flask import Flask, jsonify, Response
app=Flask(__name__)

@app.route("/api/ping")
def ping():
    return jsonify({"ok":True,"msg":"TEST MINIMO FUNZIONA"})

@app.route("/api/signals")
def sig():
    return jsonify({
        "coins":{
            "BTC":{"symbol":"BTCUSDT","price":65432.12,"rsi":62.5,"signal":"FERMO","conf":68,"trend":"Rialzista","tf":"4H","ema50":64800,"ema200":63200,"bb_up":66500,"bb_low":64300,"macd":5.2,"macd_signal":3.1,"vol_ratio":1.2,"adx":22,"atr":320,"sl":65000,"tp":66200,"reasons":["TEST OK - EMA rialzista","MACD ↑"],"bullish":62,"bearish":38},
            "ETH":{"symbol":"ETHUSDT","price":2520.5,"rsi":58.1,"signal":"COMPRA","conf":72,"trend":"Rialzista","tf":"4H","ema50":2480,"ema200":2400,"bb_up":2600,"bb_low":2440,"macd":2.1,"macd_signal":1.5,"vol_ratio":1.4,"adx":24,"atr":35,"sl":2490,"tp":2590,"reasons":["RSI basso","BB low"],"bullish":72,"bearish":28},
            "ORO":{"symbol":"PAXGUSDT","price":3765.8,"rsi":73.2,"signal":"VENDI","conf":78,"trend":"Ribassista","tf":"4H","ema50":3780,"ema200":3800,"bb_up":3790,"bb_low":3740,"macd":-1.2,"macd_signal":-0.5,"vol_ratio":0.9,"adx":26,"atr":12,"sl":3780,"tp":3740,"reasons":["RSI alto 73","BB high"],"bullish":30,"bearish":78}
        },
        "globale":"VENDI",
        "tf":"4H",
        "updated":"TEST OK",
        "source":"TEST MINIMO - NO BINANCE"
    })

@app.route("/api/history")
def hist():
    return jsonify([
        {"coin":"BTC","tf":"4H","signal":"VENDI","conf":72,"rsi":71,"price":65200,"time":"Oggi 06:04","adx":24},
        {"coin":"ETH","tf":"15m","signal":"COMPRA","conf":68,"rsi":28,"price":2510,"time":"Oggi 05:40","adx":22}
    ])

@app.route("/api/push/subscribe", methods=["POST"])
def sub(): return jsonify({"ok":True,"total":1})
@app.route("/api/push/test", methods=["POST"])
def testp(): return jsonify({"ok":True,"sent_to":1,"subs":1})
@app.route("/sw.js")
def sw(): return Response("self.addEventListener('push',e=>{self.registration.showNotification('TEST',{body:'ok'})})", mimetype="application/javascript")

@app.route("/")
@app.route("/app")
def app_page():
    return """<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>TEST MINIMO</title></head><body style="font-family:sans-serif;padding:20px">
<h1 style="background:green;color:white;padding:16px;border-radius:12px">TEST MINIMO - SE VEDI QUESTO IL DEPLOY FUNZIONA</h1>
<div id="out">Caricamento...</div>
<script>
fetch('/api/signals?tf=4H').then(r=>r.json()).then(d=>{
  document.getElementById('out').innerHTML='<pre>'+JSON.stringify(d,null,2)+'</pre><h2>BTC $'+d.coins.BTC.price+'</h2><p>Se vedi questo, il problema era Binance 451, ora lo sistemo con Kraken</p>';
}).catch(e=>{document.getElementById('out').innerHTML='ERRORE FETCH: '+e});
</script>
</body></html>"""

if __name__=="__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
