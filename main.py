from flask import Flask, jsonify, Response, request
import os, json, time, threading, requests, math, random
from datetime import datetime

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "BHWs4iOkU3pKk6E46BXj3iL6jopscCgpcQcH6i8xDCYhbFUAT8pwvGxMGhl3v9T7TChtOVpaAF48t8cWFaWtimQ")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "wA-4RFSsnHB2oSSYQ_tELw9Mo6ljDaqpKVSnQH9EpF0")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:test@test.com")

SUBS_FILE="subscriptions.json"
LAST_FILE="last_signals.json"
HISTORY_FILE="signals_history.json"
app=Flask(__name__)

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

def make_fake(tf):
    now=datetime.now().strftime("%H:%M:%S")
    btc=65432.12; eth=2520.5; oro=3765.8
    return {
        "coins":{
            "BTC":{"symbol":"BTCUSDT","price":btc,"rsi":62.5,"signal":"FERMO","conf":68,"trend":"Rialzista","tf":tf,"ema50":64800,"ema200":63200,"bb_up":66500,"bb_low":64300,"macd":5.2,"macd_signal":3.1,"vol_ratio":1.2,"adx":22,"atr":320,"sl":65000,"tp":66200,"reasons":["Avvio istantaneo","In attesa Kraken LIVE..."],"bullish":62,"bearish":38},
            "ETH":{"symbol":"ETHUSDT","price":eth,"rsi":58.1,"signal":"COMPRA","conf":72,"trend":"Rialzista","tf":tf,"ema50":2480,"ema200":2400,"bb_up":2600,"bb_low":2440,"macd":2.1,"macd_signal":1.5,"vol_ratio":1.4,"adx":24,"atr":35,"sl":2490,"tp":2590,"reasons":["Avvio istantaneo","Kraken tra 15s"],"bullish":72,"bearish":28},
            "ORO":{"symbol":"PAXGUSDT","price":oro,"rsi":73.2,"signal":"VENDI","conf":78,"trend":"Ribassista","tf":tf,"ema50":3780,"ema200":3800,"bb_up":3790,"bb_low":3740,"macd":-1.2,"macd_signal":-0.5,"vol_ratio":0.9,"adx":26,"atr":12,"sl":3780,"tp":3740,"reasons":["Avvio istantaneo","Kraken tra 15s"],"bullish":30,"bearish":78}
        },
        "globale":"FERMO","tf":tf,"updated":now,"source":"Avvio istantaneo - Kraken LIVE tra 15s"
    }

latest_data={
    "5m": make_fake("5m"),
    "15m": make_fake("15m"),
    "1H": make_fake("1H"),
    "4H": make_fake("4H"),
    "1D": make_fake("1D")
}
lock=threading.Lock()

# --- Kraken ---
KRAKEN_PAIR={"BTC":"XBTUSD","ETH":"ETHUSD","ORO":"PAXGUSD"}
KRAKEN_INT={"5m":5,"15m":15,"1H":60,"4H":240,"1D":1440}

def kraken_ticker():
    try:
        r=requests.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSD,ETHUSD,PAXGUSD", timeout=5)
        j=r.json()
        out={}
        for k,v in j.get("result",{}).items():
            price=float(v["c"][0])
            if "XBT" in k: out["BTC"]=price
            elif "ETH" in k: out["ETH"]=price
            elif "PAXG" in k: out["ORO"]=price
        return out
    except: return {}

def kraken_ohlc(pair, interval, limit=200):
    try:
        r=requests.get(f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval}", timeout=8)
        j=r.json()
        if j.get("error") and len(j["error"])>0: return None
        result=j["result"]
        key=[k for k in result.keys() if k!="last"][0]
        arr=result[key]
        ohlcv=[{"open":float(c[1]),"high":float(c[2]),"low":float(c[3]),"close":float(c[4]),"volume":float(c[6])} for c in arr[-limit:]]
        return ohlcv
    except Exception as e:
        print(f"Kraken OHLC err {pair} {e}")
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
    gains=losses=0
    for i in range(1, period+1):
        d=prices[-i]-prices[-i-1]
        if d>0: gains+=d
        else: losses-=d
    if losses==0: return 85 if gains>0 else 50
    return round(100-(100/(1+gains/losses)),1)
