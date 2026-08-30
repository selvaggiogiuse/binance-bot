# -*- coding: utf-8 -*-
from flask import Flask, jsonify, Response, request
import os, requests, time, threading, json
from datetime import datetime, timezone, timedelta, date
try:
    from zoneinfo import ZoneInfo
    def rome_now(): return datetime.now(ZoneInfo("Europe/Rome"))
except:
    def rome_now(): return datetime.now(timezone.utc) + timedelta(hours=2)

app = Flask(__name__)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
TELEGRAM_MIN_CONF = 85  # V64 REAL: 85% minimo per soldi veri
PAIRS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "ORO": "PAXGUSDT"}
VERSION = "V64 REAL MONEY READY - RISK GUARD + DIARIO"
COOLDOWN = 600
LAST_TELEGRAM = {}
LAST_ENTRA = {}
STABLE_SECONDS = 180

# V64 REAL: Risk Guard + Diario
TRADE_HISTORY = []  # {"time":..., "coin":..., "tf":..., "signal":..., "entry":..., "sl":..., "tp":..., "result": None/"WIN"/"LOSS", "pnl_pct":0}
RISK_CONFIG = {"mode": "DEMO", "capital": 1000.0, "risk_pct": 1.0, "max_trades_day": 3, "max_losses_row": 2, "daily_trades": 0, "daily_losses_row": 0, "last_day": str(date.today())}
DAILY_STATS = {}

def ema_calc(data, p):
    if len(data) < p: return sum(data)/len(data) if data else 0
    k=2/(p+1); ema=sum(data[:p])/p
    for v in data[p:]: ema=v*k+ema*(1-k)
    return ema
def rsi_calc(closes, period=14):
    if len(closes) < period+1: return 50
    g=0; l=0
    for i in range(1, period+1):
        d=closes[-i]-closes[-i-1]
        if d>0: g+=d
        else: l-=d
    if l==0: return 70 if g>0 else 50
    rs=g/l if l!=0 else 0
    return 100-(100/(1+rs))

def get_price(name):
    sym=PAIRS.get(name,"BTCUSDT")
    try:
        r=requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}",timeout=2,headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code==200: return float(r.json()['price']), "BINANCE"
    except: pass
    try:
        km={"BTC":"XXBTZUSD","ETH":"XETHZUSD","ORO":"PAXGUSD"}[name]
        r=requests.get(f"https://api.kraken.com/0/public/Ticker?pair={km}",timeout=3)
        if r.status_code==200:
            res=r.json().get("result",{})
            if res:
                k=list(res.keys())[0]
                return float(res[k]["c"][0]), "KRAKEN"
    except: pass
    try:
        cg={"BTC":"bitcoin","ETH":"ethereum","ORO":"pax-gold"}[name]
        r=requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={cg}&vs_currencies=usd",timeout=4)
        if r.status_code==200: return float(r.json()[cg]["usd"]), "COINGECKO"
    except: pass
    return None, "FAIL"

def fetch_binance(sym, interval, limit=200):
    try:
        r=requests.get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}",timeout=4,headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code!=200: return []
        return [{"close":float(k[4]),"low":float(k[3]),"high":float(k[2]),"volume":float(k[5])} for k in r.json()]
    except: return []
def fetch_kraken(name, interval, limit=200):
    try:
        km={"BTC":"XXBTZUSD","ETH":"XETHZUSD","ORO":"PAXGUSD"}[name]
        imap={"5m":1,"15m":15,"1h":60,"4h":240,"1d":1440}
        r=requests.get(f"https://api.kraken.com/0/public/OHLC?pair={km}&interval={imap.get(interval,1)}",timeout=5)
        if r.status_code!=200: return []
        res=r.json().get("result",{})
        if not res: return []
        fk=[k for k in res.keys() if k!="last"][0]
        return [{"close":float(k[4]),"low":float(k[2]),"high":float(k[3]),"volume":float(k[6])} for k in res[fk][-limit:]]
    except: return []
def fetch_ohlc(name, tf, limit=200):
    sym=PAIRS[name]
    tfm={"5m":"5m","15m":"15m","1H":"1h","4H":"4h","1D":"1d"}
    interval=tfm.get(tf,"5m")
    ohlc=fetch_binance(sym, interval, limit)
    if ohlc and len(ohlc)>=20: return ohlc, "BINANCE"
    ohlc2=fetch_kraken(name, interval, limit)
    if ohlc2 and len(ohlc2)>=20: return ohlc2, "KRAKEN"
    return [], "FAIL"

def check_risk_guard():
    global RISK_CONFIG
    today = str(date.today())
    if RISK_CONFIG["last_day"] != today:
        RISK_CONFIG["daily_trades"] = 0
        RISK_CONFIG["daily_losses_row"] = 0
        RISK_CONFIG["last_day"] = today
    if RISK_CONFIG["daily_trades"] >= RISK_CONFIG["max_trades_day"]:
        return False, f"Max {RISK_CONFIG['max_trades_day']} trade/giorno raggiunto (REAL protection)"
    if RISK_CONFIG["daily_losses_row"] >= RISK_CONFIG["max_losses_row"]:
        return False, f"Stop dopo {RISK_CONFIG['max_losses_row']} perdite di fila (REAL protection)"
    return True, "OK"

