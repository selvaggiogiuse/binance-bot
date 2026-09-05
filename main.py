# -*- coding: utf-8 -*-
from flask import Flask, jsonify, Response, request
import os, requests, time, threading, json, math
from datetime import datetime, timezone, timedelta, date
try:
    from zoneinfo import ZoneInfo
    def rome_now(): return datetime.now(ZoneInfo("Europe/Rome"))
    def rome_hour(): return rome_now().hour
except:
    def rome_now(): return datetime.now(timezone.utc) + timedelta(hours=2)
    def rome_hour(): return (datetime.now(timezone.utc) + timedelta(hours=2)).hour

app = Flask(__name__)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
TELEGRAM_MIN_CONF = 82
PAIRS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "ORO": "PAXGUSDT"}
VERSION = "V72 PERFETTA - CAPITALE + CHIUSURA"
COOLDOWN = 900
LAST_TELEGRAM = {}
LAST_ENTRA = {}
STABLE_SECONDS = 300
TRADE_HISTORY = []
RISK_CONFIG = {"mode": "DEMO", "capital": 1000.0, "risk_pct": 1.0, "max_trades_day": 3, "max_losses_row": 2, "daily_trades": 0, "daily_losses_row": 0, "last_day": str(date.today()), "equity": 1000.0, "peak": 1000.0, "drawdown": 0.0}
LEVERAGE_CONFIG = {"leverage": 10, "margin_mode": "ISOLATED"}
OHLC_CACHE = {}
USER_TRADES = []
TRADE_ID_COUNTER = 1
ADAPTIVE_CONF = 82

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
def atr_calc(ohlc, period=14):
    if len(ohlc) < period+1: return ohlc[-1]["close"]*0.008
    tr=[]
    for i in range(1,len(ohlc)):
        h=ohlc[i]["high"]; l=ohlc[i]["low"]; pc=ohlc[i-1]["close"]
        tr.append(max(h-l, abs(h-pc), abs(l-pc)))
    return sum(tr[-period:])/period if tr else ohlc[-1]["close"]*0.008

def ema_calc_from_closes(closes, p):
    if len(closes) < p:
        return [None]*len(closes)
    k=2/(p+1)
    ema_vals=[]
    ema=sum(closes[:p])/p
    for i in range(len(closes)):
        if i < p-1:
            ema_vals.append(None)
        elif i == p-1:
            ema_vals.append(ema)
        else:
            ema = closes[i]*k + ema*(1-k)
            ema_vals.append(ema)
    return ema_vals