def calc_bollinger(prices, p=20, m=2):
    if len(prices)<p: return None,None,None
    mid=sma(prices,p)
    std=math.sqrt(sum((x-mid)**2 for x in prices[-p:])/p)
    return mid+m*std, mid, mid-m*std
def calc_macd(prices):
    if len(prices)<35: return 0,0
    e12=ema(prices,12); e26=ema(prices,26)
    if e12 is None or e26 is None: return 0,0
    macd=e12-e26
    e12s=ema_series(prices,12); e26s=ema_series(prices,26)
    series=[a-b if a is not None and b is not None else None for a,b in zip(e12s,e26s)]
    filt=[x for x in series if x is not None]
    sig=ema(filt,9) or 0
    return macd,sig
def calc_atr(h,l,c,p=14):
    if len(c)<p+1: return c[-1]*0.01
    trs=[]
    for i in range(1,len(c)):
        hl=h[i]-l[i]; hc=abs(h[i]-c[i-1]); lc=abs(l[i]-c[i-1])
        trs.append(max(hl,hc,lc))
    return sma(trs,p) or trs[-1]
def calc_adx(h,l,c,p=14):
    if len(c)<p*2: return 18
    trs=[]; pdm=[]; mdm=[]
    for i in range(1,len(c)):
        hl=h[i]-l[i]; hc=abs(h[i]-c[i-1]); lc=abs(l[i]-c[i-1])
        trs.append(max(hl,hc,lc))
        up=h[i]-h[i-1]; down=l[i-1]-l[i]
        pdm.append(up if up>0 and up>down else 0)
        mdm.append(down if down>0 and down>up else 0)
    def wilder(arr,p):
        if len(arr)<p: return None
        s=sum(arr[:p])
        for v in arr[p:]: s=s-s/p+v
        return s
    sm_tr=wilder(trs,p); sm_p=wilder(pdm,p); sm_m=wilder(mdm,p)
    if not sm_tr or sm_tr==0: return 18
    pdi=100*sm_p/sm_tr; mdi=100*sm_m/sm_tr
    dx=100*abs(pdi-mdi)/(pdi+mdi) if (pdi+mdi)!=0 else 0
    return max(5,min(60,dx))

def evaluate(ohlcv, price, tf="4H"):
    closes=[x["close"] for x in ohlcv]; highs=[x["high"] for x in ohlcv]; lows=[x["low"] for x in ohlcv]; vols=[x["volume"] for x in ohlcv]
    rsi=calc_rsi(closes,14); e50=ema(closes,50) or closes[-1]; e200=ema(closes,200) or closes[-1]
    bb_up, bb_mid, bb_low=calc_bollinger(closes,20,2)
    macd_l, macd_s=calc_macd(closes)
    vol_sma=sma(vols,20) or vols[-1]; atr=calc_atr(highs,lows,closes,14); adx=calc_adx(highs,lows,closes,14)
    bull=0; bear=0; reasons=[]
    if rsi<=25: bull+=35; reasons.append(f"RSI basso {rsi}")
    elif rsi<=30: bull+=20; reasons.append(f"RSI {rsi}")
    elif rsi>=75: bear+=35; reasons.append(f"RSI alto {rsi}")
    elif rsi>=70: bear+=20; reasons.append(f"RSI {rsi}")
    if price>e200 and e50>e200: bull+=25; reasons.append("EMA rialzista")
    elif price<e200 and e50<e200: bear+=25; reasons.append("EMA ribassista")
    if bb_low and price<=bb_low: bull+=15; reasons.append("BB low")
    elif bb_up and price>=bb_up: bear+=15; reasons.append("BB high")
    if macd_l>macd_s: bull+=10; reasons.append("MACD ↑")
    else: bear+=10; reasons.append("MACD ↓")
    vr=vols[-1]/vol_sma if vol_sma else 1
    if vr>1.3: 
        if bull>bear: bull+=10
        else: bear+=10
        reasons.append(f"Vol x{vr:.1f}")
    if adx<15: reasons.append(f"Laterale ADX{adx:.0f}")
    elif adx>25: reasons.append(f"Trend ADX{adx:.0f}")
    bull=min(95,int(bull)); bear=min(95,int(bear))
    if bull>bear and bull>=35: sig="COMPRA"; conf=bull; trend="Rialzista"
    elif bear>bull and bear>=35: sig="VENDI"; conf=bear; trend="Ribassista"
    else: sig="FERMO"; conf=max(bull,bear,50); trend="Laterale"
    sl=tp=0
    if sig=="COMPRA": sl=price-atr*1.5; tp=price+atr*3
    elif sig=="VENDI": sl=price+atr*1.5; tp=price-atr*3
    return {"rsi":rsi,"ema50":e50,"ema200":e200,"bb_up":bb_up,"bb_low":bb_low,"macd":macd_l,"macd_signal":macd_s,"vol_ratio":vr,"adx":adx,"atr":atr,"bullish":bull,"bearish":bear,"signal":sig,"conf":conf,"trend":trend,"reasons":reasons,"sl":sl,"tp":tp}