def send_tg(coin, tf, signal, conf, price, sl, tp, sl_pct, tp_pct, source, rsi, extra, force=False, is_real=False):
    global LAST_TELEGRAM
    if not TELEGRAM_ENABLED: return {"ok":False,"error":"no token"}
    if not force and conf < TELEGRAM_MIN_CONF: return {"ok":False,"error":f"conf {conf}<{TELEGRAM_MIN_CONF}"}
    if not force and is_real:
        ok, reason = check_risk_guard()
        if not ok:
            return {"ok":False,"error":reason,"blocked":True}
    key=f"{coin}_{tf}"
    now=time.time()
    last=LAST_TELEGRAM.get(key,0)
    if last > now + 10:
        last=0
        LAST_TELEGRAM[key]=0
    if not force and now - last < COOLDOWN:
        return {"ok":False,"error":f"cooldown {int(COOLDOWN-(now-last))}s","key":key}
    emoji="🚀" if signal=="COMPRA" else "🔻"
    mode_tag = "🔴 REAL" if is_real else "🟡 DEMO"
    rr=tp_pct/sl_pct if sl_pct>0 else 0
    tv_sym={"BTC":"BINANCE:BTCUSDT","ETH":"BINANCE:ETHUSDT","ORO":"BINANCE:PAXGUSDT"}[coin]
    chart=f"https://www.tradingview.com/chart/?symbol={tv_sym}"
    # Calcolo size per REAL
    size_info=""
    if is_real:
        cap=RISK_CONFIG["capital"]; risk_pct=RISK_CONFIG["risk_pct"]
        risk_money=cap*risk_pct/100
        size = risk_money / (price * sl_pct/100) if sl_pct>0 else 0
        size_info=f"\n💼 {mode_tag} Size: {size:.4f} {coin} | Rischio ${risk_money:.2f} ({risk_pct}%) su ${cap}"
    else:
        size_info=f"\n🧪 {mode_tag} - Test senza rischio"
    text=f"""{emoji} *{signal} {coin} {conf}%* ⚡ {tf} V64 REAL

💰 Entry: ${price:.2f} ({source})
🎯 SL: ${sl:.2f} (-{sl_pct:.2f}%) | TP: ${tp:.2f} (+{tp_pct:.2f}%) R:R 1:{rr:.1f}{size_info}
📊 RSI {rsi} | {extra}
📈 {chart}
⏰ {rome_now().strftime('%H:%M:%S')}"""
    try:
        r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id":TELEGRAM_CHAT_ID,"text":text,"parse_mode":"Markdown","disable_web_page_preview":True}, timeout=5)
        if r.status_code==200:
            LAST_TELEGRAM[key]=now
            if is_real:
                RISK_CONFIG["daily_trades"]+=1
            # Log in history
            TRADE_HISTORY.append({"time":rome_now().isoformat(),"coin":coin,"tf":tf,"signal":signal,"entry":price,"sl":sl,"tp":tp,"conf":conf,"mode":RISK_CONFIG["mode"],"result":None})
            if len(TRADE_HISTORY)>200: TRADE_HISTORY.pop(0)
            return {"ok":True,"sent":True,"key":key,"risk":size_info}
        return {"ok":False,"error":r.text[:300]}
    except Exception as e:
        return {"ok":False,"error":str(e)}

def analyze(name, tf, do_tg=False, force_tg=False):
    global LAST_ENTRA
    ohlc, src = fetch_ohlc(name, tf, 200)
    ohlc_1h, _ = fetch_ohlc(name, "1H", 100)
    ohlc_15m, _ = fetch_ohlc(name, "15m", 100) if tf=="5m" else ([], "")
    price, price_src = get_price(name)
    if not ohlc:
        if price is None: return None, None
        ohlc=[{"close":price,"low":price*0.998,"high":price*1.002,"volume":1}]*20
    closes=[c["close"] for c in ohlc]
    close_price=closes[-1]
    if price is None: price=close_price
    source=price_src
    ema9=ema_calc(closes,9); ema21=ema_calc(closes,21); ema50=ema_calc(closes,50)
    rsi=rsi_calc(closes,14)
    lows=[c["low"] for c in ohlc]; highs=[c["high"] for c in ohlc]
    vols=[c["volume"] for c in ohlc]
    avg_vol=sum(vols[-20:])/20 if vols else 1
    cur_vol=vols[-1] if vols else 1
    vol_ratio=cur_vol/avg_vol if avg_vol>0 else 1
    try: stoch=int((close_price-min(lows[-14:]))/(max(highs[-14:])-min(lows[-14:]))*100)
    except: stoch=50
    h1_up=True; h1_rsi=50; m15_up=True
    if ohlc_1h and len(ohlc_1h)>=21:
        c1h=[c["close"] for c in ohlc_1h]
        e21_1h=ema_calc(c1h,21); h1_up=c1h[-1]>e21_1h; h1_rsi=rsi_calc(c1h,14)
    if ohlc_15m and len(ohlc_15m)>=21:
        c15=[c["close"] for c in ohlc_15m]
        e21_15=ema_calc(c15,21); m15_up=c15[-1]>e21_15
    h1_text=f"1H {'UP' if h1_up else 'DOWN'} RSI{int(h1_rsi)}"
    # Confluenza per REAL
    confluence_score = 0
    if h1_up: confluence_score+=1
    if m15_up: confluence_score+=1
    if price>ema50: confluence_score+=1
    points=0
    if 52<=rsi<=62: points+=35
    elif 48<=rsi<=68: points+=20
    else: points+=5
    if close_price>ema9 and ema9>ema21 and ema21>ema50: points+=35
    elif close_price>ema9 and ema9>ema21: points+=20
    else: points+=0
    if 25<=stoch<=65: points+=15
    else: points+=5
    if vol_ratio>=1.3: points+=15
    elif vol_ratio>=1.0: points+=8
    else: points+=0
    conf=max(15,min(95,int(points)))
    swing_low=min(lows[-10:]); swing_high=max(highs[-10:])
    if close_price>ema21:
        sl_pct_raw=(price-swing_low*0.998)/price*100
        sl_pct=max(0.5,min(1.2,sl_pct_raw))
        sl=price*(1-sl_pct/100); tp_pct=sl_pct*1.8; tp=price*(1+tp_pct/100)
        signal="COMPRA"
    else:
        sl_pct_raw=(swing_high*1.002-price)/price*100
        sl_pct=max(0.5,min(1.2,sl_pct_raw))
        sl=price*(1+sl_pct/100); tp_pct=sl_pct*1.8; tp=price*(1-tp_pct/100)
        signal="VENDI"
    # V64 REAL: per REAL serve confluenza 2/3
    extra=f"{h1_text} • Vol x{vol_ratio:.1f} • {source} • Conf {confluence_score}/3 • V64 REAL"
    if signal=="COMPRA" and not (h1_up or m15_up):
        conf=max(15, conf-20)
        extra+= " • ⚠️ 1H/15m DOWN"
    if signal=="VENDI" and (h1_up and m15_up):
        conf=max(15, conf-20)
        extra+= " • ⚠️ 1H/15m UP"
    # REAL mode più severo - FIX VENDI: prima ENTRA solo per COMPRA, ora anche per VENDI
    is_real_mode = RISK_CONFIG["mode"]=="REAL"
    min_conf = 85 if is_real_mode else 80
    min_vol = 1.3 if is_real_mode else 1.0
    min_confl = 2 if is_real_mode else 1
    if signal=="COMPRA":
        ema_ok = close_price>ema9 and ema9>ema21
        confl_ok = confluence_score>=min_confl
    else:
        ema_ok = close_price<ema9 and ema9<ema21
        # per VENDI la confluenza è al contrario: 1H DOWN, 15m DOWN, sotto EMA50 = 0 punti UP, quindi 3 - score
        confl_down = (0 if h1_up else 1) + (0 if m15_up else 1) + (0 if price>ema50 else 1)
        confl_ok = confl_down>=min_confl
    if conf>=min_conf and vol_ratio>=min_vol and confl_ok and ema_ok:
        color="entra"; label="ENTRA"
    elif conf>=68:
        color="quasi"; label="QUASI"
    else:
        color="wait"; label="ASPETTA"
        signal="ASPETTA"; sl=price*0.992; tp=price*1.015; sl_pct=0.8; tp_pct=1.5
    key=f"{name}_{tf}"
    now=time.time()
    data={"price":price,"source":source,"signal":signal,"conf":conf,"quality_color":color,"quality_label":label,"rsi":int(rsi),"stoch_k":stoch,"vol_ratio":round(vol_ratio,2),"sl":sl,"tp":tp,"sl_pct":sl_pct,"tp_pct":tp_pct,"rr":round(tp_pct/sl_pct,1) if sl_pct>0 else 0,"support":swing_low,"resistance":swing_high,"spark":closes[-30:],"extra":extra,"h1":h1_text,"ema9":ema9,"ema21":ema21,"ema50":ema50,"close":close_price,"confluence":confluence_score,"is_real":is_real_mode}
    if key in LAST_ENTRA:
        prev=LAST_ENTRA[key]
        if now - prev["time"] < STABLE_SECONDS and prev["data"]["quality_color"]=="entra" and color!="entra":
            return prev["data"], None
    if color=="entra":
        LAST_ENTRA[key]={"time":now,"data":data}
    tg_res=None
    if do_tg and color=="entra":
        tg_res=send_tg(name, tf, signal, conf, price, sl, tp, sl_pct, tp_pct, source, int(rsi), extra, force=force_tg, is_real=is_real_mode)
    return data, tg_res

