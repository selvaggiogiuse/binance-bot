import os
import time
import threading
import requests
from flask import Flask, Response
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

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
    log_msg("Bot KRAKEN v5.5 NO-SKIP partito - invia tutto")
    send_telegram("Bot KRAKEN v5.5 partito - ora mando TUTTI i messaggi anche VOL BASSO")
    while True:
        try:
            for s in SYMBOLS:
                try:
                    price, change = get_price_info(s)
                    v1, a1, l1 = get_volume_info(s, 1, 20)
                    v5, a5, l5 = get_volume_info(s, 5, 20)
                    log_line = f"AGG 1m - {s}: {price:.2f} ({change:+.2f}%) | {l1} ({v1:.1f} vs {a1:.1f})"
                    log_msg(log_line)
                    now = datetime.now().strftime("%H:%M:%S")
                    msg = "AGG 1m - " + now + "\n" + s + f": {price:.2f} ({change:+.2f}%)\n1m: {l1} ({v1:.1f} vs {a1:.1f})\n5m: {l5} ({v5:.1f} vs {a5:.1f}"
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
        return "Bot riavviato - <a href='/app'>Vai alla APP</a>", 200
    return f"Bot vivo - {len(LOGS)} log - <a href='/app'>Vai alla APP</a>", 200

@app.route("/log")
def show_log():
    return "<br>".join(LOGS[-200:])

@app.route("/app")
def serve_app():
    html = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0a0e1a"><title>Crypto Vendi</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}body{background:#0a0e1a;color:#e2e8f0;font-family:system-ui;padding:16px;min-height:100vh}