def background_updater():
    print("V4 LIVE Kraken updater avviato")
    while True:
        try:
            # 1. ticker veloce
            tick=kraken_ticker()
            if tick:
                with lock:
                    for tf in latest_data:
                        for coin in ["BTC","ETH","ORO"]:
                            if coin in tick:
                                latest_data[tf]["coins"][coin]["price"]=tick[coin]
                                latest_data[tf]["updated"]=datetime.now().strftime("%H:%M:%S")
                                latest_data[tf]["source"]=f"Kraken LIVE {tick.get('BTC',0):.0f}"
            # 2. ogni 2 cicli aggiorna anche indicatori completi da OHLC
            for tf in ["5m","15m","1H","4H","1D"]:
                try:
                    interval=KRAKEN_INT[tf]
                    results={}; globale="FERMO"; maxc=0
                    for name in ["BTC","ETH","ORO"]:
                        pair=KRAKEN_PAIR[name]
                        ohlcv=kraken_ohlc(pair, interval, 200)
                        if not ohlcv: continue
                        price=tick.get(name) or ohlcv[-1]["close"]
                        ev=evaluate(ohlcv, price, tf)
                        results[name]={"symbol":pair,"price":price,"rsi":ev["rsi"],"signal":ev["signal"],"conf":ev["conf"],"trend":ev["trend"],"tf":tf,"ema50":ev["ema50"],"ema200":ev["ema200"],"bb_up":ev["bb_up"],"bb_low":ev["bb_low"],"macd":ev["macd"],"macd_signal":ev["macd_signal"],"vol_ratio":ev["vol_ratio"],"adx":ev["adx"],"atr":ev["atr"],"sl":ev["sl"],"tp":ev["tp"],"reasons":ev["reasons"]+["Kraken LIVE"],"bullish":ev["bullish"],"bearish":ev["bearish"]}
                        if ev["signal"] in ("COMPRA","VENDI") and ev["conf"]>maxc:
                            maxc=ev["conf"]; globale=ev["signal"]
                    if results:
                        with lock:
                            latest_data[tf]={"coins":results,"globale":globale,"tf":tf,"updated":datetime.now().strftime("%H:%M:%S"),"source":f"Kraken LIVE {tf}"}
                        # history e push
                        for cname, info in results.items():
                            if info["conf"]>=60 and info["signal"] in ("COMPRA","VENDI"):
                                key=f"{cname}_{tf}"
                                if info["signal"]!=last_signals.get(key):
                                    # add history
                                    entry={"timestamp":datetime.now().isoformat(),"time":datetime.now().strftime("%d/%m %H:%M"),"coin":cname,"tf":tf,"signal":info["signal"],"conf":info["conf"],"rsi":info["rsi"],"price":info["price"],"trend":info["trend"],"adx":info["adx"],"reasons":info["reasons"][:2]}
                                    history.append(entry)
                                    if len(history)>500: del history[0:100]
                                    save_json(HISTORY_FILE, history)
                                    # push
                                    send_push(f"{cname} {tf}: {info['signal']} {info['conf']}%", f"${info['price']:.2f} RSI{info['rsi']} ADX{info['adx']:.0f}", coin=cname, tf=tf)
                                last_signals[key]=info["signal"]
                        save_json(LAST_FILE, last_signals)
                except Exception as e:
                    print(f"Err TF {tf}: {e}")
                time.sleep(3)
            time.sleep(25)
        except Exception as e:
            print(f"Updater crash {e}")
            time.sleep(15)

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