def ai_market_answer(question, coin="BTC", tf="5m"):
    q = question.lower()
    data, _ = analyze(coin, tf, do_tg=False)
    if not data:
        return "Non riesco a leggere i dati ora, riprova tra 10 sec."
    price = data["price"]; rsi = data["rsi"]; conf = data["conf"]; sig = data["signal"]; vol = data["vol_ratio"]; ema9=data["ema9"]; ema21=data["ema21"]; ema50=data["ema50"]; h1=data["h1"]; sl=data["sl"]; tp=data["tp"]; confl=data["confluence"]
    mode=RISK_CONFIG["mode"]; cap=RISK_CONFIG["capital"]; risk=RISK_CONFIG["risk_pct"]
    risk_money=cap*risk/100
    trend = "rialzista" if price>ema21 else "ribassista"
    # AI Risk Manager per REAL
    if "compra" in q or "entro" in q or "reale" in q or "soldi veri" in q:
        if mode=="REAL" and data["quality_color"]!="entra":
            return f"🔴 REAL MODE: ora {coin} {tf} è {data['quality_label']} {conf}% (serve 85%+ e confl {confl}/3). Con soldi veri NON entro. Aspetta ENTRA con confl 2/3. Ora {h1}, Vol x{vol}, RSI {rsi}."
        if data["quality_color"]=="entra":
            size = risk_money / (price * data["sl_pct"]/100) if data["sl_pct"]>0 else 0
            return f"✅ {coin} {tf} {sig} {conf}% - ${price:.2f} | Trend {trend} confl {confl}/3 | RSI {rsi} Vol x{vol} | {h1}\n💼 {mode}: Capitale ${cap} rischio {risk}% = ${risk_money:.2f} → size {size:.4f} {coin}\n🎯 SL ${sl:.2f} (-{data['sl_pct']:.2f}%) TP ${tp:.2f} (+{data['tp_pct']:.2f}%) R:R 1:{data['rr']}\n⚠️ Con soldi veri: max {RISK_CONFIG['max_trades_day']}/giorno, stop dopo {RISK_CONFIG['max_losses_row']} loss di fila. Oggi fatti {RISK_CONFIG['daily_trades']} trade."
        else:
            return f"⏸️ {coin} {tf} {data['quality_label']} {conf}% ({sig}) confl {confl}/3 - RSI {rsi} Vol x{vol} {h1}\nEMA9 {ema9:.0f} EMA21 {ema21:.0f} EMA50 {ema50:.0f}\nCon soldi veri aspetterei 85%+ e confl 2/3. Ora non è entrata REAL."
    if "rischio" in q or "size" in q or "quanto" in q:
        return f"💼 Risk Guard {mode}: Capitale ${cap}, rischio {risk}% = ${risk_money:.2f} a trade. Max {RISK_CONFIG['max_trades_day']} trade/giorno, stop dopo {RISK_CONFIG['max_losses_row']} perdite. Oggi {RISK_CONFIG['daily_trades']} trade, {RISK_CONFIG['daily_losses_row']} loss di fila. SL {data['sl_pct']:.2f}% = size {(risk_money/(price*data['sl_pct']/100) if data['sl_pct']>0 else 0):.4f} {coin}."
    if "diario" in q or "storico" in q or "win" in q:
        total=len(TRADE_HISTORY); wins=len([t for t in TRADE_HISTORY if t.get("result")=="WIN"]); losses=len([t for t in TRADE_HISTORY if t.get("result")=="LOSS"])
        wr = wins/total*100 if total>0 else 0
        return f"📓 Diario: {total} segnali salvati, {wins} WIN, {losses} LOSS, WR {wr:.1f}%. Ultimi 3: {TRADE_HISTORY[-3:] if total>=3 else TRADE_HISTORY}. Per soldi veri serve 30 giorni di demo con 15m >60% WR."
    if "candele" in q:
        return f"Il segnale {tf} analizza 200 candele passate ma decide sulle ultime 50 (EMA50). Il TP si prende in 3-6 candele {tf}. Con soldi veri usa 15m: 3-6 candele = 45-90 min, più stabile di 5m."
    return f"Analisi V64 REAL {coin} {tf}: ${price:.2f} {sig} {conf}% confl {confl}/3 | RSI {rsi} Vol x{vol} | EMA9 {ema9:.0f} EMA21 {ema21:.0f} EMA50 {ema50:.0f} | {h1} | SL ${sl:.0f} TP ${tp:.0f} | Mode {mode} ${cap} {risk}%. Chiedi: 'devo entrare con soldi veri?', 'calcola rischio', 'diario winrate'."

