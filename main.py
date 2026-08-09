"""
Vendi PRO V2 INSTANT - FIX BLOCCO DEFINITIVO
- /api/signals NON chiama Binance, risponde subito da cache RAM
- Checker in background aggiorna cache ogni 20s
- Se Binance 451, usa cache vecchia, non si blocca
"""
import os, json, time, threading, requests, math
from datetime import datetime
from flask import Flask, request, jsonify, Response
try:
    from flask_cors import CORS
    HAS_CORS=True
except: HAS_CORS=False

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "BHWs4iOkU3pKk6E46BXj3iL6jopscCgpcQcH6i8xDCYhbFUAT8pwvGxMGhl3v9T7TChtOVpaAF48t8cWFaWtimQ")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "wA-4RFSsnHB2oSSYQ_tELw9Mo6ljDaqpKVSnQH9EpF0")
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

SYMBOLS = {"BTC": "BTCUSDT","ETH": "ETHUSDT","ORO": "PAXGUSDT"}
TF_MAP={"5m":"5m","15m":"15m","1H":"1h","4H":"4h","1D":"1d"}
BINANCE_BASES=["https://data-api.binance.vision","https://api1.binance.com","https://api2.binance.com","https://api3.binance.com"]

# CACHE RAM ISTANTANEA
latest_data={} # tf -> data
latest_data_lock=threading.Lock()

def get_ohlcv_direct(symbol, interval, limit=200):
    headers={"User-Agent":"Mozilla/5.0"}
    for base in BINANCE_BASES:
        try:
            url=f"{base}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            r=requests.get(url, timeout=5, headers=headers)
            if r.status_code in (451,403,429): continue
            r.raise_for_status()
            data=r.json()
            return [{"open":float(c[1]),"high":float(c[2]),"low":float(c[3]),"close":float(c[4]),"volume":float(c[5])} for c in data]
        except: continue
    return None

def get_ticker_direct(symbol):
    for base in BINANCE_BASES:
        try:
            r=requests.get(f"{base}/api/v3/ticker/price?symbol={symbol}", timeout=3)
            if r.status_code in (451,403,429): continue
            return float(r.json()["price"])
        except: continue
    return None

def sma(arr,p):
    if len(arr)<p: return None
    return sum(arr[-p:])/p
def ema(arr,p):
    if len(arr)<p: return None
    k=2/(p+1)
    e=sma(arr[:p], p)
    for x in arr[p:]:
        e=x*k+e*(1-k)
    return e
def ema_series(arr,p):
    if len(arr)<p: return [None]*len(arr)
    k=2/(p+1)
    s=sma(arr[:p], p)
    vals=[None]*(p-1)+[s]
    e=s
    for x in arr[p:]:
        e=x*k+e*(1-k)
        vals.append(e)
    return vals
def calc_rsi(prices, period=14):
    if len(prices)<period+1: return 50
    gains=0; losses=0
    for i in range(1, period+1):
        d=prices[-i]-prices[-i-1]
        if d>0: gains+=d
        else: losses-=d
    if losses==0: return 95 if gains>0 else 50
    return round(100-(100/(1+gains/losses)),2)
def calc_bollinger(prices, period=20, mult=2):
    if len(prices)<period: return None,None,None
    m=sma(prices, period)
    import math
    std=math.sqrt(sum((x-m)**2 for x in prices[-period:])/period)
    return m+mult*std, m, m-mult*std
def calc_macd(prices):
    if len(prices)<35: return 0,0
    e12=ema(prices,12); e26=ema(prices,26)
    if e12 is None or e26 is None: return 0,0
    macd_line=e12-e26
    e12_s=ema_series(prices,12); e26_s=ema_series(prices,26)
    macd_series=[a-b if a is not None and b is not None else None for a,b in zip(e12_s, e26_s)]
    filt=[x for x in macd_series if x is not None]
    if len(filt)<9: return macd_line,0
    signal=ema(filt,9) or 0
    return macd_line, signal