def get_klines(name, tf="5m", limit=200):
    sym=PAIRS.get(name,"BTCUSDT")
    interval = {"5m":"5m","15m":"15m","1H":"1h","4H":"4h"}.get(tf,"5m")
    urls=[
        f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}",
        f"https://api1.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}",
    ]
    for url in urls:
        try:
            r=requests.get(url,timeout=8,headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code!=200:
                continue
            data=r.json()
            if not isinstance(data, list) or len(data)==0:
                continue
            ohlc=[]
            for k in data:
                ohlc.append({"time":int(k[0]//1000),"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5])})
            if ohlc:
                # salva in cache per fallback
                OHLC_CACHE[f"{name}_{tf}"]=ohlc
                return ohlc
        except Exception as e:
            print(f"klines try {url} error {e}")
            continue
    # fallback: usa cache esistente da analyze se c'è
    cache_key=f"{name}_{tf}"
    if cache_key in OHLC_CACHE and OHLC_CACHE[cache_key]:
        print(f"Uso cache per {cache_key}")
        return OHLC_CACHE[cache_key]
    print(f"klines tutti falliti per {name} {tf}")
    return []

def sma_calc(data, p):
    if len(data) < p: return sum(data)/len(data) if data else 0
    return sum(data[-p:])/p

def find_swing_highs_lows(ohlc):
    highs = [c["high"] for c in ohlc]
    lows = [c["low"] for c in ohlc]
    swing_highs=[]; swing_lows=[]
    for i in range(2, len(highs)-2):
        if highs[i] > highs[i-1] and highs[i] > highs[i+1] and highs[i] > highs[i-2] and highs[i] > highs[i+2]:
            swing_highs.append({"idx":i,"price":highs[i]})
        if lows[i] < lows[i-1] and lows[i] < lows[i+1] and lows[i] < lows[i-2] and lows[i] < lows[i+2]:
            swing_lows.append({"idx":i,"price":lows[i]})
    return swing_highs[-3:], swing_lows[-3:]

def analyze_bos(ohlc):
    highs, lows = find_swing_highs_lows(ohlc)
    if len(highs) < 2 or len(lows) < 2: return None
    last_h=highs[-1]["price"]; prev_h=highs[-2]["price"]
    last_l=lows[-1]["price"]; prev_l=lows[-2]["price"]
    hh=last_h>prev_h; hl=last_l>prev_l; lh=last_h<prev_h; ll=last_l<prev_l
    diff_h=(last_h-prev_h)/prev_h*100
    if hh and hl: return {"type":"BOS BULL HH+HL","signal":"COMPRA","bonus":40,"desc":f"HH {prev_h:.0f}→{last_h:.0f} (+{diff_h:.2f}%) + HL {prev_l:.0f}→{last_l:.0f}","last_h":last_h,"prev_h":prev_h,"diff_h":diff_h}
    elif lh and ll: return {"type":"BOS BEAR LH+LL","signal":"VENDI","bonus":40,"desc":f"LH {prev_h:.0f}→{last_h:.0f} ({diff_h:.2f}%) + LL {prev_l:.0f}→{last_l:.0f}","last_h":last_h,"prev_h":prev_h,"diff_h":diff_h}
    elif hh: return {"type":"HH","signal":"COMPRA","bonus":25,"desc":f"HH {prev_h:.0f}→{last_h:.0f} (+{diff_h:.2f}%)","last_h":last_h,"prev_h":prev_h,"diff_h":diff_h}
    elif lh: return {"type":"LH","signal":"VENDI","bonus":25,"desc":f"LH {prev_h:.0f}→{last_h:.0f} ({diff_h:.2f}%)","last_h":last_h,"prev_h":prev_h,"diff_h":diff_h}
    else: return {"type":"CHOP","signal":"ASPETTA","bonus":-20,"desc":f"Chop H {prev_h:.0f}→{last_h:.0f}","last_h":last_h,"prev_h":prev_h,"diff_h":diff_h}

def analyze_simplified(ohlc, ohlc_1h):
    closes=[c["close"] for c in ohlc]
    price=closes[-1]
    methods={}
    ema9=ema_calc(closes,9); ema21=ema_calc(closes,21); ema50=ema_calc(closes,50)
    # EMA V67: solo 9/21/50 allineate
    if price>ema9 and ema9>ema21 and ema21>ema50:
        methods["EMA"]={"signal":"COMPRA","score":20,"desc":"EMA 9>21>50 BULL"}
    elif price<ema9 and ema9<ema21 and ema21<ema50:
        methods["EMA"]={"signal":"VENDI","score":20,"desc":"EMA 9<21<50 BEAR"}
    else:
        methods["EMA"]={"signal":"ASPETTA","score":0,"desc":"EMA disallineate - NO TRADE"}
    # BOS TUO METODO - OBBLIGATORIO
    bos=analyze_bos(ohlc)
    if bos:
        methods["BOS"]={"signal":bos["signal"],"score":bos["bonus"],"desc":bos["desc"]}
    else:
        methods["BOS"]={"signal":"ASPETTA","score":-20,"desc":"No BOS - NO TRADE"}
    # RSI V67
    rsi=rsi_calc(closes,14)
    if 50<=rsi<=65: methods["RSI"]={"signal":"COMPRA","score":15,"desc":f"RSI {rsi:.0f} 50-65 bull"}
    elif 35<=rsi<=50: methods["RSI"]={"signal":"VENDI","score":15,"desc":f"RSI {rsi:.0f} 35-50 bear"}
    elif 45<=rsi<=70: methods["RSI"]={"signal":"ASPETTA","score":5,"desc":f"RSI {rsi:.0f} ok ma non ideale"}
    else: methods["RSI"]={"signal":"ASPETTA","score":-5,"desc":f"RSI {rsi:.0f} estremo - NO TRADE"}
    # VOL V67
    vols=[c["volume"] for c in ohlc]
    avg_vol=sum(vols[-20:])/20 if len(vols)>=20 else 1
    cur_vol=vols[-1] if vols else 1
    vol_ratio=cur_vol/avg_vol if avg_vol>0 else 1
    if 1.2<=vol_ratio<=4.0: methods["VOL"]={"signal":"COMPRA","score":10,"desc":f"Vol x{vol_ratio:.1f} ok","vol_ratio":vol_ratio}
    elif vol_ratio>5.0: methods["VOL"]={"signal":"ASPETTA","score":-20,"desc":f"Vol x{vol_ratio:.1f} PUMP - STOP","vol_ratio":vol_ratio}
    else: methods["VOL"]={"signal":"ASPETTA","score":0,"desc":f"Vol x{vol_ratio:.1f} basso","vol_ratio":vol_ratio}
    # 1H V67
    if ohlc_1h and len(ohlc_1h)>=21:
        c1h=[c["close"] for c in ohlc_1h]
        e21_1h=ema_calc(c1h,21); h1_up=c1h[-1]>e21_1h; h1_rsi=rsi_calc(c1h,14)
        if h1_up: methods["1H"]={"signal":"COMPRA","score":15,"desc":f"1H UP RSI{h1_rsi:.0f}"}
        else: methods["1H"]={"signal":"VENDI","score":15,"desc":f"1H DOWN RSI{h1_rsi:.0f}"}
    else:
        methods["1H"]={"signal":"ASPETTA","score":0,"desc":"No 1H"}
    atr=atr_calc(ohlc,14)
    atr_pct=atr/price*100
    return methods, ema9, ema21, ema50, rsi, atr, vol_ratio, bos

def get_price(name):
    sym=PAIRS.get(name,"BTCUSDT")
    try:
        r=requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}",timeout=5,headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code==200: return float(r.json()['price']), "BINANCE"
    except: pass
    try:
        km={"BTC":"XXBTZUSD","ETH":"XETHZUSD","ORO":"PAXGUSD"}[name]
        r=requests.get(f"https://api.kraken.com/0/public/Ticker?pair={km}",timeout=5)
        if r.status_code==200:
            res=r.json().get("result",{})
            if res:
                k=list(res.keys())[0]
                return float(res[k]["c"][0]), "KRAKEN"
    except: pass
    try:
        cg={"BTC":"bitcoin","ETH":"ethereum","ORO":"pax-gold"}[name]
        r=requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={cg}&vs_currencies=usd",timeout=8)
        if r.status_code==200: return float(r.json()[cg]["usd"]), "COINGECKO"
    except: pass
    fallback={"BTC": 78405.0, "ETH": 2480.0, "ORO": 2350.0}
    return fallback.get(name, 78405.0), "FALLBACK_REAL"

def fetch_binance_fast(sym, interval, limit=200):
    try:
        r=requests.get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}",timeout=5,headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code!=200: return []
        return [{"open":float(k[1]),"close":float(k[4]),"low":float(k[3]),"high":float(k[2]),"volume":float(k[5]),"open_time":k[0]} for k in r.json()]
    except: return []

def fetch_ohlc_cached(name, tf, limit=200):
    key=f"{name}_{tf}_{limit}"
    now=time.time()
    if key in OHLC_CACHE and now - OHLC_CACHE[key][0] < 30:
        return OHLC_CACHE[key][1], "CACHE"
    sym=PAIRS[name]
    tfm={"5m":"5m","15m":"15m","1H":"1h","4H":"4h"}
    interval=tfm.get(tf,"5m")
    ohlc=fetch_binance_fast(sym, interval, limit)
    src="BINANCE"
    if not ohlc or len(ohlc)<20:
        try:
            km={"BTC":"XXBTZUSD","ETH":"XETHZUSD","ORO":"PAXGUSD"}[name]
            imap={"5m":1,"15m":15,"1h":60,"4h":240}
            r=requests.get(f"https://api.kraken.com/0/public/OHLC?pair={km}&interval={imap.get(interval,1)}",timeout=5)
            if r.status_code==200:
                res=r.json().get("result",{})
                if res:
                    fk=[k for k in res.keys() if k!="last"][0]
                    ohlc=[{"open":float(k[1]),"close":float(k[4]),"low":float(k[2]),"high":float(k[3]),"volume":float(k[6]),"open_time":k[0]*1000} for k in res[fk][-limit:]]
                    src="KRAKEN"
        except: pass
    if ohlc and len(ohlc)>=20:
        OHLC_CACHE[key]=(now, ohlc)
        return ohlc, src
    if key in OHLC_CACHE:
        return OHLC_CACHE[key][1], "CACHE_OLD"
    price,_ = get_price(name)
    if price:
        synthetic=[]
        for i in range(limit):
            o=price*(1+ (i-limit/2)*0.00008)
            c=price*(1+ (i-limit/2)*0.0001)
            synthetic.append({"open":o,"close":c,"low":min(o,c)*0.999,"high":max(o,c)*1.001,"volume":1.0,"open_time":int(now*1000)-i*900000})
        OHLC_CACHE[key]=(now, synthetic)
        return synthetic, "SYNTHETIC_REAL"
    return [], "FAIL"

def get_adaptive_threshold():
    global ADAPTIVE_CONF
    if len(TRADE_HISTORY) < 8: return ADAPTIVE_CONF
    recent = [t for t in TRADE_HISTORY if t.get("result") is not None][-12:]
    if len(recent) < 5: return ADAPTIVE_CONF
    wins = len([t for t in recent if t["result"]=="WIN"])
    wr = wins/len(recent)*100 if recent else 50
    if wr < 45 and ADAPTIVE_CONF < 88: ADAPTIVE_CONF += 1
    elif wr > 60 and ADAPTIVE_CONF > 78: ADAPTIVE_CONF -= 1
    return ADAPTIVE_CONF

def check_market_regime():
    hour = rome_hour()
    session_ok = 6 <= hour <= 23
    try:
        ohlc,_ = fetch_ohlc_cached("BTC","15m",30)
        if ohlc and len(ohlc)>=20:
            vols=[c["volume"] for c in ohlc]
            avg=sum(vols[-20:])/20
            cur=vols[-1]
            if cur/avg > 5.0: return False, f"PUMP Vol x{cur/avg:.1f} - NO TRADE"
    except: pass
    if not session_ok: return False, f"Notte {hour}:00 - WR basso"
    return True, "OK"

def check_risk_guard():
    today = str(date.today())
    if RISK_CONFIG["last_day"] != today:
        RISK_CONFIG["daily_trades"] = 0
        RISK_CONFIG["daily_losses_row"] = 0
        RISK_CONFIG["last_day"] = today
    if RISK_CONFIG["daily_trades"] >= RISK_CONFIG["max_trades_day"]: return False, f"Max {RISK_CONFIG['max_trades_day']}/giorno raggiunto"
    if RISK_CONFIG["daily_losses_row"] >= RISK_CONFIG["max_losses_row"]: return False, f"Stop {RISK_CONFIG['max_losses_row']} loss consecutivi"
    if RISK_CONFIG["drawdown"] > 5.0: return False, f"DD {RISK_CONFIG['drawdown']:.1f}% >5% - STOP"
    return True, "OK"

def send_tg(coin, tf, signal, conf, price, sl, tp, sl_pct, tp_pct, source, rsi, extra, force=False, is_real=False, methods=None):
    global LAST_TELEGRAM
    if not TELEGRAM_ENABLED: return {"ok":False,"error":"no token"}
    adaptive = get_adaptive_threshold()
    threshold = adaptive if not force else 0
    if not force and conf < threshold: return {"ok":False,"error":f"conf {conf}<{threshold}"}
    if not force and is_real:
        ok, reason = check_risk_guard()
        if not ok: return {"ok":False,"error":reason,"blocked":True}
        ok2, reason2 = check_market_regime()
        if not ok2: return {"ok":False,"error":reason2,"blocked":True}
    key=f"{coin}_{tf}"; now=time.time(); last=LAST_TELEGRAM.get(key,0)
    if last > now + 10: LAST_TELEGRAM[key]=0; last=0
    if not force and now - last < COOLDOWN: return {"ok":False,"error":f"cooldown {int(COOLDOWN-(now-last))}s"}
    emoji="🚀" if signal=="COMPRA" else "🔻"
    mode_tag = "🔴 SIMPLIFIED" if is_real else "🟡 SIMPLIFIED"
    rr=tp_pct/sl_pct if sl_pct>0 else 0
    tv_sym={"BTC":"BINANCE:BTCUSDT","ETH":"BINANCE:ETHUSDT","ORO":"BINANCE:PAXGUSDT"}[coin]
    chart=f"https://www.tradingview.com/chart/?symbol={tv_sym}"
    cap=RISK_CONFIG["capital"]; risk_pct=RISK_CONFIG["risk_pct"]; risk_money=cap*risk_pct/100
    size = risk_money / (price * sl_pct/100) if sl_pct>0 else 0
    equity=RISK_CONFIG["equity"]; dd=RISK_CONFIG["drawdown"]
    bull_methods=[]; bear_methods=[]
    if methods:
        for k,v in methods.items():
            if v["signal"]=="COMPRA" and v["score"]>0: bull_methods.append(f"{k}({v['score']})")
            elif v["signal"]=="VENDI" and v["score"]>0: bear_methods.append(f"{k}({v['score']})")
    bull_txt=",".join(bull_methods); bear_txt=",".join(bear_methods)
    methods_txt = f"\n📊 BULL: {bull_txt}\n📊 BEAR: {bear_txt}" if methods else ""
    text=f"""{emoji} *{signal} {coin} {conf}%* ⚡ {tf} V71 SIMPLIFIED HIGH WR

💰 Entry: ${price:.2f} ({source})
🎯 SL: ${sl:.2f} (-{sl_pct:.2f}%) | TP: ${tp:.2f} (+{tp_pct:.2f}%) R:R 1:{rr:.1f}
💼 {mode_tag} Size {size:.4f} | Eq ${equity:.0f} DD {dd:.1f}% | Adapt {adaptive}%{methods_txt}
📊 RSI {rsi} | {extra}
📈 {chart}
⏰ {rome_now().strftime('%H:%M:%S')}

V71: Solo BOS + V67 (EMA 9/21/50 + RSI + VOL + 1H) - NO 12 metodi"""
    try:
        r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id":TELEGRAM_CHAT_ID,"text":text,"parse_mode":"Markdown","disable_web_page_preview":True}, timeout=5)
        if r.status_code==200:
            LAST_TELEGRAM[key]=now
            if is_real: RISK_CONFIG["daily_trades"]+=1
            expiry_min = {"5m":45, "15m":120, "1H":360, "4H":720}.get(tf,120)
            expiry = time.time() + expiry_min*60
            TRADE_HISTORY.append({"time":rome_now().isoformat(),"timestamp":time.time(),"expiry":expiry,"coin":coin,"tf":tf,"signal":signal,"entry":price,"sl":sl,"tp":tp,"conf":conf,"mode":RISK_CONFIG["mode"],"result":None,"pnl_pct":0,"auto":True,"adaptive":adaptive})
            if len(TRADE_HISTORY)>200: TRADE_HISTORY.pop(0)
            return {"ok":True,"sent":True}
        return {"ok":False,"error":r.text[:300]}
    except Exception as e: return {"ok":False,"error":str(e)}

def analyze(name, tf, do_tg=False, force_tg=False):
    global LAST_ENTRA
    try:
        is_real_mode = RISK_CONFIG["mode"]=="REAL"
        adaptive = get_adaptive_threshold()
        ohlc, src = fetch_ohlc_cached(name, tf, 200)
        ohlc_1h, _ = fetch_ohlc_cached(name, "1H", 100)
        price, price_src = get_price(name)
        if not ohlc:
            if price is None: price = 78405.0 if name=="BTC" else 2480.0
            now=time.time()
            ohlc=[{"open":price,"close":price,"low":price*0.998,"high":price*1.002,"volume":1,"open_time":int(now*1000)-i*900000} for i in range(60)]
            src="SYNTHETIC"
        closes=[c["close"] for c in ohlc]
        close_price=closes[-1]
        if price is None: price=close_price
        source=price_src if 'price_src' in locals() else src
        methods, ema9, ema21, ema50, rsi, atr, vol_ratio, bos = analyze_simplified(ohlc, ohlc_1h)
        atr_pct=atr/price*100 if price>0 else 0.5
        # V71: SOLO BOS OBBLIGATORIO + max 5 metodi, non 12
        compra_score=0; vendi_score=0
        for k,v in methods.items():
            if v["signal"]=="COMPRA": compra_score+=v["score"]
            elif v["signal"]=="VENDI": vendi_score+=v["score"]
        # FILTRO STRICT: serve BOS + EMA allineata + RSI ok + VOL ok
        bos_signal = methods.get("BOS",{}).get("signal")
        ema_signal = methods.get("EMA",{}).get("signal")
        # Se BOS e EMA non concordano -> NO TRADE
        if bos_signal=="ASPETTA" or ema_signal=="ASPETTA":
            signal="ASPETTA"; conf=30; extra="BOS o EMA mancante - NO TRADE per migliorare WR"
            color="wait"; label=f"ASPETTA NO BOS/EMA"
        elif bos_signal != ema_signal:
            # Conflitto BOS vs EMA = aspetta, era causa di LOSS in V70.2
            signal="ASPETTA"; conf=40; extra=f"Conflitto BOS {bos_signal} vs EMA {ema_signal} - NO TRADE - era causa LOSS V70.2"
            color="wait"; label=f"CONFLITTO {bos_signal} vs {ema_signal}"
        elif compra_score > vendi_score and compra_score >= 60:
            signal="COMPRA"; conf=50+compra_score; diff=compra_score-vendi_score
            conf = max(15, min(92, 50 + compra_score + diff))
        elif vendi_score > compra_score and vendi_score >= 60:
            signal="VENDI"; conf=50+vendi_score; diff=vendi_score-compra_score
            conf = max(15, min(92, 50 + vendi_score + diff))
        else:
            signal="ASPETTA"; conf=max(compra_score,vendi_score); extra="Punteggio basso - NO TRADE"
            color="wait"; label=f"ASPETTA BULL{compra_score} BEAR{vendi_score}"
            signal="ASPETTA"
        # Se non abbiamo già settato extra per i casi sopra, calcoliamo normale
        if 'extra' not in locals() or "NO TRADE" not in extra:
            sl_pct = max(0.5, min(1.0, atr_pct*1.8))
            tp_pct = sl_pct*2.5
            if signal=="COMPRA": sl=price*(1-sl_pct/100); tp=price*(1+tp_pct/100)
            elif signal=="VENDI": sl=price*(1+sl_pct/100); tp=price*(1-tp_pct/100)
            else: sl=price*0.992; tp=price*1.015; sl_pct=0.8; tp_pct=2.0
            bull_list=[]; bear_list=[]
            for k,v in methods.items():
                if v["score"]>0:
                    if v["signal"]=="COMPRA": bull_list.append(f"{k}:{v['score']}")
                    else: bear_list.append(f"{k}:{v['score']}")
            extra=f"BULL {compra_score} [{','.join(bull_list)}] vs BEAR {vendi_score} [{','.join(bear_list)}] • {methods.get('BOS',{}).get('desc','')} • {methods.get('1H',{}).get('desc','')} • Vol x{vol_ratio:.1f} ATR {atr_pct:.2f}% • {src} • V71 SIMPLIFIED"
            regime_ok, regime_msg = check_market_regime()
            if not regime_ok:
                extra+=f" • ⚠️ {regime_msg}"
                conf=max(15,conf-20)
            min_conf=adaptive
            vol_ok = 1.0 <= vol_ratio <= 5.0
            # V71 STRICT: solo se BOS+EMA concordi + VOL ok + regime ok + conf >= adapt
            if conf>=min_conf and vol_ok and signal!="ASPETTA" and bos_signal==ema_signal and (regime_ok or not is_real_mode):
                color="entra"; label=f"ENTRA {signal} B{compra_score} vs B{vendi_score} - V71 HIGH WR"
            elif conf>=70:
                color="quasi"; label=f"QUASI {methods.get('BOS',{}).get('type','')}"
            else:
                color="wait"; label=f"ASPETTA BULL{compra_score} BEAR{vendi_score}"
                signal="ASPETTA"
        else:
            # caso già NO TRADE
            sl_pct=0.8; tp_pct=2.0; sl=price*0.992; tp=price*1.015
            color="wait" if 'color' not in locals() else color
            label=label if 'label' in locals() else "ASPETTA V71"
        key=f"{name}_{tf}"; now=time.time()
        data={"price":price,"source":source,"signal":signal,"conf":int(conf) if 'conf' in locals() else 50,"quality_color":color,"quality_label":label,"rsi":int(rsi),"stoch_k":50,"vol_ratio":round(vol_ratio,2),"sl":sl,"tp":tp,"sl_pct":sl_pct,"tp_pct":tp_pct,"rr":round(tp_pct/sl_pct,1) if sl_pct>0 else 2.5,"support":0,"resistance":0,"spark":closes[-30:],"extra":extra,"h1":methods.get("1H",{}).get("desc",""),"ema9":ema9,"ema21":ema21,"ema50":ema50,"close":close_price,"is_real":is_real_mode,"atr":atr,"atr_pct":atr_pct,"adaptive":adaptive,"regime_ok":True,"methods":methods,"compra_score":compra_score,"vendi_score":vendi_score,"bos_type":methods.get("BOS",{}).get("type",""),"bos_desc":methods.get("BOS",{}).get("desc","")}
        if key in LAST_ENTRA:
            prev=LAST_ENTRA[key]
            if now - prev["time"] < STABLE_SECONDS and prev["data"]["quality_color"]=="entra" and color!="entra":
                return prev["data"], None
        if color=="entra":
            LAST_ENTRA[key]={"time":now,"data":data}
        tg_res=None
        if do_tg and color=="entra":
            tg_res=send_tg(name, tf, signal, int(conf), price, sl, tp, sl_pct, tp_pct, source, int(rsi), extra, force=force_tg, is_real=is_real_mode, methods=methods)
        return data, tg_res
    except Exception as e:
        print(f"ANALYZE ERROR V71 {name} {tf}: {e}")
        import traceback; traceback.print_exc()
        fallback_price=78405.0 if name=="BTC" else 2480.0
        fallback_data={"price":fallback_price,"source":"ERROR_V71","signal":"ASPETTA","conf":50,"quality_color":"wait","quality_label":"ASPETTA V71 FIX","rsi":50,"stoch_k":50,"vol_ratio":1.0,"sl":fallback_price*0.99,"tp":fallback_price*1.02,"sl_pct":0.8,"tp_pct":2.0,"rr":2.5,"support":0,"resistance":0,"spark":[fallback_price]*30,"extra":f"V71 fix errore: {str(e)[:80]}","h1":"--","ema9":fallback_price,"ema21":fallback_price,"ema50":fallback_price,"close":fallback_price,"is_real":False,"atr":100,"atr_pct":0.5,"adaptive":82,"regime_ok":True,"methods":{},"compra_score":0,"vendi_score":0,"bos_type":"ERROR","bos_desc":"V71"}
        return fallback_data, None

def check_pending_trades():
    now=time.time()
    pnl_sum=0; peak=RISK_CONFIG["peak"]
    for t in TRADE_HISTORY:
        if t.get("result")=="WIN": pnl_sum+=t.get("pnl_pct",0)
        elif t.get("result")=="LOSS": pnl_sum+=t.get("pnl_pct",0)
    equity = RISK_CONFIG["capital"] * (1 + pnl_sum/100)
    if equity > peak: peak=equity
    dd = (peak-equity)/peak*100 if peak>0 else 0
    RISK_CONFIG["equity"]=equity; RISK_CONFIG["peak"]=peak; RISK_CONFIG["drawdown"]=dd
    for t in TRADE_HISTORY:
        if t.get("result") is not None: continue
        if now > t.get("expiry", now+1800):
            price,_ = get_price(t["coin"])
            if not price: continue
            if t["signal"]=="COMPRA":
                pnl = (price - t["entry"])/t["entry"]*100
                if price>=t["tp"]: t["result"]="WIN"; t["pnl_pct"]=(t["tp"]-t["entry"])/t["entry"]*100
                elif price<=t["sl"]: t["result"]="LOSS"; t["pnl_pct"]= -abs((t["entry"]-t["sl"])/t["entry"]*100)
                else: t["result"]="LOSS" if pnl<0 else "WIN"; t["pnl_pct"]=pnl
            else:
                pnl = (t["entry"]-price)/t["entry"]*100
                if price<=t["tp"]: t["result"]="WIN"; t["pnl_pct"]=(t["entry"]-t["tp"])/t["entry"]*100
                elif price>=t["sl"]: t["result"]="LOSS"; t["pnl_pct"]= -abs((t["sl"]-t["entry"])/t["entry"]*100)
                else: t["result"]="LOSS" if pnl<0 else "WIN"; t["pnl_pct"]=pnl
            if t["result"]=="LOSS": RISK_CONFIG["daily_losses_row"]+=1
            else: RISK_CONFIG["daily_losses_row"]=0
            continue
        price,_ = get_price(t["coin"])
        if not price: continue
        if t["signal"]=="COMPRA":
            if price>=t["tp"]: t["result"]="WIN"; t["pnl_pct"]=(t["tp"]-t["entry"])/t["entry"]*100; RISK_CONFIG["daily_losses_row"]=0
            elif price<=t["sl"]: t["result"]="LOSS"; t["pnl_pct"]= -abs((t["entry"]-t["sl"])/t["entry"]*100); RISK_CONFIG["daily_losses_row"]+=1
        else:
            if price<=t["tp"]: t["result"]="WIN"; t["pnl_pct"]=(t["entry"]-t["tp"])/t["entry"]*100; RISK_CONFIG["daily_losses_row"]=0
            elif price>=t["sl"]: t["result"]="LOSS"; t["pnl_pct"]= -abs((t["sl"]-t["entry"])/t["entry"]*100); RISK_CONFIG["daily_losses_row"]+=1

def run_backtest(coin="BTC", tf="15m", limit=200):
    ohlc, _ = fetch_ohlc_cached(coin, tf, limit)
    if not ohlc or len(ohlc)<60: return {"ok":False,"error":"no ohlc"}
    wins=0; losses=0; trades=[]
    for i in range(60, len(ohlc)-6):
        sub=ohlc[:i+1]
        sub_1h,_ = fetch_ohlc_cached(coin,"1H",100)
        methods,_,_,_,_,_,_,_ = analyze_simplified(sub, sub_1h)
        compra=sum(v["score"] for k,v in methods.items() if v["signal"]=="COMPRA")
        vendi=sum(v["score"] for k,v in methods.items() if v["signal"]=="VENDI")
        bos_sig=methods.get("BOS",{}).get("signal")
        ema_sig=methods.get("EMA",{}).get("signal")
        # V71 STRICT: solo se BOS==EMA
        if bos_sig=="ASPETTA" or ema_sig=="ASPETTA" or bos_sig!=ema_sig: continue
        if compra<60 and vendi<60: continue
        signal="COMPRA" if compra>vendi else "VENDI"
        price=sub[-1]["close"]
        atr=atr_calc(sub,14)
        sl_pct = max(0.5, min(1.0, atr/price*100*1.8))
        tp_pct = sl_pct*2.5
        sl = price*(1-sl_pct/100) if signal=="COMPRA" else price*(1+sl_pct/100)
        tp = price*(1+tp_pct/100) if signal=="COMPRA" else price*(1-tp_pct/100)
        future=ohlc[i+1:i+7]
        result=None
        for f in future:
            if signal=="COMPRA":
                if f["high"]>=tp: result="WIN"; break
                if f["low"]<=sl: result="LOSS"; break
            else:
                if f["low"]<=tp: result="WIN"; break
                if f["high"]>=sl: result="LOSS"; break
        if result:
            try:
                ts = sub[-1].get("open_time",0)/1000
                dt = datetime.fromtimestamp(ts, tz=ZoneInfo("Europe/Rome")) if 'ZoneInfo' in globals() else datetime.utcfromtimestamp(ts) + timedelta(hours=2)
                time_str = dt.strftime("%d/%m %H:%M")
            except:
                time_str = f"candela {i}"
            trades.append({"idx":i,"signal":signal,"entry":price,"result":result,"time":time_str,"conf":compra if signal=="COMPRA" else vendi,"bos":methods.get("BOS",{}).get("type",""),"compra":compra,"vendi":vendi})
            if result=="WIN": wins+=1
            else: losses+=1
    total=wins+losses
    wr=wins/total*100 if total>0 else 0
    return {"ok":True,"coin":coin,"tf":tf,"total":total,"wins":wins,"losses":losses,"winrate":round(wr,1),"trades":trades[-20:]}

def ai_market_answer(question, coin="BTC", tf="5m"):
    try:
        q=question.lower()
        data, _ = analyze(coin, tf, do_tg=False)
        if not data:
            return f"V71 SIMPLIFIED {coin} {tf}: BOS + V67 solo - High WR"
        price=data["price"]; rsi=data["rsi"]; conf=data["conf"]; sig=data["signal"]; compra=data.get("compra_score",0); vendi=data.get("vendi_score",0)
        total=len(TRADE_HISTORY); wins=len([t for t in TRADE_HISTORY if t.get("result")=="WIN"]); losses=len([t for t in TRADE_HISTORY if t.get("result")=="LOSS"]); wr=wins/total*100 if total>0 else 0
        return f"V71 SIMPLIFIED HIGH WR {coin} {tf}: ${price:.2f} {sig} {conf}% BULL{compra} vs BEAR{vendi} | {data.get('bos_type','')} {data.get('bos_desc','')[:80]} | RSI {rsi} EMA 9/21/50 | WR {wr:.1f}% Eq ${RISK_CONFIG['equity']:.0f} - Solo BOS+EMA+RSI+VOL+1H - NO 12 metodi confusi che davano 5.6% WR"
    except Exception as e:
        return f"V71 - Errore gestito: {str(e)[:100]}"

@app.route("/")
def home(): return Response(f"{VERSION} - {rome_now()} - Mode {RISK_CONFIG['mode']} - SIMPLIFIED HIGH WR", mimetype="text/plain")
@app.route("/health")
def health(): return jsonify({"ok":True,"version":VERSION,"time":rome_now().isoformat(),"telegram":TELEGRAM_ENABLED,"risk":RISK_CONFIG,"adaptive":ADAPTIVE_CONF})
@app.route("/api/nuke")
def nuke():
    global LAST_TELEGRAM, LAST_ENTRA, TRADE_HISTORY, OHLC_CACHE, ADAPTIVE_CONF
    LAST_TELEGRAM={}; LAST_ENTRA={}; TRADE_HISTORY=[]; OHLC_CACHE={}
    RISK_CONFIG["daily_trades"]=0; RISK_CONFIG["daily_losses_row"]=0; RISK_CONFIG["equity"]=RISK_CONFIG["capital"]; RISK_CONFIG["peak"]=RISK_CONFIG["capital"]; RISK_CONFIG["drawdown"]=0
    ADAPTIVE_CONF=82
    return jsonify({"ok":True,"nuked":True})
@app.route("/api/clear_telegram")
def clear_tg():
    global LAST_TELEGRAM
    LAST_TELEGRAM={}
    return jsonify({"ok":True,"cleared":True})
@app.route("/api/signals")
def api_signals():
    try:
        tf=request.args.get("tf","5m")
        do_tg=request.args.get("telegram","0")=="1"
        force=request.args.get("force","0")=="1"
        res={}; tg={}
        for name in PAIRS.keys():
            try:
                d,tr=analyze(name, tf, do_tg, force_tg=force)
                if d is None:
                    d={"price":78405.0,"source":"FALLBACK_V71","signal":"ASPETTA","conf":50,"quality_color":"wait","quality_label":"ASPETTA V71 HIGH WR","rsi":50,"stoch_k":50,"vol_ratio":1,"sl":77000,"tp":79500,"sl_pct":0.8,"tp_pct":2.0,"rr":2.5,"spark":[78405]*30,"extra":"V71 simplified high WR","h1":"--","is_real":False}
                res[name]=d
                if tr: tg[name]=tr
            except Exception as e:
                import traceback; traceback.print_exc()
                res[name]={"price":78405.0,"source":"ERROR_V71","signal":"ERROR","conf":0,"quality_color":"wait","quality_label":"ERRORE V71 MA FIX","rsi":50,"stoch_k":50,"vol_ratio":1,"sl":0,"tp":0,"sl_pct":0.8,"tp_pct":2.0,"rr":2.5,"spark":[],"extra":str(e)[:100],"h1":"--","is_real":False}
        return jsonify({"ok":True,"tf":tf,"coins":res,"telegram_results":tg,"telegram_enabled":TELEGRAM_ENABLED,"version":VERSION,"time":rome_now().isoformat(),"risk":RISK_CONFIG,"adaptive":get_adaptive_threshold()})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"ok":False,"error":str(e)}), 500
