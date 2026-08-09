"""
Vendi STABILE PRO - V2 PRO PUSH 5M/15M ATTIVE >60%
- Push per 5m,15m,1H,4H,1D se conf>=60%
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
BINANCE_BASES=["https://data-api.binance.vision","https://api1.binance.com","https://api2.binance.com"]

def get_ohlcv(symbol, interval, limit=200):
    headers={"User-Agent":"Mozilla/5.0"}
    for base in BINANCE_BASES:
        try:
            url=f"{base}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            r=requests.get(url, timeout=12, headers=headers)
            if r.status_code in (451,403,400): continue
            r.raise_for_status()
            data=r.json()
            ohlcv=[]
            for c in data:
                ohlcv.append({"open":float(c[1]),"high":float(c[2]),"low":float(c[3]),"close":float(c[4]),"volume":float(c[5])})
            return ohlcv
        except: continue
    return None

def get_ticker_price(symbol):
    for base in BINANCE_BASES:
        try:
            r=requests.get(f"{base}/api/v3/ticker/price?symbol={symbol}", timeout=8)
            if r.status_code in (451,403,400): continue
            return float(r.json()["price"])
        except: continue
    return None

def sma(arr, period):
    if len(arr)<period: return None
    return sum(arr[-period:])/period

def ema(arr, period):
    if len(arr)<period: return None
    k=2/(period+1)
    e=sma(arr[:period], period)
    for price in arr[period:]:
        e = price*k + e*(1-k)
    return e

def ema_series(arr, period):
    if len(arr)<period: return [None]*len(arr)
    k=2/(period+1)
    s=sma(arr[:period], period)
    vals=[None]*(period-1)+[s]
    e=s
    for price in arr[period:]:
        e = price*k + e*(1-k)
        vals.append(e)
    return vals

def calc_rsi(prices, period=14):
    if len(prices)<period+1: return 50
    gains=0; losses=0
    for i in range(1, period+1):
        diff=prices[-i]-prices[-i-1]
        if diff>0: gains+=diff
        else: losses-=diff
    if losses==0: return 95 if gains>0 else 50
    return round(100-(100/(1+gains/losses)),2)

def calc_bollinger(prices, period=20, mult=2):
    if len(prices)<period: return None,None,None
    m=sma(prices, period)
    std=math.sqrt(sum((x-m)**2 for x in prices[-period:])/period)
    return m+mult*std, m, m-mult*std

def calc_macd(prices):
    if len(prices)<35: return 0,0,0
    ema12=ema(prices,12); ema26=ema(prices,26)
    if ema12 is None or ema26 is None: return 0,0,0
    macd_line=ema12-ema26
    ema12_s=ema_series(prices,12); ema26_s=ema_series(prices,26)
    macd_series=[a-b if a is not None and b is not None else None for a,b in zip(ema12_s, ema26_s)]
    filtered=[x for x in macd_series if x is not None]
    if len(filtered)<9: return macd_line,0,0
    signal=ema(filtered,9) or 0
    return macd_line, signal, macd_line-signal

def calc_atr(highs, lows, closes, period=14):
    if len(closes)<period+1: return closes[-1]*0.01 if closes else 0
    trs=[]
    for i in range(1,len(closes)):
        hl=highs[i]-lows[i]; hc=abs(highs[i]-closes[i-1]); lc=abs(lows[i]-closes[i-1])
        trs.append(max(hl,hc,lc))
    return sma(trs, period) or trs[-1]

def calc_adx(highs, lows, closes, period=14):
    if len(closes)<period*2: return 15,0,0
    trs=[]; plus_dm=[]; minus_dm=[]
    for i in range(1,len(closes)):
        hl=highs[i]-lows[i]; hc=abs(highs[i]-closes[i-1]); lc=abs(lows[i]-closes[i-1])
        trs.append(max(hl,hc,lc))
        up=highs[i]-highs[i-1]; down=lows[i-1]-lows[i]
        plus_dm.append(up if up>0 and up>down else 0)
        minus_dm.append(down if down>0 and down>up else 0)
    def wilder(arr,p):
        if len(arr)<p: return None
        s=sum(arr[:p])
        for v in arr[p:]: s = s - s/p + v
        return s
    sm_tr=wilder(trs,period); sm_plus=wilder(plus_dm,period); sm_minus=wilder(minus_dm,period)
    if not sm_tr or sm_tr==0: return 15,0,0
    plus_di=100*sm_plus/sm_tr; minus_di=100*sm_minus/sm_tr
    dx=100*abs(plus_di-minus_di)/(plus_di+minus_di) if (plus_di+minus_di)!=0 else 0
    return max(5,min(60,dx)), plus_di, minus_di

def evaluate_signals(ohlcv, current_price, higher_tf_ohlcv=None, tf="4H"):
    closes=[c["close"] for c in ohlcv]; highs=[c["high"] for c in ohlcv]; lows=[c["low"] for c in ohlcv]; vols=[c["volume"] for c in ohlcv]
    rsi=calc_rsi(closes,14); ema50=ema(closes,50) or closes[-1]; ema200=ema(closes,200) or closes[-1]
    bb_up, bb_mid, bb_low=calc_bollinger(closes,20,2)
    macd_line, macd_signal, _=calc_macd(closes)
    vol_sma=sma(vols,20) or vols[-1]; atr=calc_atr(highs,lows,closes,14)
    adx, plus_di, minus_di=calc_adx(highs,lows,closes,14)
    bullish=0; bearish=0; reasons=[]
    if rsi<=20: bullish+=40; reasons.append(f"RSI ipervenduto {rsi}")
    elif rsi<=25: bullish+=30; reasons.append(f"RSI molto basso {rsi}")
    elif rsi<=30: bullish+=20; reasons.append(f"RSI basso {rsi}")
    elif rsi>=80: bearish+=40; reasons.append(f"RSI ipercomprato {rsi}")
    elif rsi>=75: bearish+=30; reasons.append(f"RSI molto alto {rsi}")
    elif rsi>=70: bearish+=20; reasons.append(f"RSI alto {rsi}")
    if current_price>ema200 and ema50>ema200: bullish+=25; reasons.append("Trend rialzista EMA50>EMA200")
    elif current_price<ema200 and ema50<ema200: bearish+=25; reasons.append("Trend ribassista EMA50<EMA200")
    elif current_price>ema200: bullish+=10
    elif current_price<ema200: bearish+=10
    if bb_low and current_price<=bb_low: bullish+=15; reasons.append("Tocco banda inf Bollinger")
    elif bb_up and current_price>=bb_up: bearish+=15; reasons.append("Tocco banda sup Bollinger")
    if macd_line>macd_signal: bullish+=10; reasons.append("MACD rialzista")
    else: bearish+=10; reasons.append("MACD ribassista")
    vol_ratio=vols[-1]/vol_sma if vol_sma else 1
    if vol_ratio>1.3:
        if bullish>bearish: bullish+=10; reasons.append(f"Vol +{int((vol_ratio-1)*100)}% long")
        else: bearish+=10; reasons.append(f"Vol +{int((vol_ratio-1)*100)}% short")
    adx_boost=1.0
    if adx<15: adx_boost=0.7; reasons.append(f"Laterale ADX {adx:.0f}")
    elif adx>25: adx_boost=1.2; reasons.append(f"Trend forte ADX {adx:.0f}")
    bullish*=adx_boost; bearish*=adx_boost
    mtf_msg=""
    if higher_tf_ohlcv:
        h_closes=[c["close"] for c in higher_tf_ohlcv]
        h_ema50=ema(h_closes,50) or h_closes[-1]; h_ema200=ema(h_closes,200) or h_closes[-1]
        h_trend="bull" if h_closes[-1]>h_ema200 and h_ema50>h_ema200 else "bear" if h_closes[-1]<h_ema200 and h_ema50<h_ema200 else "neutral"
        if tf in ("5m","15m"):
            if bullish>bearish and h_trend=="bear": bullish*=0.7; mtf_msg="⚠️ 1H controtrend"
            if bearish>bullish and h_trend=="bull": bearish*=0.7; mtf_msg="⚠️ 1H controtrend"
            if bullish>bearish and h_trend=="bull": bullish*=1.15; mtf_msg="✅ 1H conferma"
            if bearish>bullish and h_trend=="bear": bearish*=1.15; mtf_msg="✅ 1H conferma"
        else:
            if bullish>bearish and h_trend=="bear": bullish*=0.8; mtf_msg="⚠️ 4H controtrend"
            if bearish>bullish and h_trend=="bull": bearish*=0.8; mtf_msg="⚠️ 4H controtrend"
    if mtf_msg: reasons.append(mtf_msg)
    bullish=min(95,int(bullish)); bearish=min(95,int(bearish))
    if bullish>bearish and bullish>=35: signal="COMPRA"; conf=bullish; trend="Rialzista"
    elif bearish>bullish and bearish>=35: signal="VENDI"; conf=bearish; trend="Ribassista"
    else: signal="FERMO"; conf=max(bullish,bearish, int(50+abs(rsi-50))); trend="Laterale" if adx<20 else ("Rialzista" if bullish>bearish else "Ribassista")
    sl=tp=0
    if signal=="COMPRA": sl=current_price-atr*1.5; tp=current_price+atr*3
    elif signal=="VENDI": sl=current_price+atr*1.5; tp=current_price-atr*3
    return {"rsi":rsi,"ema50":ema50,"ema200":ema200,"bb_up":bb_up,"bb_low":bb_low,"macd":macd_line,"macd_signal":macd_signal,"vol_ratio":vol_ratio,"adx":adx,"atr":atr,"bullish":bullish,"bearish":bearish,"signal":signal,"conf":conf,"trend":trend,"reasons":reasons,"sl":sl,"tp":tp}

def get_all_signals(tf="4H"):
    interval=TF_MAP.get(tf,"4h")
    higher_interval=None
    if tf=="5m": higher_interval="1h"
    elif tf=="15m": higher_interval="1h"
    elif tf=="1H": higher_interval="4h"
    elif tf=="4H": higher_interval="1d"
    results={}; globale="FERMO"; max_conf=0
    for name, sym in SYMBOLS.items():
        ohlcv=get_ohlcv(sym, interval, 200)
        if not ohlcv:
            results[name]={"symbol":sym,"rsi":0,"signal":"OFFLINE","price":0,"conf":0,"trend":"-","reasons":[]}
            continue
        live_price=get_ticker_price(sym) or ohlcv[-1]["close"]
        higher_ohlcv=get_ohlcv(sym, higher_interval, 200) if higher_interval else None
        ev=evaluate_signals(ohlcv, live_price, higher_ohlcv, tf)
        results[name]={"symbol":sym,"price":live_price,"rsi":ev["rsi"],"signal":ev["signal"],"conf":ev["conf"],"trend":ev["trend"],"tf":tf,"ema50":ev["ema50"],"ema200":ev["ema200"],"bb_up":ev["bb_up"],"bb_low":ev["bb_low"],"macd":ev["macd"],"macd_signal":ev["macd_signal"],"vol_ratio":ev["vol_ratio"],"adx":ev["adx"],"atr":ev["atr"],"sl":ev["sl"],"tp":ev["tp"],"reasons":ev["reasons"],"bullish":ev["bullish"],"bearish":ev["bearish"]}
        if ev["signal"] in ("COMPRA","VENDI") and ev["conf"]>max_conf:
            max_conf=ev["conf"]; globale=ev["signal"]
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
    if len(history)>400: del history[0:len(history)-400]
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

def checker():
    print("Checker V2 PUSH TUTTI TF >60% avviato")
    while True:
        try:
            # Controlla TUTTI i TF per push >60%
            for tf in ["5m","15m","1H","4H","1D"]:
                data=get_all_signals(tf)
                for cname, info in data["coins"].items():
                    key=f"{cname}_{tf}"
                    is_new = info["signal"]!=last_signals.get(key,"FERMO")
                    add_history(cname, tf, info)
                    # PUSH PER TUTTI I TF SE >60%
                    if info["signal"] in ("COMPRA","VENDI") and info["conf"]>=60:
                        if is_new or tf in ("5m","15m"): # su scalping manda anche se stesso segnale ma dopo 15 min
                            send_push(f"{cname} {tf}: {info['signal']} {info['conf']}%", f"${info['price']:.2f} RSI {info['rsi']} ADX {info['adx']:.0f} | {', '.join(info['reasons'][:2])}", coin=cname, tf=tf)
                    last_signals[key]=info["signal"]
                save_json(LAST_FILE, last_signals)
                time.sleep(2)
            time.sleep(20) # check ogni 20 sec per scalping
        except Exception as e:
            print(e); time.sleep(20)

@app.route("/api/ping")
def ping(): return jsonify({"ok":True,"history":len(history),"subs":len(subscriptions)})

@app.route("/api/signals")
def sig(): return jsonify(get_all_signals(request.args.get("tf","4H")))

@app.route("/api/history")
def hist_api():
    coin=request.args.get("coin"); min_conf=int(request.args.get("min_conf","60"))
    filtered=[h for h in history if h["conf"]>=min_conf]
    if coin: filtered=[h for h in filtered if h["coin"]==coin]
    filtered=sorted(filtered, key=lambda x: x["timestamp"], reverse=True)[:150]
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
    sent=send_push(f"TEST V2 {d.get('coin','BTC')} {d.get('tf','5m')} >60%", f"Test push tutti TF - {datetime.now().strftime('%H:%M:%S')}", coin=d.get('coin','BTC'), tf=d.get('tf','5m'))
    return jsonify({"ok":True,"sent_to":sent,"subs":len(subscriptions)})

@app.route("/sw.js")
def sw(): return Response("self.addEventListener('push',e=>{let d={};try{d=e.data.json()}catch{};self.registration.showNotification(d.title||'[SERVER]',{body:d.body||'',data:{url:d.url||'/app'}})});self.addEventListener('notificationclick',e=>{e.notification.close();clients.openWindow(e.notification.data.url||'/app')});", mimetype="application/javascript")

@app.route("/")
@app.route("/app")
def app_page():
    return """