def calc_atr(highs,lows,closes,p=14):
    if len(closes)<p+1: return closes[-1]*0.01
    trs=[]
    for i in range(1,len(closes)):
        hl=highs[i]-lows[i]; hc=abs(highs[i]-closes[i-1]); lc=abs(lows[i]-closes[i-1])
        trs.append(max(hl,hc,lc))
    return sma(trs,p) or trs[-1]
def calc_adx(highs,lows,closes,p=14):
    if len(closes)<p*2: return 15
    trs=[]; pdm=[]; mdm=[]
    for i in range(1,len(closes)):
        hl=highs[i]-lows[i]; hc=abs(highs[i]-closes[i-1]); lc=abs(lows[i]-closes[i-1])
        trs.append(max(hl,hc,lc))
        up=highs[i]-highs[i-1]; down=lows[i-1]-lows[i]
        pdm.append(up if up>0 and up>down else 0)
        mdm.append(down if down>0 and down>up else 0)
    def wilder(arr,p):
        if len(arr)<p: return None
        s=sum(arr[:p])
        for v in arr[p:]: s=s-s/p+v
        return s
    sm_tr=wilder(trs,p); sm_p=wilder(pdm,p); sm_m=wilder(mdm,p)
    if not sm_tr or sm_tr==0: return 15
    pdi=100*sm_p/sm_tr; mdi=100*sm_m/sm_tr
    dx=100*abs(pdi-mdi)/(pdi+mdi) if (pdi+mdi)!=0 else 0
    return max(5,min(60,dx))

def evaluate(ohlcv, price, higher=None, tf="4H"):
    closes=[c["close"] for c in ohlcv]; highs=[c["high"] for c in ohlcv]; lows=[c["low"] for c in ohlcv]; vols=[c["volume"] for c in ohlcv]
    rsi=calc_rsi(closes,14); e50=ema(closes,50) or closes[-1]; e200=ema(closes,200) or closes[-1]
    bb_up, bb_mid, bb_low=calc_bollinger(closes,20,2)
    macd_l, macd_s=calc_macd(closes)
    vol_sma=sma(vols,20) or vols[-1]; atr=calc_atr(highs,lows,closes,14); adx=calc_adx(highs,lows,closes,14)
    bull=0; bear=0; reasons=[]
    if rsi<=20: bull+=40; reasons.append(f"RSI ipervend {rsi}")
    elif rsi<=25: bull+=30; reasons.append(f"RSI basso {rsi}")
    elif rsi<=30: bull+=20; reasons.append(f"RSI {rsi}")
    elif rsi>=80: bear+=40; reasons.append(f"RSI ipercompr {rsi}")
    elif rsi>=75: bear+=30; reasons.append(f"RSI alto {rsi}")
    elif rsi>=70: bear+=20; reasons.append(f"RSI {rsi}")
    if price>e200 and e50>e200: bull+=25; reasons.append("EMA rialzista")
    elif price<e200 and e50<e200: bear+=25; reasons.append("EMA ribassista")
    elif price>e200: bull+=10
    elif price<e200: bear+=10
    if bb_low and price<=bb_low: bull+=15; reasons.append("BB low")
    elif bb_up and price>=bb_up: bear+=15; reasons.append("BB high")
    if macd_l>macd_s: bull+=10; reasons.append("MACD ↑")
    else: bear+=10; reasons.append("MACD ↓")
    vol_ratio=vols[-1]/vol_sma if vol_sma else 1
    if vol_ratio>1.3:
        if bull>bear: bull+=10; reasons.append(f"Vol +{int((vol_ratio-1)*100)}%")
        else: bear+=10; reasons.append(f"Vol +{int((vol_ratio-1)*100)}%")
    boost=1.0
    if adx<15: boost=0.7; reasons.append(f"Laterale ADX{adx:.0f}")
    elif adx>25: boost=1.2; reasons.append(f"Trend ADX{adx:.0f}")
    bull*=boost; bear*=boost
    if higher:
        hc=[c["close"] for c in higher]; he50=ema(hc,50) or hc[-1]; he200=ema(hc,200) or hc[-1]
        ht="bull" if hc[-1]>he200 and he50>he200 else "bear" if hc[-1]<he200 and he50<he200 else "neutral"
        if tf in ("5m","15m"):
            if bull>bear and ht=="bear": bull*=0.7; reasons.append("⚠️1H contro")
            if bear>bull and ht=="bull": bear*=0.7; reasons.append("⚠️1H contro")
            if bull>bear and ht=="bull": bull*=1.15; reasons.append("✅1H ok")
            if bear>bull and ht=="bear": bear*=1.15; reasons.append("✅1H ok")
    bull=min(95,int(bull)); bear=min(95,int(bear))
    if bull>bear and bull>=35: sig="COMPRA"; conf=bull; trend="Rialzista"
    elif bear>bull and bear>=35: sig="VENDI"; conf=bear; trend="Ribassista"
    else: sig="FERMO"; conf=max(bull,bear, int(50+abs(rsi-50))); trend="Laterale" if adx<20 else ("Rialz" if bull>bear else "Ribass")
    sl=tp=0
    if sig=="COMPRA": sl=price-atr*1.5; tp=price+atr*3
    elif sig=="VENDI": sl=price+atr*1.5; tp=price-atr*3
    return {"rsi":rsi,"ema50":e50,"ema200":e200,"bb_up":bb_up,"bb_low":bb_low,"macd":macd_l,"macd_signal":macd_s,"vol_ratio":vol_ratio,"adx":adx,"atr":atr,"bullish":bull,"bearish":bear,"signal":sig,"conf":conf,"trend":trend,"reasons":reasons,"sl":sl,"tp":tp}