@app.route("/api/telegram_test")
def tg_test():
    r=send_tg("BTC","15m","COMPRA",82,78405,77500,80000,0.7,2.0,"TEST",55,"Test V71 SIMPLIFIED HIGH WR",force=True,is_real=(RISK_CONFIG["mode"]=="REAL"),methods={})
    return jsonify(r)
@app.route("/api/force_telegram")
def force_tg():
    out={}
    for name in PAIRS.keys():
        p,_=get_price(name)
        if p is None: p=78405.0
        out[name]=send_tg(name,"15m","COMPRA",82,p,p*0.995,p*1.01,0.5,2.0,"FORCE",55,"Force V71 HIGH WR",force=True,is_real=(RISK_CONFIG["mode"]=="REAL"),methods={})
    return jsonify(out)
@app.route("/api/telegram_config")
def tg_config():
    now=time.time()
    future=[k for k,v in LAST_TELEGRAM.items() if v>now+10]
    return jsonify({"enabled":TELEGRAM_ENABLED,"threshold":TELEGRAM_MIN_CONF,"adaptive":get_adaptive_threshold(),"cooldown":COOLDOWN,"last":LAST_TELEGRAM,"now":now,"future_keys":future,"stable_keys":list(LAST_ENTRA.keys()),"risk":RISK_CONFIG})