@app.route("/")
def home(): return Response(f"{VERSION} - {rome_now()} - Mode {RISK_CONFIG['mode']}", mimetype="text/plain")
@app.route("/health")
def health(): return jsonify({"ok":True,"version":VERSION,"time":rome_now().isoformat(),"telegram":TELEGRAM_ENABLED,"risk":RISK_CONFIG,"history_len":len(TRADE_HISTORY)})
@app.route("/api/nuke")
def nuke():
    global LAST_TELEGRAM, LAST_ENTRA, TRADE_HISTORY
    LAST_TELEGRAM={}; LAST_ENTRA={}; TRADE_HISTORY=[]
    RISK_CONFIG["daily_trades"]=0; RISK_CONFIG["daily_losses_row"]=0
    return jsonify({"ok":True,"nuked":True,"now":time.time()})
@app.route("/api/clear_telegram")
def clear_tg():
    global LAST_TELEGRAM
    LAST_TELEGRAM={}
    return jsonify({"ok":True,"cleared":True,"now":time.time()})
@app.route("/api/signals")
def api_signals():
    tf=request.args.get("tf","5m")
    do_tg=request.args.get("telegram","0")=="1"
    force=request.args.get("force","0")=="1"
    res={}; tg={}
    for name in PAIRS.keys():
        d,tr=analyze(name, tf, do_tg, force_tg=force)
        if d is None: d={"price":0,"source":"LOADING","signal":"LOADING","conf":0,"quality_color":"loading","quality_label":"CARICO...","rsi":50,"stoch_k":50,"vol_ratio":1,"sl":0,"tp":0,"sl_pct":0.8,"tp_pct":1.5,"rr":1.8,"spark":[],"extra":"Carico...","h1":"--","confluence":0,"is_real":False}
        res[name]=d
        if tr: tg[name]=tr
    return jsonify({"ok":True,"tf":tf,"coins":res,"telegram_results":tg,"telegram_enabled":TELEGRAM_ENABLED,"version":VERSION,"time":rome_now().isoformat(),"risk":RISK_CONFIG})
@app.route("/api/telegram_test")
def tg_test():
    r=send_tg("BTC","5m","COMPRA",85,80000,79400,81200,0.7,1.5,"TEST",55,"Test V64 REAL",force=True,is_real=(RISK_CONFIG["mode"]=="REAL"))
    return jsonify(r)
@app.route("/api/force_telegram")
def force_tg():
    out={}
    for name in PAIRS.keys():
        p,_=get_price(name)
        if p is None: p=80000
        out[name]=send_tg(name,"5m","COMPRA",85,p,p*0.995,p*1.01,0.5,0.9,"FORCE V64",55,"Force V64 REAL",force=True,is_real=(RISK_CONFIG["mode"]=="REAL"))
    return jsonify(out)
@app.route("/api/telegram_config")
def tg_config():
    now=time.time()
    future=[k for k,v in LAST_TELEGRAM.items() if v>now+10]
    return jsonify({"enabled":TELEGRAM_ENABLED,"threshold":TELEGRAM_MIN_CONF,"cooldown":COOLDOWN,"last":LAST_TELEGRAM,"now":now,"future_keys":future,"stable_keys":list(LAST_ENTRA.keys()),"risk":RISK_CONFIG})

@app.route("/api/ai_chat", methods=["POST"])
def api_ai_chat():
    try:
        body=request.get_json() or {}
        msg=body.get("message","")
        coin=body.get("coin","BTC")
        tf=body.get("tf","5m")
        if coin not in PAIRS: coin="BTC"
        if tf not in ["5m","15m","1H"]: tf="5m"
        if not msg.strip():
            return jsonify({"ok":False,"error":"Messaggio vuoto"})
        ans=ai_market_answer(msg, coin, tf)
        return jsonify({"ok":True,"coin":coin,"tf":tf,"question":msg,"answer":ans,"time":rome_now().isoformat(),"risk":RISK_CONFIG})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route("/api/risk_config", methods=["GET","POST"])
def api_risk():
    global RISK_CONFIG
    if request.method=="POST":
        data=request.get_json() or {}
        if "mode" in data and data["mode"] in ["DEMO","REAL"]: RISK_CONFIG["mode"]=data["mode"]
        if "capital" in data: 
            try: RISK_CONFIG["capital"]=float(data["capital"])
            except: pass
        if "risk_pct" in data:
            try: v=float(data["risk_pct"]); RISK_CONFIG["risk_pct"]=max(0.1,min(3.0,v))
            except: pass
        if "max_trades_day" in data:
            try: RISK_CONFIG["max_trades_day"]=int(data["max_trades_day"])
            except: pass
        if "max_losses_row" in data:
            try: RISK_CONFIG["max_losses_row"]=int(data["max_losses_row"])
            except: pass
    return jsonify({"ok":True,"risk":RISK_CONFIG})

@app.route("/api/history")
def api_history():
    total=len(TRADE_HISTORY)
    wins=len([t for t in TRADE_HISTORY if t.get("result")=="WIN"])
    losses=len([t for t in TRADE_HISTORY if t.get("result")=="LOSS"])
    pending=len([t for t in TRADE_HISTORY if t.get("result") is None])
    wr = wins/total*100 if total>0 else 0
    return jsonify({"ok":True,"total":total,"wins":wins,"losses":losses,"pending":pending,"winrate":round(wr,1),"history":TRADE_HISTORY[-50:]})