def compute_tf(tf):
    interval=TF_MAP.get(tf,"4h")
    higher_interval="1h" if tf in ("5m","15m") else "1d" if tf=="4H" else "4h" if tf=="1H" else None
    results={}; globale="FERMO"; maxc=0
    for name,sym in SYMBOLS.items():
        ohlcv=get_ohlcv_direct(sym, interval, 200)
        if not ohlcv:
            # prova cache vecchia
            with latest_data_lock:
                if tf in latest_data and name in latest_data[tf].get("coins",{}):
                    results[name]=latest_data[tf]["coins"][name]
                    continue
            results[name]={"symbol":sym,"price":0,"rsi":0,"signal":"OFFLINE","conf":0,"trend":"-","reasons":["Binance 451 - uso cache"],"bullish":0,"bearish":0,"adx":0,"vol_ratio":1,"ema50":0,"ema200":0,"bb_up":0,"bb_low":0,"macd":0,"macd_signal":0,"sl":0,"tp":0}
            continue
        price=get_ticker_direct(sym) or ohlcv[-1]["close"]
        higher=get_ohlcv_direct(sym, higher_interval, 200) if higher_interval else None
        ev=evaluate(ohlcv, price, higher, tf)
        results[name]={"symbol":sym,"price":price,"rsi":ev["rsi"],"signal":ev["signal"],"conf":ev["conf"],"trend":ev["trend"],"tf":tf,"ema50":ev["ema50"],"ema200":ev["ema200"],"bb_up":ev["bb_up"],"bb_low":ev["bb_low"],"macd":ev["macd"],"macd_signal":ev["macd_signal"],"vol_ratio":ev["vol_ratio"],"adx":ev["adx"],"atr":ev["atr"],"sl":ev["sl"],"tp":ev["tp"],"reasons":ev["reasons"],"bullish":ev["bullish"],"bearish":ev["bearish"]}
        if ev["signal"] in ("COMPRA","VENDI") and ev["conf"]>maxc:
            maxc=ev["conf"]; globale=ev["signal"]
    return {"coins":results,"globale":globale,"tf":tf,"updated":datetime.now().strftime("%H:%M:%S")}