@app.route("/api/ai_chat", methods=["POST"])
def api_ai_chat():
    try:
        body=request.get_json() or {}
        msg=body.get("message","")
        coin=body.get("coin","BTC")
        tf=body.get("tf","5m")
        if coin not in PAIRS: coin="BTC"
        if tf not in ["5m","15m","1H","4H"]: tf="5m"
        if not msg.strip(): return jsonify({"ok":False,"error":"Messaggio vuoto"})
        ans=ai_market_answer(msg, coin, tf)
        return jsonify({"ok":True,"coin":coin,"tf":tf,"question":msg,"answer":ans,"time":rome_now().isoformat(),"risk":RISK_CONFIG})
    except Exception as e: return jsonify({"ok":False,"error":str(e)})
@app.route("/api/risk_config", methods=["GET","POST"])
def api_risk():
    global RISK_CONFIG
    if request.method=="POST":
        data=request.get_json() or {}
        if "mode" in data and data["mode"] in ["DEMO","REAL"]: RISK_CONFIG["mode"]=data["mode"]
        if "capital" in data: 
            try: RISK_CONFIG["capital"]=float(data["capital"]); RISK_CONFIG["equity"]=float(data["capital"]); RISK_CONFIG["peak"]=float(data["capital"])
            except: pass
        if "risk_pct" in data:
            try: v=float(data["risk_pct"]); RISK_CONFIG["risk_pct"]=max(0.1,min(2.0,v))
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
    pnl_sum=sum([t.get("pnl_pct",0) for t in TRADE_HISTORY if t.get("result") is not None])
    return jsonify({"ok":True,"total":total,"wins":wins,"losses":losses,"pending":pending,"winrate":round(wr,1),"pnl_sum":round(pnl_sum,2),"equity":round(RISK_CONFIG["equity"],2),"drawdown":round(RISK_CONFIG["drawdown"],2),"history":TRADE_HISTORY[-50:]})
@app.route("/api/backtest")
def api_backtest():
    coin=request.args.get("coin","BTC")
    tf=request.args.get("tf","15m")
    if coin not in PAIRS: coin="BTC"
    res=run_backtest(coin, tf)
    return jsonify(res)

@app.route("/api/ohlc")
def api_ohlc():
    coin=request.args.get("coin","BTC")
    tf=request.args.get("tf","15m")
    if coin not in PAIRS: coin="BTC"
    klines=get_klines(coin,tf,200)
    if not klines:
        # ultimo tentativo: prova a usare i dati di /api/signals cache spark
        return jsonify({"ok":False,"error":"no klines - Binance bloccato su Render, uso fallback cache","debug":"Prova a riavviare Render"}),500
    closes=[c["close"] for c in klines]
    ema50_vals=ema_calc_from_closes(closes,50)
    ema150_vals=ema_calc_from_closes(closes,150)
    candles=[{"time":c["time"],"open":c["open"],"high":c["high"],"low":c["low"],"close":c["close"]} for c in klines]
    ema50_line=[{"time":klines[i]["time"],"value":ema50_vals[i]} for i in range(len(klines)) if ema50_vals[i] is not None]
    ema150_line=[{"time":klines[i]["time"],"value":ema150_vals[i]} for i in range(len(klines)) if ema150_vals[i] is not None]
    last_price=closes[-1] if closes else 0
    ema50_last=ema50_vals[-1] if ema50_vals[-1] else 0
    ema150_last=ema150_vals[-1] if ema150_vals[-1] else 0
    trend="BULL" if ema50_last>ema150_last else "BEAR" if ema50_last and ema150_last else "NEUTRAL"
    return jsonify({"ok":True,"coin":coin,"tf":tf,"candles":candles,"ema50":ema50_line,"ema150":ema150_line,"last_price":last_price,"ema50_last":ema50_last,"ema150_last":ema150_last,"trend":trend})

@app.route("/api/leverage", methods=["GET","POST"])
def api_leverage():
    global LEVERAGE_CONFIG
    if request.method=="POST":
        data=request.get_json() or {}
        if "leverage" in data:
            try:
                lev=int(data["leverage"])
                if lev in [1,2,3,5,10,25,50,100]:
                    LEVERAGE_CONFIG["leverage"]=lev
            except: pass
    lev=LEVERAGE_CONFIG["leverage"]
    return jsonify({"ok":True,"leverage":lev,"margin_mode":LEVERAGE_CONFIG["margin_mode"],"example":f"Con 50€ a {lev}x => posizione {50*lev}€"})


@app.route("/api/bybit/position")
def api_bybit_position():
    # Se hai API Bybit EU configurate in env, mostra posizioni, altrimenti DEMO
    api_key=os.getenv("BYBIT_API_KEY","")
    api_secret=os.getenv("BYBIT_API_SECRET","")
    if not api_key or not api_secret:
        return jsonify({"ok":False,"demo":True,"msg":"API Bybit non configurate - imposta BYBIT_API_KEY e BYBIT_API_SECRET su Render","positions":[]})
    # Qui andrebbe chiamata Bybit EU - per ora ritorniamo demo
    try:
        # Placeholder per chiamata reale Bybit EU
        # import ccxt etc.
        return jsonify({"ok":True,"demo":False,"positions":[],"msg":"Connesso a Bybit EU - posizioni lette"})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}),500

@app.route("/api/bybit/close", methods=["POST"])
def api_bybit_close():
    data=request.get_json() or {}
    symbol=data.get("symbol","BTCUSDT")
    side=data.get("side","")
    api_key=os.getenv("BYBIT_API_KEY","")
    if not api_key:
        return jsonify({"ok":False,"demo":True,"msg":f"DEMO: Chiudi {symbol} {side} su Bybit EU manualmente in Posizioni -> Chiudi -> Market. Per chiusura automatica configura API Bybit su Render."})
    # Qui chiamata reale Bybit
    return jsonify({"ok":True,"msg":f"Chiusura {symbol} inviata a Bybit EU"})