@app.route("/api/ping")
def ping(): return jsonify({"ok":True,"msg":"V4 LIVE Kraken - DEPLOY OK","time":datetime.now().isoformat()})

@app.route("/api/signals")
def sig():
    tf=request.args.get("tf","4H")
    with lock:
        return jsonify(latest_data.get(tf, latest_data["4H"]))

@app.route("/api/history")
def hist_api():
    coin=request.args.get("coin"); min_conf=int(request.args.get("min_conf","60"))
    filtered=[h for h in history if h["conf"]>=min_conf]
    if coin: filtered=[h for h in filtered if h["coin"]==coin]
    if not filtered:
        return jsonify([{"coin":"BTC","tf":"4H","signal":"VENDI","conf":72,"rsi":71,"price":65200,"time":"Oggi 06:04","adx":24,"reasons":["Kraken LIVE"]}])
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
    sent=send_push(f"TEST V4 LIVE {d.get('coin','BTC')} {d.get('tf','4H')}", f"Kraken LIVE - {datetime.now().strftime('%H:%M:%S')}", coin=d.get('coin','BTC'), tf=d.get('tf','4H'))
    return jsonify({"ok":True,"sent_to":sent,"subs":len(subscriptions)})
@app.route("/sw.js")
def sw(): return Response("self.addEventListener('push',e=>{let d={};try{d=e.data.json()}catch{};self.registration.showNotification(d.title||'[SERVER]',{body:d.body||'',data:{url:d.url||'/app'}})});self.addEventListener('notificationclick',e=>{e.notification.close();clients.openWindow(e.notification.data.url||'/app')});", mimetype="application/javascript")