def add_history(coin, tf, info):
    if info["conf"]<60: return
    if info["signal"] not in ("COMPRA","VENDI"): return
    now=datetime.now()
    if history:
        try:
            last=history[-1]
            lt=datetime.fromisoformat(last["timestamp"])
            if last["coin"]==coin and last["tf"]==tf and last["signal"]==info["signal"] and (now-lt).total_seconds()<900:
                return
        except: pass
    entry={"timestamp":now.isoformat(),"time":now.strftime("%d/%m %H:%M"),"coin":coin,"tf":tf,"signal":info["signal"],"conf":info["conf"],"rsi":info["rsi"],"price":info["price"],"trend":info["trend"],"adx":info.get("adx",0),"reasons":info.get("reasons",[])[:3]}
    history.append(entry)
    if len(history)>500: del history[0:len(history)-500]
    save_json(HISTORY_FILE, history)

def send_push(title, body, coin="BTC", tf="4H"):
    if not subscriptions or not VAPID_PRIVATE_KEY: return 0
    try:
        from pywebpush import webpush
    except: return 0
    payload=json.dumps({"title":"[SERVER] "+title,"body":body,"url":f"/app?coin={coin}&tf={tf}"})
    ok=0
    for sub in subscriptions:
        try:
            webpush(subscription_info=sub, data=payload, vapid_private_key=VAPID_PRIVATE_KEY, vapid_claims={"sub":VAPID_SUBJECT})
            ok+=1
        except: pass
    return ok

def background_updater():
    print("Background INSTANT avviato")
    # pre-popola con dati fake per far caricare subito l'app
    with latest_data_lock:
        for tf in ["5m","15m","1H","4H","1D"]:
            latest_data[tf]={"coins":{"BTC":{"symbol":"BTCUSDT","price":0,"rsi":0,"signal":"CARICAMENTO","conf":0,"trend":"...","reasons":["Avvio..."],"bullish":0,"bearish":0,"adx":0,"vol_ratio":1,"ema50":0,"ema200":0,"bb_up":0,"bb_low":0,"macd":0,"macd_signal":0,"sl":0,"tp":0},"ETH":{"symbol":"ETHUSDT","price":0,"rsi":0,"signal":"CARICAMENTO","conf":0,"trend":"...","reasons":[],"bullish":0,"bearish":0,"adx":0,"vol_ratio":1,"ema50":0,"ema200":0,"bb_up":0,"bb_low":0,"macd":0,"macd_signal":0,"sl":0,"tp":0},"ORO":{"symbol":"PAXGUSDT","price":0,"rsi":0,"signal":"CARICAMENTO","conf":0,"trend":"...","reasons":[],"bullish":0,"bearish":0,"adx":0,"vol_ratio":1,"ema50":0,"ema200":0,"bb_up":0,"bb_low":0,"macd":0,"macd_signal":0,"sl":0,"tp":0}},"globale":"CARICAMENTO","tf":tf,"updated":datetime.now().strftime("%H:%M:%S")}
    while True:
        try:
            for tf in ["5m","15m","1H","4H","1D"]:
                try:
                    data=compute_tf(tf)
                    with latest_data_lock:
                        latest_data[tf]=data
                    for cname, info in data["coins"].items():
                        key=f"{cname}_{tf}"
                        is_new = info["signal"]!=last_signals.get(key,"FERMO")
                        add_history(cname, tf, info)
                        if info["signal"] in ("COMPRA","VENDI") and info["conf"]>=60 and (is_new or tf in ("5m","15m")):
                            send_push(f"{cname} {tf}: {info['signal']} {info['conf']}%", f"${info['price']:.2f} RSI{info['rsi']} ADX{info['adx']:.0f}", coin=cname, tf=tf)
                        last_signals[key]=info["signal"]
                    save_json(LAST_FILE, last_signals)
                except Exception as e:
                    print(f"Errore TF {tf}: {e}")
                time.sleep(2)
            time.sleep(15)
        except Exception as e:
            print(f"Updater crash: {e}")
            time.sleep(10)