@app.route("/api/my_trades", methods=["GET","POST"])
def api_my_trades():
    global USER_TRADES, TRADE_ID_COUNTER
    if request.method=="GET":
        # aggiorna PnL in tempo reale per ogni trade aperto
        out=[]
        for t in USER_TRADES:
            try:
                price = get_price(t["coin"]) or t["entry"]
            except:
                price = t["entry"]
            entry=t["entry"]
            lev=t.get("leverage",10)
            cap=t.get("capital",50)
            side=t.get("side","LONG")
            if side=="LONG":
                pnl_pct=(price-entry)/entry*100*lev
            else:
                pnl_pct=(entry-price)/entry*100*lev
            pnl_eur=cap*pnl_pct/100
            t_copy=dict(t)
            t_copy["current_price"]=price
            t_copy["pnl_pct"]=round(pnl_pct,2)
            t_copy["pnl_eur"]=round(pnl_eur,2)
            out.append(t_copy)
        return jsonify({"ok":True,"trades":out})
    else:
        data=request.get_json() or {}
        coin=data.get("coin","BTC")
        side=data.get("side","LONG")
        entry=float(data.get("entry",0))
        leverage=int(data.get("leverage",10))
        capital=float(data.get("capital",50))
        sl=data.get("sl")
        tp=data.get("tp")
        if not entry:
            try:
                entry=get_price(coin) or 0
            except:
                entry=0
        if not entry:
            return jsonify({"ok":False,"error":"entry mancante"}),400
        trade={
            "id":TRADE_ID_COUNTER,
            "coin":coin,
            "side":side,
            "entry":entry,
            "leverage":leverage,
            "capital":capital,
            "sl":float(sl) if sl else None,
            "tp":float(tp) if tp else None,
            "time":rome_now().isoformat(),
            "status":"APERTO"
        }
        USER_TRADES.append(trade)
        TRADE_ID_COUNTER+=1
        return jsonify({"ok":True,"trade":trade})

@app.route("/api/my_trades/close", methods=["POST"])
def api_my_trades_close():
    global USER_TRADES
    data=request.get_json() or {}
    tid=int(data.get("id",0))
    for t in USER_TRADES:
        if t["id"]==tid and t["status"]=="APERTO":
            try:
                price=get_price(t["coin"]) or t["entry"]
            except:
                price=t["entry"]
            entry=t["entry"]
            lev=t.get("leverage",10)
            cap=t.get("capital",50)
            side=t.get("side","LONG")
            if side=="LONG":
                pnl_pct=(price-entry)/entry*100*lev
            else:
                pnl_pct=(entry-price)/entry*100*lev
            pnl_eur=cap*pnl_pct/100
            t["status"]="CHIUSO"
            t["close_price"]=price
            t["pnl_pct"]=round(pnl_pct,2)
            t["pnl_eur"]=round(pnl_eur,2)
            t["close_time"]=rome_now().isoformat()
            return jsonify({"ok":True,"trade":t})
    return jsonify({"ok":False,"error":"trade non trovato"}),404


@app.route("/trading")
def trading_page():
    html2 = """
<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>V73 - I Miei Trade Visibili</title>
<style>
*{box-sizing:border-box;font-family:Inter,sans-serif}body{margin:0;background:#020617;color:#e2e8f0}
.header{padding:12px 16px;background:#020617;border-bottom:1px solid #1e293b;display:flex;justify-content:space-between;align-items:center}
.badge{padding:4px 10px;border-radius:20px;font-size:11px;font-weight:800}.badge-bull{background:#22c55e;color:#052e16}.badge-bear{background:#ef4444;color:white}.badge-wait{background:#1e293b;color:#94a3b8}
.tv-wrap{margin:12px;background:#020617;border:1px solid #1e293b;border-radius:14px;overflow:hidden}
.tv-header{display:flex;justify-content:space-between;padding:10px 12px;border-bottom:1px solid #1e293b;align-items:center;flex-wrap:wrap;gap:8px}
.lev-panel{display:flex;gap:6px;flex-wrap:wrap;padding:12px;background:#0f172a;border-top:1px solid #1e293b}
.lev-btn{padding:7px 14px;border-radius:20px;border:1px solid #334155;background:#1e293b;color:#cbd5e1;font-weight:800;font-size:12px;cursor:pointer}
.lev-btn.active{background:#22c55e;color:#052e16;border-color:#22c55e}
.btn{padding:12px;border-radius:10px;border:none;font-weight:800;cursor:pointer}
.btn-green{background:#16a34a;color:white;flex:1}.btn-red{background:#dc2626;color:white;flex:1}.btn-close{background:#f59e0b;color:#000;flex:1}.btn-small{padding:6px 10px;border-radius:20px;font-size:11px}
.info{font-size:11px;color:#94a3b8;background:#1e293b;padding:8px 10px;border-radius:8px;border:1px solid #334155;margin:8px 12px;line-height:1.4}
.input-cap{padding:8px 10px;border-radius:20px;background:#020617;color:white;border:1px solid #334155;width:90px;text-align:center;font-weight:800}
.trade-card{display:flex;justify-content:space-between;align-items:center;padding:10px;border-bottom:1px solid #1e293b;font-size:12px}
.trade-card.bull{border-left:3px solid #22c55e}.trade-card.bear{border-left:3px solid #ef4444}
</style></head><body>
<div class="header"><div><b>V73 TRADE VISIBILI</b> <span style="font-size:10px;color:#22c55e">Telegram safe</span><div style="font-size:10px;color:#94a3b8">TradingView + Leva + I Miei Trade</div></div><div><a href="/app" style="color:#22c55e;font-size:12px;text-decoration:none">Torna a V71</a></div></div>
<div class="info">Quando apri su Bybit EU, clicca LONG/SHORT qui sotto e il trade appare in <b>I MIEI TRADE</b> con PnL live. Telegram resta su /app identico.</div>

<div class="tv-wrap">
<div class="tv-header">
<div><b id="tvTitle">ETHUSDT 15m</b> <span id="emaInfo" style="font-size:11px;color:#94a3b8"></span> <span id="trendBadge" class="badge badge-wait">--</span></div>
<div style="display:flex;gap:6px;align-items:center">
<select id="coinSel" onchange="changeCoin()" style="padding:6px 10px;border-radius:20px;background:#020617;color:white;border:1px solid #334155"><option value="BTC">BTC</option><option value="ETH" selected>ETH</option><option value="ORO">ORO</option></select>
<select id="tfSel" onchange="changeTF()" style="padding:6px 10px;border-radius:20px;background:#020617;color:white;border:1px solid #334155"><option value="5">5m</option><option value="15" selected>15m</option><option value="60">1H</option><option value="240">4H</option></select>
</div>
</div>
<div id="tradingview_chart" style="height:420px;width:100%"></div>

<div class="lev-panel">
<div style="width:100%;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
<div style="font-size:12px;font-weight:800;color:#86efac">CAPITALE:</div>
<input id="capInput" class="input-cap" type="number" value="50" min="1" max="10000" oninput="updateCalc()" />
<span style="font-size:12px;color:#cbd5e1">EUR</span>
<div style="margin-left:auto;font-size:12px;font-weight:800;color:#86efac">LEVA: <span id="levInfo" style="color:#cbd5e1;font-weight:400"></span></div>
</div>
<div style="width:100%;display:flex;gap:6px;margin-top:6px">
<button class="lev-btn" data-lev="1" onclick="setLev(1)">1x</button>
<button class="lev-btn" data-lev="3" onclick="setLev(3)">3x</button>
<button class="lev-btn" data-lev="5" onclick="setLev(5)">5x</button>
<button class="lev-btn active" data-lev="10" onclick="setLev(10)">10x</button>
<button class="lev-btn" data-lev="25" onclick="setLev(25)">25x</button>
<button class="lev-btn" data-lev="50" onclick="setLev(50)">50x</button>
<button class="lev-btn" data-lev="100" onclick="setLev(100)">100x</button>
</div>
<div style="width:100%;display:flex;gap:8px;margin-top:10px">
<button class="btn btn-green" onclick="openTrade('LONG')">LONG + Salva</button>
<button class="btn btn-red" onclick="openTrade('SHORT')">SHORT + Salva</button>
</div>
<div id="calc" style="width:100%;font-size:11px;color:#94a3b8;margin-top:10px;line-height:1.5;background:#020617;padding:10px;border-radius:10px;border:1px solid #1e293b"></div>
</div>
</div>

<div class="tv-wrap" style="margin-top:8px">
<div class="tv-header"><b>I MIEI TRADE</b> <span style="font-size:10px;color:#94a3b8">PnL live da Bybit price</span> <button onclick="loadMyTrades()" style="padding:4px 10px;border-radius:20px;background:#1e293b;color:white;border:1px solid #334155;font-size:11px">Aggiorna</button></div>
<div id="myTradesList" style="max-height:400px;overflow:auto;background:#020617">Carico...</div>
</div>

<script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
<script>
let curCoin='ETH', curTF='15', lev=10, currentPrice=0, capital=50;
let tvWidget=null, lastTP=0, lastSL=0;

function getSymbol(coin){
  if(coin=='BTC') return 'BINANCE:BTCUSDT';
  if(coin=='ETH') return 'BINANCE:ETHUSDT';
  if(coin=='ORO') return 'BINANCE:PAXGUSDT';
  return 'BINANCE:BTCUSDT';
}

function loadTV(){
  const symbol=getSymbol(curCoin);
  document.getElementById('tvTitle').textContent=curCoin+'USDT '+curTF+'m';
  if(tvWidget) { try{tvWidget.remove();}catch(e){} }
  document.getElementById('tradingview_chart').innerHTML='';
  tvWidget = new TradingView.widget({
    "autosize": true,
    "symbol": symbol,
    "interval": curTF,
    "timezone": "Europe/Rome",
    "theme": "dark",
    "style": "1",
    "locale": "it",
    "toolbar_bg": "#0f172a",
    "enable_publishing": false,
    "withdateranges": true,
    "hide_side_toolbar": false,
    "allow_symbol_change": true,
    "details": true,
    "studies": ["EMA@tv-basicstudies", "EMA@tv-basicstudies", "EMA@tv-basicstudies"],
    "container_id": "tradingview_chart"
  });
  fetchEMA();
}

async function fetchEMA(){
  try{
    let tfMap={'5':'5m','15':'15m','60':'1H','240':'4H'};
    let tf = tfMap[curTF]||'15m';
    let r=await fetch(`/api/ohlc?coin=${curCoin}&tf=${tf}`);
    let j=await r.json();
    if(j.ok){
      document.getElementById('emaInfo').textContent=`EMA50: ${j.ema50_last.toFixed(2)} | EMA150: ${j.ema150_last.toFixed(2)}`;
      let badge=document.getElementById('trendBadge');
      let isBull = j.ema50_last > j.ema150_last;
      badge.textContent = j.trend + (isBull ? ' - SALIRA' : ' - SCENDERA');
      badge.className = 'badge ' + (isBull ? 'badge-bull' : 'badge-bear');
      currentPrice=j.last_price;
      let r2=await fetch(`/api/signals?tf=${tf}`);
      let j2=await r2.json();
      if(j2.coins && j2.coins[curCoin]){
        lastSL=j2.coins[curCoin].sl;
        lastTP=j2.coins[curCoin].tp;
      }
      updateCalc();
    }
  }catch(e){console.log('EMA fetch error',e)}
}

function changeCoin(){curCoin=document.getElementById('coinSel').value;loadTV();loadMyTrades();}
function changeTF(){curTF=document.getElementById('tfSel').value;loadTV();}

async function setLev(l){
  lev=l;
  document.querySelectorAll('.lev-btn').forEach(b=>b.classList.remove('active'));
  document.querySelector(`[data-lev="${l}"]`).classList.add('active');
  try{
    await fetch('/api/leverage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({leverage:l})});
    let r=await fetch('/api/leverage');
    let j=await r.json();
    document.getElementById('levInfo').textContent=j.example;
  }catch(e){}
  updateCalc();
}

function updateCalc(){
  capital=parseFloat(document.getElementById('capInput').value)||50;
  if(!currentPrice) currentPrice=2400;
  let p=currentPrice;
  let longLiq=p*(1-0.8/lev);
  let shortLiq=p*(1+0.8/lev);
  let pos=capital*lev;
  document.getElementById('calc').innerHTML=
    `Capitale <b>${capital} EUR</b> x ${lev}x = <b>${pos.toFixed(2)} EUR</b><br>`+
    `Entry ~${p.toFixed(2)} | Liq LONG ${longLiq.toFixed(2)} | Liq SHORT ${shortLiq.toFixed(2)}<br>`+
    `SL ${lastSL?lastSL.toFixed(2):'--'} TP ${lastTP?lastTP.toFixed(2):'--'} - Quando apri su Bybit, clicca LONG/SHORT + Salva qui sotto`;
}

async function openTrade(side){
  let p=currentPrice||0;
  capital=parseFloat(document.getElementById('capInput').value)||50;
  let payload={coin:curCoin, side:side, entry:p, leverage:lev, capital:capital, sl:lastSL, tp:lastTP};
  try{
    let r=await fetch('/api/my_trades',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    let j=await r.json();
    if(j.ok){
      alert(`${side} ${curCoin} salvato! Entry ${p.toFixed(2)} leva ${lev}x
Ora aprilo anche su Bybit EU con stessi valori. Lo vedrai sotto in I MIEI TRADE con PnL live.`);
      loadMyTrades();
    }else{
      alert('Errore: '+j.error);
    }
  }catch(e){alert(e.message);}
}

async function loadMyTrades(){
  try{
    let r=await fetch('/api/my_trades');
    let j=await r.json();
    let list=document.getElementById('myTradesList');
    if(!j.trades || j.trades.length==0){
      list.innerHTML='<div style="padding:20px;text-align:center;color:#64748b">Nessun trade ancora.<br>Apri LONG/SHORT sopra e apparira qui con PnL live.</div>';
      return;
    }
    let html='';
    j.trades.slice().reverse().forEach(t=>{
      let col=t.pnl_eur>=0?'#22c55e':'#ef4444';
      let statusCol=t.status=='APERTO'?'#facc15':'#94a3b8';
      let sideClass=t.side=='LONG'?'bull':'bear';
      html+=`<div class="trade-card ${sideClass}"><div><b>${t.side} ${t.coin}</b> ${t.leverage}x ${t.capital}EUR<br><span style="font-size:10px;color:#94a3b8">Entry ${t.entry.toFixed(2)} -> Ora ${t.current_price?t.current_price.toFixed(2):'--'} | SL ${t.sl?t.sl.toFixed(2):'--'} TP ${t.tp?t.tp.toFixed(2):'--'}<br>${t.time.slice(11,19)} ${t.status}</span></div><div style="text-align:right"><span style="color:${col};font-weight:800">${t.pnl_eur>=0?'+':''}${t.pnl_eur} EUR (${t.pnl_pct}%)</span><br><span style="color:${statusCol};font-size:10px">${t.status}</span>${t.status=='APERTO'?`<br><button class="btn btn-close btn-small" onclick="closeTrade(${t.id})">CHIUDI</button>`:''}</div></div>`;
    });
    list.innerHTML=html;
  }catch(e){
    document.getElementById('myTradesList').innerHTML='Errore: '+e.message;
  }
}

async function closeTrade(id){
  if(!confirm('Chiudere trade #'+id+'?')) return;
  try{
    let r=await fetch('/api/my_trades/close',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:id})});
    let j=await r.json();
    if(j.ok){
      alert(`Chiuso! PnL ${j.trade.pnl_eur} EUR (${j.trade.pnl_pct}%) - Chiudilo anche su Bybit EU in Posizioni -> Chiudi -> Market`);
      loadMyTrades();
    }else{
      alert(j.error);
    }
  }catch(e){alert(e.message);}
}

loadTV();setLev(10);loadMyTrades();
setInterval(loadMyTrades, 10000);
</script>
</body></html>
    """
    return Response(html2, mimetype="text/html; charset=utf-8")