.header{display:flex;align-items:center;gap:12px;margin-bottom:16px}
.logo{width:48px;height:48px;background:linear-gradient(135deg,#7c3aed,#3b82f6);border-radius:16px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:22px}
.card{background:#131a2e;border:1px solid #1e2a4a;border-radius:16px;padding:16px;margin-bottom:12px}
.price{font-size:28px;font-weight:800}.positive{color:#10b981}.negative{color:#ef4444}
.btn-install{background:#fff;color:#000;border:none;padding:10px 18px;border-radius:20px;font-weight:700;cursor:pointer}
.grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:12px 0}
.mini{font-size:11px;opacity:.6}.mini b{font-size:13px;opacity:1;display:block;color:#fff}
</style>
</head>
<body>
<div class="header"><div class="logo">V</div><div style="flex:1"><div style="font-weight:800">Vendite di criptovalute</div><div style="font-size:12px;opacity:.6">BTCEUR • ETHEUR • SOLEUR • LIVE</div></div><button class="btn-install" id="installBtn">⬇️ Installa</button></div>
<div class="card" style="display:flex;align-items:center;gap:12px"><div style="width:48px;height:48px;background:#1e293b;border-radius:50%;display:flex;align-items:center;justify-content:center">📈</div><div><div style="font-size:12px;letter-spacing:2px;opacity:.6">GLOBALE</div><div id="globale" style="font-size:20px;font-weight:800;color:#fbbf24">CARICAMENTO...</div></div></div>
<div class="grid"><div class="card"><div class="mini">⚡ RSI</div><b>14 periodici</b></div><div class="card"><div class="mini">📈 TENDENZA</div><b>EMA 20/50</b></div><div class="card"><div class="mini">🛡️ FONTE</div><b>Binance</b></div></div>
<div id="coins"></div><div style="text-align:center;margin-top:12px;font-size:11px;opacity:.5" id="upd">Aggiornato: --:--</div>
<script>
let deferredPrompt=null;
window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();deferredPrompt=e;document.getElementById('installBtn').style.display='block';});
document.getElementById('installBtn').onclick=async()=>{
 if(deferredPrompt){deferredPrompt.prompt();await deferredPrompt.userChoice;deferredPrompt=null;}
 else{alert('Perfetto! Per installare: Menu Chrome ⋮ in alto a destra -> Installa e crea scorciatoia');}
};
const SYMBOLS=['BTCEUR','ETHEUR','SOLEUR'];
function calcRSI(prices,period=14){
 if(prices.length<period+1)return 50;
 let gains=0,losses=0;
 for(let i=1;i<=period;i++){let d=prices[i]-prices[i-1];if(d>=0)gains+=d;else losses-=d;}
 let avgG=gains/period,avgL=losses/period;
 if(avgL==0)return 70;
 for(let i=period+1;i<prices.length;i++){let d=prices[i]-prices[i-1];let g=d>0?d:0;let l=d<0?-d:0;avgG=(avgG*(period-1)+g)/period;avgL=(avgL*(period-1)+l)/period;}
 let rs=avgG/avgL;return 100-100/(1+rs);
}
function calcEMA(prices,period){let k=2/(period+1);let ema=prices[0];for(let i=1;i<prices.length;i++)ema=prices[i]*k+ema*(1-k);return ema;}
async function fetchKlines(sym,interval,limit){
 try{let r=await fetch(`https://api.binance.com/api/v3/klines?symbol=${sym}&interval=${interval}&limit=${limit}`);if(!r.ok)throw 0;return await r.json();}
 catch{try{let r=await fetch(`https://data-api.binance.vision/api/v3/klines?symbol=${sym}&interval=${interval}&limit=${limit}`);return await r.json();}catch{return [];}}
}
async function loadCoin(sym){
 try{
  let kl1h=await fetchKlines(sym,'1h',60);
  if(!kl1h.length)return null;
  let closes=kl1h.map(c=>parseFloat(c[4]));
  let price=closes[closes.length-1];
  let open=closes[0];
  let change=((price-open)/open*100);
  let rsi=calcRSI(closes,14);
  let ema20=calcEMA(closes,20);
  let ema50=calcEMA(closes,50);
  let trend=ema20>ema50?'Rialzista':'Ribassista';
  let stato='FERMO';let col='#fbbf24';
  if(rsi>70){stato='VENDI';col='#ef4444';}
  else if(rsi<30){stato='COMPRA';col='#10b981';}
  else if(ema20>ema50 && rsi>55){stato='COMPRA';col='#10b981';}
  else if(ema20<ema50 && rsi<45){stato='VENDI';col='#ef4444';}
  return {sym,price,change,rsi,ema20,ema50,trend,stato,col};
 }catch(e){return null;}
}
async function refresh(){
 let html='';let segnali=[];
 for(let sym of SYMBOLS){
  let d=await loadCoin(sym);if(!d)continue;
  segnali.push(d.stato);
  let name=sym.replace('EUR','');
  html+=`<div class="card"><div style="display:flex;justify-content:space-between;align-items:center"><div style="display:flex;gap:10px;align-items:center"><div style="width:44px;height:44px;background:#1e293b;border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:800">${name[0]}</div><div><div style="font-weight:800">${sym}</div><div style="font-size:12px;opacity:0.6">${name}</div></div></div><div style="background:${d.col};color:${d.col=='#fbbf24'?'#000':'#fff'};padding:6px 14px;border-radius:20px;font-weight:800;font-size:13px">${d.stato}</div></div><div class="price" style="margin:12px 0">€${d.price.toLocaleString('it-IT',{minimumFractionDigits:2,maximumFractionDigits:2})} <span style="font-size:14px" class="${d.change>=0?'positive':'negative'}">${d.change>=0?'+':''}${d.change.toFixed(2)}%</span></div><div style="display:flex;gap:8px"><div class="card" style="flex:1;margin:0"><div class="mini">RSI 14</div><b>${d.rsi.toFixed(1)}</b></div><div class="card" style="flex:1;margin:0"><div class="mini">TENDENZA</div><b style="color:${d.trend=='Rialzista'?'#10b981':'#ef4444'}">${d.trend}</b><div style="font-size:11px;opacity:0.6">EMA20 €${d.ema20.toFixed(0)}<br>EMA50 €${d.ema50.toFixed(0)}</div></div></div></div>`;
 }
 document.getElementById('coins').innerHTML=html;
 let comp=segnali.filter(s=>s=='COMPRA').length;let vend=segnali.filter(s=>s=='VENDI').length;
 let glob=document.getElementById('globale');
 if(comp>=2){glob.textContent='MERCATO COMPRA';glob.style.color='#10b981';}
 else if(vend>=2){glob.textContent='MERCATO VENDI';glob.style.color='#ef4444';}
 else{glob.textContent='MERCATO FERMO';glob.style.color='#fbbf24';}
 document.getElementById('upd').textContent='Aggiornato: '+new Date().toLocaleTimeString('it-IT');
}
refresh();setInterval(refresh,60000);
</script>
</body>
</html>
"""
    return Response(html, mimetype="text/html")

bot_thread = threading.Thread(target=loop_bot, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