@app.route("/api/history_mark", methods=["POST"])
def api_history_mark():
    try:
        body=request.get_json() or {}
        idx=body.get("idx",-1)
        result=body.get("result") # WIN / LOSS
        if idx<0: idx=len(TRADE_HISTORY)+idx
        if 0<=idx<len(TRADE_HISTORY) and result in ["WIN","LOSS"]:
            TRADE_HISTORY[idx]["result"]=result
            # update risk guard losses
            if result=="LOSS":
                RISK_CONFIG["daily_losses_row"]+=1
            else:
                RISK_CONFIG["daily_losses_row"]=0
            return jsonify({"ok":True,"updated":TRADE_HISTORY[idx]})
        return jsonify({"ok":False,"error":"idx o result non valido"})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route("/app")
def app_page():
    html="""
<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VENDI V64 REAL</title>
<style>
*{box-sizing:border-box;font-family:Inter,system-ui,sans-serif}
body{margin:0;background:#020617;color:#e2e8f0}
.header{padding:14px 16px;display:flex;align-items:center;gap:12px;background:#0f172a;border-bottom:1px solid #1e293b;position:sticky;top:0;z-index:10}
.logo{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#22c55e,#ef4444);display:flex;align-items:center;justify-content:center;font-weight:900;color:white}
.badge{padding:4px 10px;border-radius:20px;font-size:11px;font-weight:800}
.badge-entra{background:#22c55e;color:#052e16;animation:glow 1s infinite alternate}
.badge-quasi{background:#facc15;color:#422006}
.badge-wait{background:#1e293b;color:#94a3b8}
@keyframes glow{0%{box-shadow:0 0 5px #22c55e}100%{box-shadow:0 0 12px #22c55e}}
.tfs{display:flex;gap:6px;padding:10px 12px;background:#020617;overflow-x:auto}
.tfs button{border:1px solid #1e293b;background:#1e293b;color:#cbd5e1;padding:8px 14px;border-radius:20px;font-weight:700;cursor:pointer}
.tfs button.active{background:#22c55e;color:#052e16}
.banner{margin:8px 12px;padding:10px 12px;border-radius:10px;font-size:12px;text-align:center}
.b-on{background:#052e16;border:1px solid #16a34a;color:#86efac}
.b-off{background:#450a0a;border:1px solid #dc2626;color:#fca5a5}
.banner-real{background:#7f1d1d;border:1px solid #ef4444;color:#fecaca;font-weight:800}
.coin{background:#0f172a;border:1px solid #1e293b;border-radius:14px;margin:8px 10px;overflow:hidden}
.coin-row{display:flex;justify-content:space-between;align-items:center;padding:14px;cursor:pointer}
.icon{width:38px;height:38px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:900;color:white}
.icon.btc{background:#f7931a}.icon.eth{background:#8b5cf6}.icon.oro{background:#ca8a04}
.modal{position:fixed;inset:0;background:rgba(0,0,0,0.7);display:none;align-items:flex-end;justify-content:center;z-index:50}
.modal.show{display:flex}
.box{background:#0f172a;width:100%;max-width:480px;border-radius:20px 20px 0 0;padding:20px;max-height:90vh;overflow:auto;border:1px solid #1e293b}
.btn{width:100%;padding:12px;border-radius:10px;border:none;font-weight:800;cursor:pointer;margin-top:8px}
.btn-blue{background:#0088cc;color:white}
.btn-green{background:#16a34a;color:white}
.btn-purple{background:#8b5cf6;color:white}
.btn-red{background:#dc2626;color:white}
#aiPanel{position:fixed;bottom:0;left:0;right:0;max-width:480px;margin:0 auto;background:#0f172a;border-top:2px solid #ef4444;border-left:1px solid #1e293b;border-right:1px solid #1e293b;border-radius:20px 20px 0 0;z-index:60;display:none;flex-direction:column;max-height:70vh}
#aiPanel.show{display:flex}
#aiMsgs{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}
.msg{padding:10px 12px;border-radius:12px;font-size:13px;line-height:1.4;max-width:85%;white-space:pre-wrap}
.msg.user{align-self:flex-end;background:#ef4444;color:white}
.msg.ai{align-self:flex-start;background:#1e293b;border:1px solid #334155;color:#e2e8f0}
#aiInputRow{display:flex;gap:8px;padding:10px;border-top:1px solid #1e293b}
#aiInput{flex:1;background:#020617;border:1px solid #334155;color:white;padding:10px 12px;border-radius:20px;outline:none}
.chip{padding:6px 10px;background:#1e293b;border:1px solid #334155;border-radius:20px;font-size:11px;cursor:pointer}
.chip:hover{background:#334155}
.riskBar{margin:8px 12px;padding:10px 12px;background:#1e293b;border:1px solid #334155;border-radius:10px;font-size:11px;display:flex;justify-content:space-between;gap:8px}
</style></head><body>
<div class="header"><div class="logo">V64</div><div style="flex:1"><div style="font-weight:800">VENDI V64 <span style="background:#ef4444;color:white;padding:2px 6px;border-radius:6px;font-size:10px">REAL READY</span></div><div style="font-size:10px;color:#94a3b8">85% + confl 2/3 + Risk Guard + Diario</div></div><div style="display:flex;gap:6px"><button onclick="openAI()" style="background:#ef4444;color:white;border:none;padding:6px 10px;border-radius:20px;font-size:11px;font-weight:700">🤖 AI REAL</button><button onclick="openRisk()" style="background:#1e293b;color:white;border:1px solid #334155;padding:6px 10px;border-radius:20px;font-size:11px">⚙️ Risk</button></div></div>
<div id="banner" class="banner b-off">Verifico V64 REAL...</div>
<div id="riskBar" class="riskBar"><span id="riskMode">Mode: DEMO</span><span id="riskCap">Cap: $1000 1%</span><span id="riskDay">Oggi: 0/3</span><span><button onclick="openHistory()" style="background:#8b5cf6;color:white;border:none;padding:4px 8px;border-radius:10px;font-size:10px">📓 Diario</button></span></div>
<div class="tfs"><button id="b5m" class="active" onclick="loadTF('5m')">⚡ 5m</button><button id="b15m" onclick="loadTF('15m')">15m REAL</button><button id="b1H" onclick="loadTF('1H')">1H REAL</button><button onclick="loadTF(curTF,true,true)" style="background:#22c55e;color:#052e16">📱 Forza TG</button><button onclick="nuke()" style="background:#dc2626;color:white">💣 NUKE</button></div>
<div id="coins"><div style="padding:20px;text-align:center;color:#94a3b8">Carico V64 REAL...</div></div>

<div id="riskModal" class="modal" onclick="if(event.target==this)closeRisk()"><div class="box"><b>⚙️ Risk Guard - Soldi Veri</b><div style="font-size:11px;color:#94a3b8;margin:6px 0">DEMO = test senza limiti. REAL = protezione attiva: 85% minimo, confl 2/3, max trade/giorno, stop dopo perdite.</div>
<div style="display:grid;gap:10px;margin-top:10px">
<label style="font-size:12px">Modalità<br><select id="rMode" style="width:100%;padding:10px;background:#020617;color:white;border:1px solid #334155;border-radius:10px"><option value="DEMO">🟡 DEMO - Test</option><option value="REAL">🔴 REAL - Soldi veri con protezione</option></select></label>
<label style="font-size:12px">Capitale $ <input id="rCap" type="number" style="width:100%;padding:10px;background:#020617;color:white;border:1px solid #334155;border-radius:10px"></label>
<label style="font-size:12px">Rischio % a trade (0.5-3%) <input id="rRisk" type="number" step="0.1" style="width:100%;padding:10px;background:#020617;color:white;border:1px solid #334155;border-radius:10px"></label>
<label style="font-size:12px">Max trade al giorno <input id="rMaxT" type="number" style="width:100%;padding:10px;background:#020617;color:white;border:1px solid #334155;border-radius:10px"></label>
<label style="font-size:12px">Stop dopo N perdite di fila <input id="rMaxL" type="number" style="width:100%;padding:10px;background:#020617;color:white;border:1px solid #334155;border-radius:10px"></label>
</div>
<button class="btn btn-red" onclick="saveRisk()">💾 Salva Risk Guard</button><button class="btn" onclick="closeRisk()" style="background:#1e293b;color:white">Chiudi</button>
</div></div>

<div id="histModal" class="modal" onclick="if(event.target==this)closeHistory()"><div class="box"><b>📓 Diario Trade - Winrate Reale</b><div id="histStats" style="font-size:11px;background:#1e293b;padding:10px;border-radius:10px;margin:8px 0"></div><div id="histList" style="max-height:50vh;overflow:auto"></div><button class="btn" onclick="closeHistory()" style="background:#1e293b;color:white">Chiudi</button></div></div>

<div id="aiPanel"><div style="padding:12px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #1e293b"><b>🤖 AI Risk Manager - REAL</b><button onclick="closeAI()" style="background:#1e293b;color:white;border:none;padding:6px 10px;border-radius:10px">X</button></div>
<div id="aiMsgs"><div class="msg ai">Ciao! Sono l'AI Risk Manager V64. In modalità REAL non ti dico solo "compra", ti dico "con $1000 rischi $10, size 0.02 BTC, stop dopo 2 loss". Chiedimi: "devo entrare con soldi veri?", "calcola rischio", "diario winrate".</div>
<div style="display:flex;gap:6px;flex-wrap:wrap"><span class="chip" onclick="askChip('Devo entrare con soldi veri su BTC?')">Soldi veri BTC?</span><span class="chip" onclick="askChip('Calcola rischio')">Calcola rischio</span><span class="chip" onclick="askChip('Diario winrate')">Diario</span><span class="chip" onclick="askChip('Perché 5m perde e 15m vince?')">5m vs 15m</span></div>
</div>
<div id="aiInputRow"><input id="aiInput" placeholder="Soldi veri? Rischio? Diario?" onkeydown="if(event.key==='Enter')sendAI()"><button onclick="sendAI()" style="background:#ef4444;color:white;border:none;padding:10px 16px;border-radius:20px;font-weight:800">Invia</button></div>
</div>

<div id="modal" class="modal" onclick="if(event.target==this)closeM()"><div class="box"><div style="display:flex;justify-content:space-between"><b id="mCoin">BTC</b><button onclick="closeM()" style="background:#1e293b;color:white;border:none;padding:8px 12px;border-radius:10px">X</button></div><div id="mPrice" style="font-size:11px;color:#94a3b8;margin:6px 0"></div><div id="mBig" style="border-radius:14px;padding:16px;margin:10px 0;text-align:center;font-weight:900;font-size:20px"></div><div id="mExtra" style="font-size:11px;background:#1e293b;padding:10px;border-radius:10px;border:1px solid #334155;margin:8px 0"></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px"><div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">STOP LOSS</span><br><b id="mSL">-</b><br><span id="mSLpct" style="font-size:10px"></span></div><div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">TAKE PROFIT</span><br><b id="mTP">-</b><br><span id="mTPpct" style="font-size:10px"></span><br><span id="mRR" style="font-size:10px;color:#86efac"></span></div></div>
<div id="mRisk" style="font-size:11px;background:#7f1d1d;border:1px solid #ef4444;padding:10px;border-radius:10px;margin:8px 0;color:#fecaca"></div>
<button class="btn btn-green" onclick="copySLTP()">📋 Copia SL/TP</button><button class="btn btn-blue" onclick="openChart()">📈 TradingView</button><button class="btn btn-purple" onclick="askAboutCoin()">🤖 Chiedi AI Risk Manager</button><button class="btn btn-blue" onclick="sendNow()">📱 Manda Telegram ORA</button></div></div>

<script>
var curTF='5m';var lastData=null;var curCoin=null;var riskCfg=null;
function badge(c,l){if(c=='entra')return '<span class="badge badge-entra">'+l+'</span>';if(c=='quasi')return '<span class="badge badge-quasi">'+l+'</span>';return '<span class="badge badge-wait">'+l+'</span>';}
async function loadRisk(){try{let r=await fetch('/api/risk_config');let j=await r.json();riskCfg=j.risk;document.getElementById('riskMode').textContent='Mode: '+riskCfg.mode;document.getElementById('riskCap').textContent='Cap: $'+riskCfg.capital+' '+riskCfg.risk_pct+'%';document.getElementById('riskDay').textContent='Oggi: '+riskCfg.daily_trades+'/'+riskCfg.max_trades_day+' Loss row:'+riskCfg.daily_losses_row;document.getElementById('rMode').value=riskCfg.mode;document.getElementById('rCap').value=riskCfg.capital;document.getElementById('rRisk').value=riskCfg.risk_pct;document.getElementById('rMaxT').value=riskCfg.max_trades_day;document.getElementById('rMaxL').value=riskCfg.max_losses_row;let b=document.getElementById('banner');if(riskCfg.mode=='REAL'){b.className='banner banner-real';b.innerHTML='🔴 REAL MODE ON - 85% + confl 2/3 + Risk Guard '+riskCfg.daily_trades+'/'+riskCfg.max_trades_day+' - Attento ai soldi veri!';}else{b.className='banner b-on';b.innerHTML='🟡 DEMO MODE - Test senza limiti - Soglia 80% - Cooldown 10min';}}catch{}}
async function checkTG(){try{let r=await fetch('/api/telegram_config');let j=await r.json();await loadRisk();}catch{}}
async function nuke(){if(!confirm('NUKE storico e cooldown?'))return;try{let r=await fetch('/api/nuke');alert('✅ NUKE');checkTG();loadTF(curTF);}catch(e){alert(e.message);}}
async function loadTF(tf,withTG=false,force=false){
curTF=tf;
document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active'));
let el=document.getElementById('b'+tf); if(el) el.classList.add('active');
document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center;color:#94a3b8">⚡ Carico '+tf+' V64 REAL...</div>';
try{
let url='/api/signals?tf='+tf+(withTG?'&telegram=1':'')+(force?'&force=1':'');
let r=await fetch(url); let d=await r.json(); lastData=d; await loadRisk();
let html='';
for(let name in d.coins){
let info=d.coins[name];
let iclass=name=='BTC'?'btc':name=='ETH'?'eth':'oro';
let b=badge(info.quality_color, info.quality_label);
let price='$'+info.price.toFixed(2);
let action=info.quality_color=='entra'?(info.signal=='COMPRA'?'🚀 COMPRA ORA':'🔻 VENDI ORA'):'⏸️ Aspetta';
let conflBadge=info.confluence?` confl ${info.confluence}/3`:'';
html+=`<div class="coin"><div class="coin-row" onclick="openM('${name}')"><div style="display:flex;gap:10px;align-items:center"><div class="icon ${iclass}">${name=='BTC'?'B':name=='ETH'?'E':'Au'}</div><div><b>${name}</b> - ${price}<div style="font-size:11px;color:#94a3b8">${info.extra}</div><div style="font-size:11px;color:#64748b">${action}${conflBadge}</div></div></div><div style="text-align:right">${b}<div style="font-size:11px;color:#64748b;margin-top:4px">${info.signal} ${info.conf}%<br>SL ${info.sl_pct.toFixed(2)}% TP ${info.tp_pct.toFixed(2)}%<br>R:R 1:${info.rr}</div></div></div></div>`;
}
if(d.telegram_results && Object.keys(d.telegram_results).length>0){let block=JSON.stringify(d.telegram_results);if(block.includes('blocked')){html+=`<div style="background:#7f1d1d;padding:8px 12px;font-size:11px;color:#fecaca;text-align:center">⛔ Risk Guard ha bloccato: ${block}</div>`;}else{html+=`<div style="background:#052e16;padding:8px 12px;font-size:11px;color:#86efac;text-align:center">📱 TG: ${JSON.stringify(d.telegram_results)}</div>`;}}
document.getElementById('coins').innerHTML=html;
}catch(e){document.getElementById('coins').innerHTML='<div style="padding:20px;color:#ef4444">Errore: '+e.message+'</div>';}
}
function openM(coin){if(!lastData) return; let info=lastData.coins[coin]; curCoin=coin; document.getElementById('mCoin').textContent=coin+' - $'+info.price.toFixed(2); document.getElementById('mPrice').textContent=info.source+' - '+info.signal+' '+info.conf+'% - TF '+curTF+' confl '+info.confluence+'/3'; let big=document.getElementById('mBig'); big.style.cssText='border-radius:14px;padding:16px;margin:10px 0;text-align:center;font-weight:900;font-size:20px;'; if(info.quality_color=='entra'){big.style.background='#052e16';big.style.border='2px solid #22c55e';big.style.color='#22c55e';} else if(info.quality_color=='quasi'){big.style.background='#422006';big.style.border='2px solid #facc15';big.style.color='#facc15';} else{big.style.background='#1e293b';big.style.border='1px solid #334155';} big.innerHTML=info.quality_label+' - '+info.signal+' '+info.conf+'%'; document.getElementById('mSL').textContent='$'+info.sl.toFixed(2); document.getElementById('mSLpct').textContent='-'+info.sl_pct.toFixed(2)+'%'; document.getElementById('mTP').textContent='$'+info.tp.toFixed(2); document.getElementById('mTPpct').textContent='+'+info.tp_pct.toFixed(2)+'%'; document.getElementById('mRR').textContent='R:R 1:'+info.rr; document.getElementById('mExtra').textContent=info.extra; 
let riskDiv=document.getElementById('mRisk'); if(riskCfg){let riskMoney=riskCfg.capital*riskCfg.risk_pct/100;let size=riskMoney/(info.price*info.sl_pct/100);riskDiv.innerHTML=`💼 ${riskCfg.mode} - Cap $${riskCfg.capital} rischio ${riskCfg.risk_pct}% = $${riskMoney.toFixed(2)} → size ${size.toFixed(4)} ${coin}<br>Oggi ${riskCfg.daily_trades}/${riskCfg.max_trades_day} trade, ${riskCfg.daily_losses_row} loss di fila - ${riskCfg.mode=='REAL'?'🔴 SOLDI VERI - Attento!':'🟡 DEMO - Test'}`;}
document.getElementById('modal').classList.add('show');}
function closeM(){document.getElementById('modal').classList.remove('show');}
function copySLTP(){if(!curCoin||!lastData) return; let info=lastData.coins[curCoin]; let txt=`${curCoin} Entry ${info.price.toFixed(2)} SL ${info.sl.toFixed(2)} (${info.sl_pct.toFixed(2)}%) TP ${info.tp.toFixed(2)} (${info.tp_pct.toFixed(2)}%) R:R 1:${info.rr}`; navigator.clipboard.writeText(txt).then(()=>alert('Copiato: '+txt));}
function openChart(){if(!curCoin) return; let sym={BTC:'BINANCE:BTCUSDT',ETH:'BINANCE:ETHUSDT',ORO:'BINANCE:PAXGUSDT'}[curCoin]; window.open('https://www.tradingview.com/chart/?symbol='+sym,'_blank');}
async function sendNow(){if(!curCoin) return; try{let r=await fetch('/api/signals?tf='+curTF+'&telegram=1&force=1'); let j=await r.json(); alert('TG: '+JSON.stringify(j.telegram_results[curCoin]||j.telegram_results));}catch(e){alert(e.message);}}
async function testTG(){try{let r=await fetch('/api/telegram_test'); let j=await r.json(); alert(j.ok?'✅ Test V64 REAL!':'⛔ Bloccato da Risk Guard: '+(j.error||''));}catch(e){alert(e.message);}}

// AI CHAT
function openAI(){document.getElementById('aiPanel').classList.add('show');}
function closeAI(){document.getElementById('aiPanel').classList.remove('show');}
function askChip(t){document.getElementById('aiInput').value=t; sendAI();}
function askAboutCoin(){if(!curCoin) return; closeM(); openAI(); document.getElementById('aiInput').value='Devo entrare con soldi veri su '+curCoin+' '+curTF+'?'; sendAI();}
async function sendAI(){
 let input=document.getElementById('aiInput'); let txt=input.value.trim(); if(!txt) return;
 let msgs=document.getElementById('aiMsgs');
 let div=document.createElement('div'); div.className='msg user'; div.textContent=txt; msgs.appendChild(div);
 input.value=''; msgs.scrollTop=msgs.scrollHeight;
 try{
   let r=await fetch('/api/ai_chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:txt,coin:curCoin||'BTC',tf:curTF})});
   let j=await r.json();
   let ans=j.answer||j.error||'Errore AI';
   let div2=document.createElement('div'); div2.className='msg ai'; div2.textContent=ans; msgs.appendChild(div2);
   msgs.scrollTop=msgs.scrollHeight;
 }catch(e){
   let div2=document.createElement('div'); div2.className='msg ai'; div2.textContent='Errore: '+e.message; msgs.appendChild(div2);
 }
}
function openRisk(){document.getElementById('riskModal').classList.add('show');}
function closeRisk(){document.getElementById('riskModal').classList.remove('show');}
async function saveRisk(){
 let mode=document.getElementById('rMode').value;
 let cap=document.getElementById('rCap').value;
 let risk=document.getElementById('rRisk').value;
 let maxT=document.getElementById('rMaxT').value;
 let maxL=document.getElementById('rMaxL').value;
 try{
   let r=await fetch('/api/risk_config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:mode,capital:cap,risk_pct:risk,max_trades_day:maxT,max_losses_row:maxL})});
   let j=await r.json();
   alert('✅ Salvato: '+j.risk.mode+' $'+j.risk.capital+' '+j.risk.risk_pct+'%');
   closeRisk(); await loadRisk(); await loadTF(curTF);
 }catch(e){alert(e.message);}
}
function openHistory(){document.getElementById('histModal').classList.add('show'); loadHistory();}
function closeHistory(){document.getElementById('histModal').classList.remove('show');}
async function loadHistory(){
 try{
   let r=await fetch('/api/history');let j=await r.json();
   document.getElementById('histStats').textContent=`Totale ${j.total} - WIN ${j.wins} - LOSS ${j.losses} - Pending ${j.pending} - WR ${j.winrate}% - Per soldi veri serve 15m >60% su 30 giorni`;
   let list=document.getElementById('histList');let html='';
   j.history.slice().reverse().forEach((t,i)=>{
     let idx=j.history.length-1-i;
     let col=t.result=='WIN'?'#22c55e':t.result=='LOSS'?'#ef4444':'#94a3b8';
     html+=`<div style="display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid #1e293b;font-size:11px"><div><b>${t.coin} ${t.tf} ${t.signal} ${t.conf}%</b> $${t.entry?.toFixed(2)}<br><span style="color:#94a3b8">${t.time.slice(11,19)} ${t.mode}</span></div><div style="text-align:right"><span style="color:${col};font-weight:800">${t.result||'PENDING'}</span><br><button onclick="markTrade(${j.history.length-1-i},'WIN')" style="background:#052e16;color:#22c55e;border:1px solid #16a34a;padding:2px 6px;border-radius:6px;font-size:10px">WIN</button> <button onclick="markTrade(${j.history.length-1-i},'LOSS')" style="background:#450a0a;color:#ef4444;border:1px solid #dc2626;padding:2px 6px;border-radius:6px;font-size:10px">LOSS</button></div></div>`;
   });
   list.innerHTML=html||'<div style="padding:10px;color:#94a3b8">Nessun trade ancora</div>';
 }catch(e){alert(e.message);}
}
async function markTrade(idx,res){
 try{
   let r=await fetch('/api/history_mark',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({idx:idx,result:res})});
   let j=await r.json(); if(j.ok){loadHistory(); loadRisk();} else alert(j.error);
 }catch(e){alert(e.message);}
}

checkTG();loadTF('5m');setInterval(()=>loadTF(curTF),15000);
</script></body></html>
"""
    return Response(html, mimetype="text/html; charset=utf-8")

def bg_loop():
    while True:
        try:
            for tf in ["5m","15m","1H"]:
                for name in PAIRS.keys():
                    analyze(name, tf, do_tg=True)
        except Exception as e:
            print(f"Loop V64 {e}")
        time.sleep(60)

threading.Thread(target=bg_loop, daemon=True).start()
if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