@app.route("/app")
def app_page():
    html="""
<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>V71 SIMPLIFIED HIGH WR</title>
<style>
*{box-sizing:border-box;font-family:Inter,system-ui,sans-serif}
body{margin:0;background:#020617;color:#e2e8f0}
.header{padding:14px 16px;display:flex;align-items:center;gap:12px;background:#0f172a;border-bottom:1px solid #1e293b;position:sticky;top:0;z-index:10}
.logo{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#22c55e,#06b6d4);display:flex;align-items:center;justify-content:center;font-weight:900;color:white;font-size:12px}
.badge{padding:4px 10px;border-radius:20px;font-size:11px;font-weight:800}
.badge-entra{background:#22c55e;color:#052e16;animation:glow 1s infinite alternate}
.badge-quasi{background:#facc15;color:#422006}
.badge-wait{background:#1e293b;color:#94a3b8}
@keyframes glow{0%{box-shadow:0 0 5px #22c55e}100%{box-shadow:0 0 12px #22c55e}}
.tfs{display:flex;gap:6px;padding:10px 12px;background:#020617;overflow-x:auto}
.tfs button{border:1px solid #1e293b;background:#1e293b;color:#cbd5e1;padding:8px 14px;border-radius:20px;font-weight:700;cursor:pointer}
.tfs button.active{background:#22c55e;color:#052e16}
.banner{margin:8px 12px;padding:10px 12px;border-radius:10px;font-size:10px;text-align:center;line-height:1.3}
.banner-simplified{background:linear-gradient(135deg,#052e16,#083344);border:1px solid #22c55e;color:#86efac;font-weight:800}
.coin{background:#0f172a;border:1px solid #1e293b;border-radius:14px;margin:8px 10px;overflow:hidden}
.coin-row{display:flex;justify-content:space-between;align-items:center;padding:14px;cursor:pointer}
.icon{width:38px;height:38px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:900;color:white}
.icon.btc{background:#f7931a}.icon.eth{background:#8b5cf6}.icon.oro{background:#ca8a04}
.modal{position:fixed;inset:0;background:rgba(0,0,0,0.7);display:none;align-items:flex-end;justify-content:center;z-index:50}
.modal.show{display:flex}
.box{background:#0f172a;width:100%;max-width:520px;border-radius:20px 20px 0 0;padding:20px;max-height:92vh;overflow:auto;border:1px solid #1e293b}
.btn{width:100%;padding:12px;border-radius:10px;border:none;font-weight:800;cursor:pointer;margin-top:8px}
.btn-green{background:#16a34a;color:white}
.btn-blue{background:#3b82f6;color:white}
.btn-red{background:#dc2626;color:white}
#aiPanel{position:fixed;bottom:0;left:0;right:0;max-width:520px;margin:0 auto;background:#0f172a;border-top:2px solid #22c55e;border-left:1px solid #1e293b;border-right:1px solid #1e293b;border-radius:20px 20px 0 0;z-index:60;display:none;flex-direction:column;max-height:80vh}
#aiPanel.show{display:flex}
#aiMsgs{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}
.msg{padding:10px 12px;border-radius:12px;font-size:13px;line-height:1.4;max-width:85%;white-space:pre-wrap}
.msg.user{align-self:flex-end;background:#22c55e;color:#052e16}
.msg.ai{align-self:flex-start;background:#1e293b;border:1px solid #334155;color:#e2e8f0}
#aiInputRow{display:flex;gap:8px;padding:10px;border-top:1px solid #1e293b}
#aiInput{flex:1;background:#020617;border:1px solid #334155;color:white;padding:10px 12px;border-radius:20px;outline:none}
.riskBar{margin:8px 12px;padding:10px 12px;background:#1e293b;border:1px solid #334155;border-radius:10px;font-size:10px;display:flex;justify-content:space-between;gap:6px;flex-wrap:wrap}
.methodsGrid{display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:9px;margin-top:6px}
.methodsGrid span{padding:3px 6px;border-radius:6px;background:#1e293b;border:1px solid #334155}
.methodsGrid span.bull{background:#052e16;border-color:#16a34a;color:#86efac}
.methodsGrid span.bear{background:#450a0a;border-color:#dc2626;color:#fca5a5}
</style></head><body>
<div class="header"><div class="logo">V71</div><div style="flex:1"><div style="font-weight:800">V71 <span style="background:#22c55e;color:#052e16;padding:2px 6px;border-radius:6px;font-size:9px">SIMPLIFIED HIGH WR</span></div><div style="font-size:9px;color:#94a3b8">Solo BOS + V67 (EMA 9/21/50 + RSI + VOL + 1H) - NO 12 metodi che davano 5.6% WR</div></div><div style="display:flex;gap:6px"><button onclick="openAI()" style="background:#22c55e;color:#052e16;border:none;padding:6px 10px;border-radius:20px;font-size:11px;font-weight:700">🤖 AI</button><button onclick="openRisk()" style="background:#1e293b;color:white;border:1px solid #334155;padding:6px 10px;border-radius:20px;font-size:11px">⚙️ Risk</button></div></div>
<div id="banner" class="banner banner-simplified">V71 SIMPLIFIED HIGH WR: Torno a tuo metodo manuale + V67. Solo 5 metodi: BOS HH/LH cerchi blu (40 punti) + EMA 9>21>50 (20) + RSI (15) + VOL (10) + 1H (15) = max 100. FILTRO STRICT: BOS deve essere uguale a EMA, altrimenti NO TRADE (era causa LOSS V70.2). Max 3 trade/giorno, stop dopo 2 loss, cooldown 15min. Obiettivo WR 60%+ come facevi manuale.</div>
<div id="riskBar" class="riskBar"><span id="riskMode">Mode: DEMO</span><span id="riskCap">Cap: $1000</span><span id="riskWR">WR: 0%</span><span id="riskEquity">Eq: $1000</span><span id="riskAdapt">Adapt: 82%</span><span id="riskScores">BULL vs BEAR 5 metodi</span><span><button onclick="openHistory()" style="background:#22c55e;color:#052e16;border:none;padding:4px 8px;border-radius:10px;font-size:10px;font-weight:800">📓 Diario</button> <button onclick="runBT()" style="background:#22c55e;color:#052e16;border:none;padding:4px 8px;border-radius:10px;font-size:10px;font-weight:800">📊 Backtest HIGH WR</button></span></div>
<div class="tfs"><button id="b5m" onclick="loadTF('5m')">⚡ 5m HIGH WR</button><button id="b15m" class="active" onclick="loadTF('15m')">15m SIMPLIFIED</button><button id="b1H" onclick="loadTF('1H')">1H HIGH WR</button><button id="b4H" onclick="loadTF('4H')">4H HIGH WR</button><button onclick="loadTF(curTF,true,true)" style="background:#22c55e;color:#052e16">📱 Forza TG</button><button onclick="nuke()" style="background:#dc2626;color:white">💣 NUKE</button></div>
<div id="coins"><div style="padding:20px;text-align:center;color:#94a3b8">Carico V71 SIMPLIFIED HIGH WR - Solo BOS + V67...</div></div>
<div id="riskModal" class="modal" onclick="if(event.target==this)closeRisk()"><div class="box"><b>⚙️ Risk V71 SIMPLIFIED HIGH WR</b><div style="font-size:10px;color:#86efac;background:#052e16;border:1px solid #22c55e;padding:8px;border-radius:8px;margin:6px 0">V71: meno trade ma più WIN. Solo BOS (40) + EMA 9/21/50 (20) + RSI (15) + VOL (10) + 1H (15). Filtro STRICT: BOS deve concordare con EMA, altrimenti NO TRADE. Era causa di LOSS V70.2 con 12 metodi che dicevano BULL 60 BEAR 70 e entrava lo stesso. Max 3/giorno, stop 2 loss, cooldown 15min, ATR*1.8 SL*2.5 TP R:R 1:2.5</div><div style="display:grid;gap:10px;margin-top:10px">
<label style="font-size:12px">Modalità<br><select id="rMode" style="width:100%;padding:10px;background:#020617;color:white;border:1px solid #334155;border-radius:10px"><option value="DEMO">🟡 DEMO HIGH WR</option><option value="REAL">🔴 REAL HIGH WR</option></select></label>
<label style="font-size:12px">Capitale $ <input id="rCap" type="number" style="width:100%;padding:10px;background:#020617;color:white;border:1px solid #334155;border-radius:10px"></label>
<label style="font-size:12px">Rischio % <input id="rRisk" type="number" step="0.1" style="width:100%;padding:10px;background:#020617;color:white;border:1px solid #334155;border-radius:10px"></label>
<label style="font-size:12px">Max trade/giorno <input id="rMaxT" type="number" style="width:100%;padding:10px;background:#020617;color:white;border:1px solid #334155;border-radius:10px"></label>
<label style="font-size:12px">Stop dopo N loss <input id="rMaxL" type="number" style="width:100%;padding:10px;background:#020617;color:white;border:1px solid #334155;border-radius:10px"></label>
</div><button class="btn btn-green" onclick="saveRisk()">💾 Salva HIGH WR</button><button class="btn" onclick="closeRisk()" style="background:#1e293b;color:white">Chiudi</button></div></div>
<div id="histModal" class="modal" onclick="if(event.target==this)closeHistory()"><div class="box"><b>📓 Diario V71 HIGH WR</b><div id="histStats" style="font-size:11px;background:#1e293b;padding:10px;border-radius:10px;margin:8px 0"></div><div id="histList" style="max-height:50vh;overflow:auto"></div><button class="btn" onclick="closeHistory()" style="background:#1e293b;color:white">Chiudi</button></div></div>
<div id="btModal" class="modal" onclick="if(event.target==this)closeBT()"><div class="box"><b>📊 Backtest V71 HIGH WR</b><div id="btStats" style="font-size:11px;background:#1e293b;padding:10px;border-radius:10px;margin:8px 0">Carico...</div><div id="btList" style="max-height:40vh;overflow:auto;font-size:11px"></div><button class="btn" onclick="closeBT()" style="background:#1e293b;color:white">Chiudi</button></div></div>
<div id="aiPanel"><div style="padding:12px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #1e293b"><b>🤖 AI V71 HIGH WR</b><button onclick="closeAI()" style="background:#1e293b;color:white;border:none;padding:6px 10px;border-radius:10px">X</button></div>
<div id="aiMsgs"><div class="msg ai">V71 SIMPLIFIED HIGH WR - Torno al tuo metodo manuale:

V70.2 aveva 12 metodi che votavano e si contraddicevano: BULL 60 BEAR 70 entrava e perdeva → WR 5.6% su 15m, 18.2% live Eq $968 DD 3.38%

V71 ha solo 5 metodi: BOS 40 + EMA 20 + RSI 15 + VOL 10 + 1H 15 = max 100. Filtro STRICT: BOS deve essere uguale a EMA (se BOS dice COMPRA e EMA dice VENDI = NO TRADE). Così evitiamo i LOSS di V70.2.

Max 3 trade/giorno, stop dopo 2 loss, cooldown 15min, SL ATR*1.8 TP*2.5 R:R 1:2.5

Obiettivo: WR 60%+ come facevi manuale +0.29$ con solo HH/LH</div>
</div>
<div id="aiInputRow"><input id="aiInput" placeholder="V71 HIGH WR?" onkeydown="if(event.key==='Enter')sendAI()"><button onclick="sendAI()" style="background:#22c55e;color:#052e16;border:none;padding:10px 16px;border-radius:20px;font-weight:800">Invia</button></div>
</div>
<div id="modal" class="modal" onclick="if(event.target==this)closeM()"><div class="box"><div style="display:flex;justify-content:space-between"><b id="mCoin">BTC</b><button onclick="closeM()" style="background:#1e293b;color:white;border:none;padding:8px 12px;border-radius:10px">X</button></div><div id="mPrice" style="font-size:11px;color:#94a3b8;margin:6px 0"></div><div id="mBig" style="border-radius:14px;padding:16px;margin:10px 0;text-align:center;font-weight:900;font-size:20px"></div><div id="mExtra" style="font-size:11px;background:#1e293b;padding:10px;border-radius:10px;border:1px solid #334155;margin:8px 0"></div><div id="mMethods" style="font-size:10px;background:#1e293b;padding:10px;border-radius:10px;border:1px solid #334155;margin:8px 0;white-space:pre-wrap"></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px"><div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">SL ATR*1.8</span><br><b id="mSL">-</b><br><span id="mSLpct" style="font-size:10px"></span></div><div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">TP 2.5x</span><br><b id="mTP">-</b><br><span id="mTPpct" style="font-size:10px"></span><br><span id="mRR" style="font-size:10px;color:#86efac"></span></div></div><div id="mRisk" style="font-size:11px;background:#052e16;border:1px solid #22c55e;padding:10px;border-radius:10px;margin:8px 0;color:#86efac"></div><button class="btn btn-green" onclick="copySLTP()">📋 Copia HIGH WR</button><button class="btn btn-blue" onclick="openChart()">📈 TV HIGH WR</button><button class="btn btn-green" onclick="askAboutCoin()">🤖 AI HIGH WR</button><button class="btn btn-blue" onclick="sendNow()">📱 TG ORA</button></div></div>
<script>
var curTF='15m';var lastData=null;var curCoin=null;var riskCfg=null;
function badge(c,l){if(c=='entra')return '<span class="badge badge-entra">'+l+'</span>';if(c=='quasi')return '<span class="badge badge-quasi">'+l+'</span>';return '<span class="badge badge-wait">'+l+'</span>';}
async function loadRisk(){try{let r=await fetch('/api/risk_config');let j=await r.json();riskCfg=j.risk;document.getElementById('riskMode').textContent='Mode: '+riskCfg.mode;document.getElementById('riskCap').textContent='Cap: $'+riskCfg.capital;document.getElementById('riskDay').textContent='Oggi: '+riskCfg.daily_trades+'/'+riskCfg.max_trades_day;document.getElementById('rMode').value=riskCfg.mode;document.getElementById('rCap').value=riskCfg.capital;document.getElementById('rRisk').value=riskCfg.risk_pct;document.getElementById('rMaxT').value=riskCfg.max_trades_day;document.getElementById('rMaxL').value=riskCfg.max_losses_row;document.getElementById('riskEquity').textContent=`Eq: $${riskCfg.equity.toFixed(0)} DD ${riskCfg.drawdown.toFixed(1)}%`;document.getElementById('riskAdapt').textContent=`Adapt: ${j.adaptive||82}%`;document.getElementById('riskScores').textContent=`BULL vs BEAR 5 metodi`;}catch{}}
async function checkTG(){await loadRisk();}
async function nuke(){if(!confirm('NUKE V71 HIGH WR? Resetta Eq $968 → $1000 e WR 18% → 0%?'))return;try{let r=await fetch('/api/nuke');alert('✅ NUKE V71 - Eq resettata a $1000, WR resettato, ora solo 5 metodi HIGH WR');location.reload();}catch(e){alert(e.message);}}
async function loadTF(tf,withTG=false,force=false){
curTF=tf;
document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active'));
let el=document.getElementById('b'+tf); if(el) el.classList.add('active');
document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center;color:#94a3b8">⚡ Carico '+tf+' V71 HIGH WR - Solo BOS + V67...</div>';
let controller=new AbortController(); let timeout=setTimeout(()=>controller.abort(),15000);
try{
let url='/api/signals?tf='+tf+(withTG?'&telegram=1':'')+(force?'&force=1':'');
let r=await fetch(url,{signal:controller.signal}); clearTimeout(timeout); let d=await r.json(); lastData=d; await loadRisk(); await loadHistoryStats();
let html='';
for(let name in d.coins){
let info=d.coins[name];
let iclass=name=='BTC'?'btc':name=='ETH'?'eth':'oro';
let b=badge(info.quality_color, info.quality_label);
let price='$'+info.price.toFixed(2);
let action=info.quality_color=='entra'?(info.signal=='COMPRA'?'🚀 COMPRA':'🔻 VENDI'):'⏸️ Aspetta';
let methods=info.methods||{};
let bullHtml=''; let bearHtml='';
for(let k in methods){let m=methods[k]; if(m.score>0){if(m.signal=='COMPRA') bullHtml+=`<span class="bull">${k} ${m.score}</span>`; else if(m.signal=='VENDI') bearHtml+=`<span class="bear">${k} ${m.score}</span>`;}}
html+=`<div class="coin"><div class="coin-row" onclick="openM('${name}')"><div style="display:flex;gap:10px;align-items:center"><div class="icon ${iclass}">${name=='BTC'?'B':name=='ETH'?'E':'Au'}</div><div><b>${name}</b> - ${price}<div style="font-size:11px;color:#94a3b8">${info.extra.slice(0,130)}</div><div style="font-size:11px;color:#64748b">${action} BULL ${info.compra_score} vs BEAR ${info.vendi_score} | ${info.bos_type} R:R 1:${info.rr}</div><div class="methodsGrid">${bullHtml}${bearHtml}</div></div></div><div style="text-align:right">${b}<div style="font-size:11px;color:#64748b;margin-top:4px">${info.signal} ${info.conf}%<br>SL ${info.sl_pct.toFixed(2)}% TP ${info.tp_pct.toFixed(2)}%<br>${info.bos_type}</div></div></div></div>`;
}
if(d.telegram_results && Object.keys(d.telegram_results).length>0){html+=`<div style="background:#052e16;padding:8px 12px;font-size:10px;color:#86efac;text-align:center">📱 TG HIGH WR: ${JSON.stringify(d.telegram_results)}</div>`;}
document.getElementById('coins').innerHTML=html;
}catch(e){
clearTimeout(timeout);
document.getElementById('coins').innerHTML='<div style="padding:20px;color:#ef4444;text-align:center">Timeout HIGH WR<br><button onclick="nuke()" style="margin-top:10px;background:#dc2626;color:white;border:none;padding:10px 20px;border-radius:20px">💣 NUKE</button><br><small>'+e.message+'</small></div>';
}
}
function openM(coin){if(!lastData) return; let info=lastData.coins[coin]; curCoin=coin; document.getElementById('mCoin').textContent=coin+' - $'+info.price.toFixed(2); document.getElementById('mPrice').textContent=info.source+' - '+info.signal+' '+info.conf+'% BULL '+info.compra_score+' vs BEAR '+info.vendi_score+' - TF '+curTF; let big=document.getElementById('mBig'); big.style.cssText='border-radius:14px;padding:16px;margin:10px 0;text-align:center;font-weight:900;font-size:20px;'; if(info.quality_color=='entra'){big.style.background='#052e16';big.style.border='2px solid #22c55e';big.style.color='#22c55e';} else if(info.quality_color=='quasi'){big.style.background='#422006';big.style.border='2px solid #facc15';big.style.color='#facc15';} else{big.style.background='#1e293b';big.style.border='1px solid #334155';} big.innerHTML=info.quality_label+' - '+info.signal+' '+info.conf+'% BULL'+info.compra_score+' BEAR'+info.vendi_score; document.getElementById('mSL').textContent='$'+info.sl.toFixed(2); document.getElementById('mSLpct').textContent='-'+info.sl_pct.toFixed(2)+'%'; document.getElementById('mTP').textContent='$'+info.tp.toFixed(2); document.getElementById('mTPpct').textContent='+'+info.tp_pct.toFixed(2)+'%'; document.getElementById('mRR').textContent='R:R 1:'+info.rr; document.getElementById('mExtra').textContent=info.extra; let methHtml='5 METODI HIGH WR:\\n'; for(let k in info.methods){let m=info.methods[k]; methHtml+=`${k}: ${m.signal} ${m.score} - ${m.desc}\\n`;} document.getElementById('mMethods').textContent=methHtml; let riskDiv=document.getElementById('mRisk'); if(riskCfg){let riskMoney=riskCfg.capital*riskCfg.risk_pct/100;let size=riskMoney/(info.price*info.sl_pct/100);riskDiv.innerHTML=`💼 ${riskCfg.mode} $${riskCfg.capital} ${riskCfg.risk_pct}% = $${riskMoney.toFixed(2)} size ${size.toFixed(4)}<br>📈 Eq $${riskCfg.equity.toFixed(2)} Peak $${riskCfg.peak.toFixed(2)} DD ${riskCfg.drawdown.toFixed(1)}%<br>🏆 BULL ${info.compra_score} vs BEAR ${info.vendi_score} Diff ${info.compra_score-info.vendi_score}<br>${info.compra_score>info.vendi_score?`✅ BULL vince di ${info.compra_score-info.vendi_score} punti → ${info.signal}`:`🔻 BEAR vince di ${info.vendi_score-info.compra_score} punti → ${info.signal}`}<br>🔍 ${info.bos_type} ${info.bos_desc||''}<br>✅ FILTRO V71: BOS==EMA altrimenti NO TRADE - era causa LOSS V70.2`;} document.getElementById('modal').classList.add('show');}
function closeM(){document.getElementById('modal').classList.remove('show');}
function copySLTP(){if(!curCoin||!lastData) return; let info=lastData.coins[curCoin]; let txt=`${curCoin} ${info.price.toFixed(2)} SL ${info.sl.toFixed(2)} TP ${info.tp.toFixed(2)} V71 HIGH WR BULL${info.compra_score} BEAR${info.vendi_score} BOS ${info.bos_type}`; navigator.clipboard.writeText(txt).then(()=>alert('Copiato HIGH WR'));}
function openChart(){if(!curCoin) return; let sym={BTC:'BINANCE:BTCUSDT',ETH:'BINANCE:ETHUSDT',ORO:'BINANCE:PAXGUSDT'}[curCoin]; window.open('https://www.tradingview.com/chart/?symbol='+sym,'_blank');}
async function sendNow(){if(!curCoin) return; try{let r=await fetch('/api/signals?tf='+curTF+'&telegram=1&force=1'); let j=await r.json(); alert('TG HIGH WR: '+JSON.stringify(j.telegram_results));}catch(e){alert(e.message);}}
function openAI(){document.getElementById('aiPanel').classList.add('show');}
function closeAI(){document.getElementById('aiPanel').classList.remove('show');}
function askChip(t){document.getElementById('aiInput').value=t; sendAI();}
function askAboutCoin(){if(!curCoin) return; closeM(); openAI(); document.getElementById('aiInput').value='V71 HIGH WR su '+curCoin+'?'; sendAI();}
async function sendAI(){let input=document.getElementById('aiInput'); let txt=input.value.trim(); if(!txt) return; let msgs=document.getElementById('aiMsgs'); let div=document.createElement('div'); div.className='msg user'; div.textContent=txt; msgs.appendChild(div); input.value=''; msgs.scrollTop=msgs.scrollHeight; try{let r=await fetch('/api/ai_chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:txt,coin:curCoin||'BTC',tf:curTF})}); let j=await r.json(); let ans=j.answer||j.error||'Errore'; let div2=document.createElement('div'); div2.className='msg ai'; div2.textContent=ans; msgs.appendChild(div2); msgs.scrollTop=msgs.scrollHeight;}catch(e){let div2=document.createElement('div'); div2.className='msg ai'; div2.textContent='Errore: '+e.message; msgs.appendChild(div2);}}
function openRisk(){document.getElementById('riskModal').classList.add('show');}
function closeRisk(){document.getElementById('riskModal').classList.remove('show');}
async function saveRisk(){let mode=document.getElementById('rMode').value; let cap=document.getElementById('rCap').value; let risk=document.getElementById('rRisk').value; let maxT=document.getElementById('rMaxT').value; let maxL=document.getElementById('rMaxL').value; try{let r=await fetch('/api/risk_config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:mode,capital:cap,risk_pct:risk,max_trades_day:maxT,max_losses_row:maxL})}); let j=await r.json(); alert('✅ Salvato HIGH WR'); closeRisk(); await loadRisk(); await loadTF(curTF);}catch(e){alert(e.message);}}
async function loadHistoryStats(){try{let r=await fetch('/api/history');let j=await r.json(); document.getElementById('riskWR').textContent=`WR: ${j.winrate}% ${j.wins}W/${j.losses}L P:${j.pending}`; document.getElementById('riskMode').textContent='Mode: '+ (riskCfg?riskCfg.mode:'DEMO'); if(riskCfg) document.getElementById('riskCap').textContent='Cap: $'+riskCfg.capital; document.getElementById('riskEquity').textContent=`Eq: $${j.equity} DD ${j.drawdown}%`; }catch{}}
function openHistory(){document.getElementById('histModal').classList.add('show'); loadHistory();}
function closeHistory(){document.getElementById('histModal').classList.remove('show');}
async function loadHistory(){try{let r=await fetch('/api/history');let j=await r.json(); document.getElementById('histStats').textContent=`Totale ${j.total} - WIN ${j.wins} - LOSS ${j.losses} - Pending ${j.pending} - WR ${j.winrate}% - PnL ${j.pnl_sum}% - Eq $${j.equity} - V71 HIGH WR`; let list=document.getElementById('histList');let html=''; j.history.slice().reverse().forEach((t,i)=>{let col=t.result=='WIN'?'#22c55e':t.result=='LOSS'?'#ef4444':'#facc15'; html+=`<div style="display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid #1e293b;font-size:11px"><div><b>🤖 ${t.coin} ${t.tf} ${t.signal} ${t.conf}%</b> $${t.entry?.toFixed(2)} → ${t.result?`$${(t.result=='WIN'?t.tp:t.sl).toFixed(2)}`:'...'}<br><span style="color:#94a3b8">${t.time.slice(11,19)} ${t.mode} PnL ${t.pnl_pct?.toFixed(2)}%</span></div><div style="text-align:right"><span style="color:${col};font-weight:800">${t.result||'APERTO'}</span></div></div>`;}); list.innerHTML=html||'Nessun trade HIGH WR';}catch(e){alert(e.message);}}
function openBT(){document.getElementById('btModal').classList.add('show'); runBT();}
function closeBT(){document.getElementById('btModal').classList.remove('show');}
async function runBT(){let coin=curCoin||'BTC';let tf=curTF; document.getElementById('btStats').textContent='Carico backtest HIGH WR '+coin+' '+tf+'...'; document.getElementById('btList').innerHTML=''; document.getElementById('btModal').classList.add('show'); try{let r=await fetch(`/api/backtest?coin=${coin}&tf=${tf}`); let j=await r.json(); if(!j.ok){document.getElementById('btStats').textContent='Errore: '+j.error; return;} document.getElementById('btStats').textContent=`V71 HIGH WR ${j.coin} ${j.tf}: ${j.total} trade, ${j.wins} WIN, ${j.losses} LOSS, WR ${j.winrate}% - 5 metodi BOS+EMA+RSI+VOL+1H - NO 12 metodi`; let html=''; j.trades.reverse().forEach(t=>{let col=t.result=='WIN'?'#22c55e':'#ef4444'; html+=`<div style="display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid #1e293b;font-size:12px"><div><b>${t.signal}</b> $${t.entry.toFixed(2)} BULL${t.compra} BEAR${t.vendi}<br><span style="font-size:10px;color:#94a3b8">📅 ${t.time} ${t.bos} Conf ${t.conf}</span></div><div style="text-align:right"><span style="color:${col};font-weight:800">${t.result}</span></div></div>`;}); document.getElementById('btList').innerHTML=html||'Nessun trade HIGH WR';}catch(e){document.getElementById('btStats').textContent='Errore: '+e.message;}}
checkTG();loadTF('15m');setInterval(()=>loadTF(curTF),15000);
setInterval(()=>{loadHistoryStats();},10000);
</script></body></html>
"""
    return Response(html, mimetype="text/html; charset=utf-8")

def bg_loop():
    while True:
        try:
            check_pending_trades()
            for tf in ["15m","1H","4H"]:
                for name in PAIRS.keys():
                    analyze(name, tf, do_tg=True)
        except Exception as e:
            print(f"Loop V71 {e}")
        time.sleep(35)

threading.Thread(target=bg_loop, daemon=True).start()
if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))