<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Vendi PRO V2 PUSH ALL</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
*{font-family:'Inter',sans-serif;box-sizing:border-box;margin:0;padding:0}
body{background:#f8fafc;min-height:100vh;padding:12px 12px 110px}
.header{background:linear-gradient(135deg,#0f172a 0%,#6366f1 100%);border-radius:20px;padding:16px;color:white;display:flex;justify-content:space-between;align-items:center}
.logo{width:44px;height:44px;background:rgba(255,255,255,.15);border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:800}
.tfs{display:flex;gap:5px;margin:12px 0;overflow-x:auto}
.tfs button{border:none;background:white;padding:8px 12px;border-radius:999px;font-weight:700;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.tfs button.active{background:#0f172a;color:white}
.tfs button.scalp{border:1px solid #f59e0b}
.global-card{background:white;border-radius:16px;padding:12px 14px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 4px 20px rgba(0,0,0,.05)}
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
.item b{display:block;font-size:12px}
.reason{font-size:10px;background:#eef2ff;color:#4338ca;padding:3px 7px;border-radius:999px;display:inline-block;margin:2px}
.hist-item{display:flex;justify-content:space-between;align-items:center;padding:7px 9px;border-radius:8px;background:#f8fafc;margin:4px 0;font-size:11px}
</style>
</head><body>
<div class=header><div style="display:flex;gap:10px;align-items:center"><div class=logo>V2</div><div><div style="font-weight:800;font-size:14px">Vendi PRO V2 • PUSH TUTTI TF</div><div style="opacity:.8;font-size:10px">5m 15m 1H 4H 1D >60% • RSI+EMA+BB+MACD+VOL+ADX</div><div style="opacity:.6;font-size:9px" id=subStatus>Push: verifica...</div></div></div>🔔</div>
<div class=tfs>
<button onclick="loadTF('5m')" id=b5m class=scalp>5m ⚡</button>
<button onclick="loadTF('15m')" id=b15m class=scalp>15m ⚡</button>
<button onclick="loadTF('1H')" id=b1H>1H</button>
<button onclick="loadTF('4H')" id=b4H class=active>4H</button>
<button onclick="loadTF('1D')" id=b1D>1D</button>
</div>
<div class=global-card><div><div style="font-size:9px;color:#64748b">GLOBALE</div><div style="font-weight:800;font-size:14px" id=globale>...</div><div style="font-size:10px;color:#64748b" id=globaleSub>TF 4H</div></div><div style="text-align:right"><div style="font-size:9px;color:#64748b">AGGIORNATO</div><div style="font-weight:700;font-size:12px" id=agg>--</div><div style="font-size:9px;color:#94a3b8">PUSH ALL TF >60%</div></div></div>
<div class=coin-card id=coins><div style="padding:24px;text-align:center;color:#94a3b8">Caricamento...</div></div>
<div class=coin-card style="margin-top:12px"><div style="padding:10px 14px;display:flex;justify-content:space-between;align-items:center;cursor:pointer" onclick="toggleHist()"><div><b style="font-size:13px">📜 Storico V2 PRO >60% TUTTI TF</b><div style="font-size:10px;color:#64748b">5m 15m 1H 4H 1D con motivazioni</div></div><div id=histArrow>▼</div></div><div id=histList style="display:none;padding:0 8px 8px"></div></div>
<div class=fab><button class=btn-light onclick="testPush()">🔔 Test 5m</button><button class=btn-dark onclick="subscribePush()">📢 Attiva Push ALL</button></div>
<div id=modal onclick="if(event.target==this)closeModal()"><div class=modal-box>
  <div style="display:flex;justify-content:space-between"><div><b id=mCoin>BTC</b><div id=mPrice style="color:#64748b;font-size:11px"></div></div><button onclick="closeModal()" style="width:28px;height:28px;border-radius:999px;border:none;background:#f1f5f9">✕</button></div>
  <div class=grid2>
    <div class=item><small>SEGNALE / CONF</small><b id=mSignal>-</b><div id=mConf style="font-size:10px;color:#64748b"></div><div style="margin-top:4px"><small>B <span id=mBull>-</span> vs Bear <span id=mBear>-</span></small></div></div>
    <div class=item><small>RSI / ADX / TREND</small><b id=mRsi>-</b><div id=mTrend style="font-size:10px"></div><div style="font-size:10px" id=mAdx></div></div>
    <div class=item><small>EMA50 / EMA200</small><b id=mEma>-</b><div id=mEmaDetail style="font-size:10px;color:#64748b"></div></div>
    <div class=item><small>BB / MACD / VOL</small><b id=mBb>-</b><div id=mMacd style="font-size:10px;color:#64748b"></div></div>
  </div>
  <div style="background:#f1f5f9;border-radius:10px;padding:8px;margin:6px 0"><small style="font-weight:700;font-size:11px">Entry / SL / TP (ATR)</small><div style="display:flex;gap:6px;margin-top:4px;font-size:11px"><div>Entry <b id=mEntry>-</b></div><div>SL <b id=mSL style="color:#dc2626">-</b></div><div>TP <b id=mTP style="color:#16a34a">-</b></div></div></div>
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
    document.getElementById('subStatus').innerText='Push: ATTIVO '+j.total+' TF:5m 15m 1H 4H 1D >60%'; alert('Push ALL TF attiva Tot:'+j.total);
  }catch(e){alert('Errore push:'+e.message);}
}
async function testPush(){try{const r=await fetch('/api/push/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({coin:'BTC',tf:curTF})});const j=await r.json();alert('Test '+j.sent_to+' disp Subs:'+j.subs+' TF '+curTF);}catch(e){alert(e.message);}}
function colorFor(s){return s=='COMPRA'?'#16a34a':s=='VENDI'?'#dc2626':'#d97706'}
function bgFor(s){return s=='COMPRA'?'COMPRA-bg':s=='VENDI'?'VENDI-bg':'FERMO-bg'}
async function loadTF(tf){
  curTF=tf; document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active')); document.getElementById('b'+tf).classList.add('active');
  document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center;color:#94a3b8">Calcolo V2 '+tf+' >60%...</div>';
  try{
    const res=await fetch('/api/signals?tf='+tf); const d=await res.json(); lastData=d;
    document.getElementById('globale').innerText=d.globale; document.getElementById('globale').style.color=colorFor(d.globale);
    document.getElementById('globaleSub').innerText=d.globale+' • TF '+tf+(tf.includes('m')?' ⚡ SCALP':' Swing')+' >60% PUSH'; document.getElementById('agg').innerText=d.updated;
    let html='';
    for(let [name,info] of Object.entries(d.coins)){
      const icon=name=='BTC'?'btc':name=='ETH'?'eth':'oro'; const ico=name=='BTC'?'₿':name=='ETH'?'Ξ':'Au';
      html+=`<div class=coin-row onclick="openDetails('${name}')"><div style="display:flex;gap:8px;align-items:center"><div class="coin-icon ${icon}">${ico}</div><div><b>${name} <span style="font-size:9px;color:#64748b">ADX ${info.adx.toFixed(0)}</span></b><div style="font-size:10px;color:#64748b">RSI ${info.rsi} • Vol x${info.vol_ratio.toFixed(1)} • ${info.trend}</div><div style="font-size:9px;color:#94a3b8">${info.reasons.slice(0,2).join(' • ')}</div></div></div><div style="text-align:right"><span class="badge ${bgFor(info.signal)}">${info.signal} ${info.conf}%</span><div style="font-weight:800;margin-top:2px;font-size:12px">$${info.price.toFixed(2)}</div><div style="font-size:9px;color:#94a3b8">B${info.bullish}/B${info.bearish} • PUSH >60%</div></div></div>`;
    }
    document.getElementById('coins').innerHTML=html;
    loadHistGlobal();
    if('serviceWorker' in navigator){try{const reg=await navigator.serviceWorker.ready; const s=await reg.pushManager.getSubscription(); if(s){document.getElementById('subStatus').innerText='Push: ATTIVO 5m15m1H4H1D >60%'; await fetch('/api/push/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(s)});}}catch{}
  }catch(e){document.getElementById('coins').innerText='Errore '+e;}
}
async function loadHistGlobal(){try{const r=await fetch('/api/history?min_conf=60'); const list=await r.json(); const c=document.getElementById('histList'); if(!list.length){c.innerHTML='<div style="padding:6px;color:#94a3b8;font-size:10px">Nessun segnale >60%</div>';return;} c.innerHTML=list.map(h=>`<div class=hist-item><div><b>${h.coin}</b> <span style="padding:2px 5px;border-radius:999px;font-size:9px;font-weight:700;background:${h.signal=='COMPRA'?'#dcfce7':'#fee2e2'};color:${h.signal=='COMPRA'?'#16a34a':'#dc2626'}">${h.signal} ${h.conf}%</span> <small>${h.tf}${h.tf.includes('m')?'⚡':''}</small></div><div style="text-align:right"><div>$${h.price.toFixed(2)}</div><div style="font-size:9px;color:#94a3b8">${h.time}</div></div></div>`).join('');}catch{}}
function toggleHist(){const l=document.getElementById('histList');const a=document.getElementById('histArrow'); if(l.style.display=='none'){l.style.display='block';a.innerText='▲';loadHistGlobal();}else{l.style.display='none';a.innerText='▼'}}
async function openDetails(coin){
  if(!lastData) return; const info=lastData.coins[coin]; if(!info) return; currentDetail=coin;
  document.getElementById('mCoin').innerText=coin+' • '+info.symbol+' • PUSH >60% '+curTF; document.getElementById('mPrice').innerText='$'+info.price.toFixed(2)+' USDT • ADX '+info.adx.toFixed(1);
  document.getElementById('mSignal').innerText=info.signal; document.getElementById('mSignal').style.color=colorFor(info.signal);
  document.getElementById('mConf').innerText=info.signal+' '+info.conf+'%'; document.getElementById('mBull').innerText=info.bullish; document.getElementById('mBear').innerText=info.bearish;
  document.getElementById('mRsi').innerText='RSI '+info.rsi; document.getElementById('mTrend').innerText=info.trend; document.getElementById('mAdx').innerText='ADX '+info.adx.toFixed(1)+' Vol x'+info.vol_ratio.toFixed(2);
  document.getElementById('mEma').innerText='$'+info.ema50.toFixed(2)+' / $'+info.ema200.toFixed(2); document.getElementById('mEmaDetail').innerText=info.ema50>info.ema200?'EMA50>200 rialzista':'EMA50<200 ribassista';
  document.getElementById('mBb').innerText='BB '+(info.bb_up?info.bb_up.toFixed(0):'-')+'/'+(info.bb_low?info.bb_low.toFixed(0):'-'); document.getElementById('mMacd').innerText='MACD '+info.macd.toFixed(2)+' vs '+info.macd_signal.toFixed(2);
  document.getElementById('mEntry').innerText='$'+info.price.toFixed(2); document.getElementById('mSL').innerText=info.sl?'$'+info.sl.toFixed(2):'-'; document.getElementById('mTP').innerText=info.tp?'$'+info.tp.toFixed(2):'-';
  document.getElementById('mHistCoin').innerText=coin;
  document.getElementById('mReasons').innerHTML=info.reasons.map(r=>`<span class=reason>${r}</span>`).join(' ');
  document.getElementById('modal').classList.add('show');
  try{const r=await fetch('/api/history?coin='+coin+'&min_conf=60'); const list=await r.json(); document.getElementById('mHist').innerHTML=list.length?list.slice(0,8).map(h=>`<div class=hist-item><div><b>${h.tf}</b> ${h.signal} ${h.conf}%</div><div>${h.time} $${h.price.toFixed(0)}</div></div>`).join(''):'<div style="font-size:10px;color:#94a3b8">Nessuno</div>';}catch{}
}
function closeModal(){document.getElementById('modal').classList.remove('show')}
function openChart(){if(!currentDetail)return;const map={BTC:'BINANCE:BTCUSDT',ETH:'BINANCE:ETHUSDT',ORO:'BINANCE:PAXGUSDT'};window.open('https://www.tradingview.com/chart/?symbol='+map[currentDetail]+'&interval='+curTF,'_blank');}
loadTF('4H'); setInterval(()=>loadTF(curTF),25000);
if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js');}
</script>
</body></html>
"""

threading.Thread(target=checker, daemon=True).start()
if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