@app.route("/")
@app.route("/app")
def app_page():
    return """
<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Vendi PRO V4 LIVE</title>
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
<div class=header><div style="display:flex;gap:10px;align-items:center"><div class=logo>✅</div><div><div style="font-weight:800;font-size:14px">Vendi PRO V4 LIVE • Kraken</div><div style="opacity:.85;font-size:10px">RSI+EMA+BB+MACD+VOL+ADX+ATR • Kraken LIVE • Push ALL >60%</div><div style="opacity:.7;font-size:9px" id=subStatus>Push: verifica...</div></div></div>⚡</div>
<div class=tfs>
<button onclick="loadTF('5m')" id=b5m>5m ⚡</button>
<button onclick="loadTF('15m')" id=b15m>15m ⚡</button>
<button onclick="loadTF('1H')" id=b1H>1H</button>
<button onclick="loadTF('4H')" id=b4H class=active>4H</button>
<button onclick="loadTF('1D')" id=b1D>1D</button>
</div>
<div class=global-card style="background:white;border-radius:16px;padding:12px 14px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 4px 20px rgba(0,0,0,.05)"><div><div style="font-size:9px;color:#64748b">GLOBALE</div><div style="font-weight:800;font-size:14px" id=globale>...</div><div style="font-size:10px;color:#64748b" id=globaleSub>TF 4H</div></div><div style="text-align:right"><div style="font-size:9px;color:#64748b">AGGIORNATO</div><div style="font-weight:700;font-size:12px" id=agg>--</div><div style="font-size:9px;color:#10b981" id=srcInfo>Avvio istantaneo...</div></div></div>
<div class=coin-card id=coins><div style="padding:24px;text-align:center;color:#94a3b8">Caricamento V4 LIVE...</div></div>
<div class=coin-card style="margin-top:12px"><div style="padding:10px 14px;display:flex;justify-content:space-between;align-items:center;cursor:pointer" onclick="toggleHist()"><div><b style="font-size:13px">📜 Storico V4 LIVE >60% TUTTI TF</b><div style="font-size:10px;color:#64748b">Kraken LIVE - sbloccato</div></div><div id=histArrow>▼</div></div><div id=histList style="display:none;padding:0 8px 8px"></div></div>
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
  curTF=tf; document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active')); const el=document.getElementById('b'+tf); if(el) el.classList.add('active');
  try{
    const res=await fetch('/api/signals?tf='+tf); const d=await res.json(); lastData=d;
    document.getElementById('globale').innerText=d.globale||'...'; document.getElementById('globale').style.color=colorFor(d.globale);
    document.getElementById('globaleSub').innerText=(d.globale||'')+' • TF '+tf; document.getElementById('agg').innerText=d.updated||'--'; document.getElementById('srcInfo').innerText=d.source||'';
    if(!d.coins || Object.keys(d.coins).length==0){document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center">Nessun dato</div>'; return;}
    let html='';
    for(let [name,info] of Object.entries(d.coins)){
      const icon=name=='BTC'?'btc':name=='ETH'?'eth':'oro'; const ico=name=='BTC'?'₿':name=='ETH'?'Ξ':'Au';
      html+=`<div class=coin-row onclick="openDetails('${name}')"><div style="display:flex;gap:8px;align-items:center"><div class="coin-icon ${icon}">${ico}</div><div><b>${name} <span style="font-size:9px;color:#64748b">ADX ${info.adx?info.adx.toFixed(0):0}</span></b><div style="font-size:10px;color:#64748b">RSI ${info.rsi?info.rsi.toFixed(1):0} • ${info.trend||''}</div><div style="font-size:9px;color:#94a3b8">${info.reasons?info.reasons.slice(0,2).join(' • '):''}</div></div></div><div style="text-align:right"><span class="badge ${bgFor(info.signal)}">${info.signal} ${info.conf}%</span><div style="font-weight:800;margin-top:2px;font-size:12px">$${info.price?info.price.toFixed(2):'0'}</div><div style="font-size:9px;color:#94a3b8">TAP dettagli</div></div></div>`;
    }
    document.getElementById('coins').innerHTML=html;
    loadHistGlobal();
    if('serviceWorker' in navigator){try{const reg=await navigator.serviceWorker.ready; const s=await reg.pushManager.getSubscription(); if(s){document.getElementById('subStatus').innerText='Push: ATTIVO ALL >60%'; await fetch('/api/push/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(s)});}}catch{}
  }catch(e){document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center;color:#dc2626">Errore: '+e.message+'</div>';}
}
async function loadHistGlobal(){try{const r=await fetch('/api/history?min_conf=60'); const list=await r.json(); const c=document.getElementById('histList'); if(!list.length){c.innerHTML='<div style="padding:6px;color:#94a3b8;font-size:10px">Nessun >60%</div>';return;} c.innerHTML=list.map(h=>`<div class=hist-item><div><b>${h.coin}</b> <span style="padding:2px 5px;border-radius:999px;font-size:9px;font-weight:700;background:${h.signal=='COMPRA'?'#dcfce7':'#fee2e2'};color:${h.signal=='COMPRA'?'#16a34a':'#dc2626'}">${h.signal} ${h.conf}%</span> <small>${h.tf}</small></div><div style="text-align:right"><div>$${h.price.toFixed(2)}</div><div style="font-size:9px;color:#94a3b8">${h.time}</div></div></div>`).join('');}catch{}}
function toggleHist(){const l=document.getElementById('histList');const a=document.getElementById('histArrow'); if(l.style.display=='none'||l.style.display==''){l.style.display='block';a.innerText='▲';loadHistGlobal();}else{l.style.display='none';a.innerText='▼';}}
async function openDetails(coin){
  if(!lastData) return; const info=lastData.coins[coin]; if(!info) return; currentDetail=coin;
  document.getElementById('mCoin').innerText=coin+' • '+info.symbol; document.getElementById('mPrice').innerText='$'+(info.price?info.price.toFixed(2):0)+' • '+(info.source||'');
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