@app.route("/api/ping")
def ping(): return jsonify({"ok":True,"history":len(history),"subs":len(subscriptions),"cached_tfs":list(latest_data.keys())})

@app.route("/api/signals")
def sig():
    tf=request.args.get("tf","4H")
    with latest_data_lock:
        if tf in latest_data:
            return jsonify(latest_data[tf])
    # se non c'è ancora cache, ritorna subito fake per non bloccare
    return jsonify({"coins":{"BTC":{"symbol":"BTCUSDT","price":0,"rsi":0,"signal":"CARICAMENTO","conf":0,"trend":"Avvio server...","reasons":["Attendi 10s"],"bullish":0,"bearish":0,"adx":0,"vol_ratio":1,"ema50":0,"ema200":0,"bb_up":0,"bb_low":0,"macd":0,"macd_signal":0,"sl":0,"tp":0}},"globale":"CARICAMENTO","tf":tf,"updated":datetime.now().strftime("%H:%M:%S")})

@app.route("/api/history")
def hist_api():
    coin=request.args.get("coin"); min_conf=int(request.args.get("min_conf","60"))
    filtered=[h for h in history if h["conf"]>=min_conf]
    if coin: filtered=[h for h in filtered if h["coin"]==coin]
    filtered=sorted(filtered, key=lambda x: x["timestamp"], reverse=True)[:200]
    return jsonify(filtered)

@app.route("/api/push/subscribe", methods=["POST"])
def sub():
    s=request.get_json()
    if s and s not in subscriptions:
        subscriptions.append(s); save_json(SUBS_FILE, subscriptions)
    return jsonify({"ok":True,"total":len(subscriptions)})

@app.route("/api/push/test", methods=["POST"])
def testp():
    d=request.get_json(silent=True) or {}
    sent=send_push(f"TEST INSTANT {d.get('coin','BTC')} {d.get('tf','4H')}", f"Test - {datetime.now().strftime('%H:%M:%S')}", coin=d.get('coin','BTC'), tf=d.get('tf','4H'))
    return jsonify({"ok":True,"sent_to":sent,"subs":len(subscriptions)})

@app.route("/sw.js")
def sw(): return Response("self.addEventListener('push',e=>{let d={};try{d=e.data.json()}catch{};self.registration.showNotification(d.title||'[SERVER]',{body:d.body||'',data:{url:d.url||'/app'}})});self.addEventListener('notificationclick',e=>{e.notification.close();clients.openWindow(e.notification.data.url||'/app')});", mimetype="application/javascript")

@app.route("/")
@app.route("/app")
def app_page():
    return """
<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Vendi PRO V2 INSTANT</title>
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
<div class=header><div style="display:flex;gap:10px;align-items:center"><div class=logo>⚡</div><div><div style="font-weight:800;font-size:14px">Vendi PRO V2 INSTANT • FIX BLOCCO</div><div style="opacity:.85;font-size:10px">RSI+EMA+BB+MACD+VOL+ADX+ATR • Cache RAM • Push ALL >60%</div><div style="opacity:.7;font-size:9px" id=subStatus>Push: verifica...</div></div></div>✅</div>
<div class=tfs>
<button onclick="loadTF('5m')" id=b5m>5m ⚡</button>
<button onclick="loadTF('15m')" id=b15m>15m ⚡</button>
<button onclick="loadTF('1H')" id=b1H>1H</button>
<button onclick="loadTF('4H')" id=b4H class=active>4H</button>
<button onclick="loadTF('1D')" id=b1D>1D</button>
</div>
<div class=global-card style="background:white;border-radius:16px;padding:12px 14px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 4px 20px rgba(0,0,0,.05)"><div><div style="font-size:9px;color:#64748b">GLOBALE</div><div style="font-weight:800;font-size:14px" id=globale>...</div><div style="font-size:10px;color:#64748b" id=globaleSub>TF 4H</div></div><div style="text-align:right"><div style="font-size:9px;color:#64748b">AGGIORNATO</div><div style="font-weight:700;font-size:12px" id=agg>--</div><div style="font-size:9px;color:#10b981">INSTANT CACHE</div></div></div>
<div class=coin-card id=coins><div style="padding:24px;text-align:center;color:#94a3b8">Caricamento INSTANT...</div></div>
<div class=coin-card style="margin-top:12px"><div style="padding:10px 14px;display:flex;justify-content:space-between;align-items:center;cursor:pointer" onclick="toggleHist()"><div><b style="font-size:13px">📜 Storico V2 INSTANT >60%</b><div style="font-size:10px;color:#64748b">Tutti TF - non si blocca</div></div><div id=histArrow>▼</div></div><div id=histList style="display:none;padding:0 8px 8px"></div></div>
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
  curTF=tf; document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active')); document.getElementById('b'+tf).classList.add('active');
  document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center;color:#94a3b8">INSTANT '+tf+'...</div>';
  try{
    const res=await fetch('/api/signals?tf='+tf); const d=await res.json(); lastData=d;
    document.getElementById('globale').innerText=d.globale; document.getElementById('globale').style.color=colorFor(d.globale);
    document.getElementById('globaleSub').innerText=d.globale+' • TF '+tf; document.getElementById('agg').innerText=d.updated;
    if(!d.coins || Object.keys(d.coins).length==0){document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center">Nessun dato, attendi 15s e ricarica</div>'; return;}
    let html='';
    for(let [name,info] of Object.entries(d.coins)){
      if(!info) continue;
      const icon=name=='BTC'?'btc':name=='ETH'?'eth':'oro'; const ico=name=='BTC'?'₿':name=='ETH'?'Ξ':'Au';
      const price=info.price?info.price.toFixed(2):'0.00';
      html+=`<div class=coin-row onclick="openDetails('${name}')"><div style="display:flex;gap:8px;align-items:center"><div class="coin-icon ${icon}">${ico}</div><div><b>${name} <span style="font-size:9px;color:#64748b">ADX ${info.adx?info.adx.toFixed(0):0}</span></b><div style="font-size:10px;color:#64748b">RSI ${info.rsi?info.rsi.toFixed(1):0} • x${info.vol_ratio?info.vol_ratio.toFixed(1):1} • ${info.trend||''}</div><div style="font-size:9px;color:#94a3b8">${info.reasons?info.reasons.slice(0,2).join(' • '):''}</div></div></div><div style="text-align:right"><span class="badge ${bgFor(info.signal)}">${info.signal} ${info.conf}%</span><div style="font-weight:800;margin-top:2px;font-size:12px">$${price}</div><div style="font-size:9px;color:#94a3b8">B${info.bullish||0}/B${info.bearish||0}</div></div></div>`;
    }
    document.getElementById('coins').innerHTML=html||'<div style="padding:20px;text-align:center">Dati in arrivo... ricarica tra 10s</div>';
    loadHistGlobal();
    if('serviceWorker' in navigator){try{const reg=await navigator.serviceWorker.ready; const s=await reg.pushManager.getSubscription(); if(s){document.getElementById('subStatus').innerText='Push: ATTIVO ALL >60%'; await fetch('/api/push/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(s)});}}catch{}
  }catch(e){document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center;color:#dc2626">Errore: '+e.message+' - riprovo</div>'; setTimeout(()=>loadTF(tf),3000);}
}
async function loadHistGlobal(){try{const r=await fetch('/api/history?min_conf=60'); const list=await r.json(); const c=document.getElementById('histList'); if(!list.length){c.innerHTML='<div style="padding:6px;color:#94a3b8;font-size:10px">Nessun >60%</div>';return;} c.innerHTML=list.map(h=>`<div class=hist-item><div><b>${h.coin}</b> <span style="padding:2px 5px;border-radius:999px;font-size:9px;font-weight:700;background:${h.signal=='COMPRA'?'#dcfce7':'#fee2e2'};color:${h.signal=='COMPRA'?'#16a34a':'#dc2626'}">${h.signal} ${h.conf}%</span> <small>${h.tf}</small></div><div style="text-align:right"><div>$${h.price.toFixed(2)}</div><div style="font-size:9px;color:#94a3b8">${h.time}</div></div></div>`).join('');}catch{}}
function toggleHist(){const l=document.getElementById('histList');const a=document.getElementById('histArrow'); if(l.style.display=='none'){l.style.display='block';a.innerText='▲';loadHistGlobal();}else{l.style.display='none';a.innerText='▼'}}
async function openDetails(coin){
  if(!lastData) return; const info=lastData.coins[coin]; if(!info) return; currentDetail=coin;
  document.getElementById('mCoin').innerText=coin+' • '+info.symbol; document.getElementById('mPrice').innerText='$'+(info.price?info.price.toFixed(2):0)+' • ADX '+(info.adx?info.adx.toFixed(1):0);
  document.getElementById('mSignal').innerText=info.signal; document.getElementById('mSignal').style.color=colorFor(info.signal);
  document.getElementById('mConf').innerText=info.signal+' '+info.conf+'%'; document.getElementById('mBull').innerText=info.bullish||0; document.getElementById('mBear').innerText=info.bearish||0;
  document.getElementById('mRsi').innerText='RSI '+(info.rsi||0); document.getElementById('mTrend').innerText=info.trend||''; document.getElementById('mAdx').innerText='ADX '+(info.adx?info.adx.toFixed(1):0)+' Vol x'+(info.vol_ratio?info.vol_ratio.toFixed(2):1);
  document.getElementById('mEma').innerText='$'+(info.ema50?info.ema50.toFixed(2):0)+' / $'+(info.ema200?info.ema200.toFixed(2):0); document.getElementById('mEmaDetail').innerText=info.ema50>info.ema200?'Sopra':'Sotto';
  document.getElementById('mBb').innerText='BB '+(info.bb_up?info.bb_up.toFixed(0):'-')+'/'+(info.bb_low?info.bb_low.toFixed(0):'-'); document.getElementById('mMacd').innerText='MACD '+(info.macd?info.macd.toFixed(2):0)+' vs '+(info.macd_signal?info.macd_signal.toFixed(2):0);
  document.getElementById('mEntry').innerText='$'+(info.price?info.price.toFixed(2):0); document.getElementById('mSL').innerText=info.sl?'$'+info.sl.toFixed(2):'-'; document.getElementById('mTP').innerText=info.tp?'$'+info.tp.toFixed(2):'-';
  document.getElementById('mHistCoin').innerText=coin;
  document.getElementById('mReasons').innerHTML=info.reasons?info.reasons.map(r=>`<span class=reason>${r}</span>`).join(' '):'';
  document.getElementById('modal').classList.add('show');
  try{const r=await fetch('/api/history?coin='+coin+'&min_conf=60'); const list=await r.json(); document.getElementById('mHist').innerHTML=list.length?list.slice(0,8).map(h=>`<div class=hist-item><div><b>${h.tf}</b> ${h.signal} ${h.conf}%</div><div>${h.time} $${h.price.toFixed(0)}</div></div>`).join(''):'<div style="font-size:10px;color:#94a3b8">Nessuno</div>';}catch{}
}
function closeModal(){document.getElementById('modal').classList.remove('show')}
function openChart(){if(!currentDetail)return;const map={BTC:'BINANCE:BTCUSDT',ETH:'BINANCE:ETHUSDT',ORO:'BINANCE:PAXGUSDT'};window.open('https://www.tradingview.com/chart/?symbol='+map[currentDetail]+'&interval='+curTF,'_blank');}
loadTF('4H'); setInterval(()=>loadTF(curTF),20000);
if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js');}
</script>
</body></html>
"""

threading.Thread(target=background_updater, daemon=True).start()
if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)), threaded=True)
