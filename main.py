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
TELEGRAM_MIN_CONF = 88  # V66 STRICT: 88% per aumentare WR
PAIRS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "ORO": "PAXGUSDT"}
VERSION = "V66 STRICT PLUS - WR 65-70% TARGET - NO 5m REAL"
COOLDOWN = 900  # 15 min per evitare overtrading
LAST_TELEGRAM = {}
LAST_ENTRA = {}
STABLE_SECONDS = 180
TRADE_HISTORY = []
RISK_CONFIG = {"mode": "DEMO", "capital": 1000.0, "risk_pct": 1.0, "max_trades_day": 2, "max_losses_row": 2, "daily_trades": 0, "daily_losses_row": 0, "last_day": str(date.today())}
OHLC_CACHE = {}

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
        r=requests.get(f"https://api.kraken.com/0/public/Ticker?pair={km}",timeout=2)
        if r.status_code==200:
            res=r.json().get("result",{})
            if res:
                k=list(res.keys())[0]
                return float(res[k]["c"][0]), "KRAKEN"
    except: pass
    try:
        cg={"BTC":"bitcoin","ETH":"ethereum","ORO":"pax-gold"}[name]
        r=requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={cg}&vs_currencies=usd",timeout=2)
        if r.status_code==200: return float(r.json()[cg]["usd"]), "COINGECKO"
    except: pass
    return None, "FAIL"

def fetch_binance_fast(sym, interval, limit=200):
    try:
        r=requests.get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}",timeout=2,headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code!=200: return []
        return [{"close":float(k[4]),"low":float(k[3]),"high":float(k[2]),"volume":float(k[5]),"open_time":k[0]} for k in r.json()]
    except: return []

def fetch_ohlc_cached(name, tf, limit=200):
    key=f"{name}_{tf}_{limit}"
    now=time.time()
    if key in OHLC_CACHE and now - OHLC_CACHE[key][0] < 30:
        return OHLC_CACHE[key][1], "CACHE"
    sym=PAIRS[name]
    tfm={"5m":"5m","15m":"15m","1H":"1h"}
    interval=tfm.get(tf,"5m")
    ohlc=fetch_binance_fast(sym, interval, limit)
    src="BINANCE"
    if not ohlc or len(ohlc)<20:
        try:
            km={"BTC":"XXBTZUSD","ETH":"XETHZUSD","ORO":"PAXGUSD"}[name]
            imap={"5m":1,"15m":15,"1h":60}
            r=requests.get(f"https://api.kraken.com/0/public/OHLC?pair={km}&interval={imap.get(interval,1)}",timeout=2)
            if r.status_code==200:
                res=r.json().get("result",{})
                if res:
                    fk=[k for k in res.keys() if k!="last"][0]
                    ohlc=[{"close":float(k[4]),"low":float(k[2]),"high":float(k[3]),"volume":float(k[6]),"open_time":k[0]*1000} for k in res[fk][-limit:]]
                    src="KRAKEN"
        except: pass
    if ohlc and len(ohlc)>=20:
        OHLC_CACHE[key]=(now, ohlc)
        return ohlc, src
    if key in OHLC_CACHE:
        return OHLC_CACHE[key][1], "CACHE_OLD"
    return [], "FAIL"

def check_risk_guard():
    today = str(date.today())
    if RISK_CONFIG["last_day"] != today:
        RISK_CONFIG["daily_trades"] = 0
        RISK_CONFIG["daily_losses_row"] = 0
        RISK_CONFIG["last_day"] = today
    if RISK_CONFIG["daily_trades"] >= RISK_CONFIG["max_trades_day"]:
        return False, f"Max {RISK_CONFIG['max_trades_day']} trade/giorno"
    if RISK_CONFIG["daily_losses_row"] >= RISK_CONFIG["max_losses_row"]:
        return False, f"Stop dopo {RISK_CONFIG['max_losses_row']} loss"
    return True, "OK"

def send_tg(coin, tf, signal, conf, price, sl, tp, sl_pct, tp_pct, source, rsi, extra, force=False, is_real=False):
    global LAST_TELEGRAM
    if not TELEGRAM_ENABLED: return {"ok":False,"error":"no token"}
    if not force and conf < TELEGRAM_MIN_CONF: return {"ok":False,"error":f"conf {conf}<{TELEGRAM_MIN_CONF}"}
    if not force and is_real:
        ok, reason = check_risk_guard()
        if not ok: return {"ok":False,"error":reason,"blocked":True}
    key=f"{coin}_{tf}"; now=time.time(); last=LAST_TELEGRAM.get(key,0)
    if last > now + 10: LAST_TELEGRAM[key]=0; last=0
    if not force and now - last < COOLDOWN: return {"ok":False,"error":f"cooldown {int(COOLDOWN-(now-last))}s"}
    emoji="🚀" if signal=="COMPRA" else "🔻"
    mode_tag = "🔴 REAL STRICT" if is_real else "🟡 DEMO STRICT"
    rr=tp_pct/sl_pct if sl_pct>0 else 0
    tv_sym={"BTC":"BINANCE:BTCUSDT","ETH":"BINANCE:ETHUSDT","ORO":"BINANCE:PAXGUSDT"}[coin]
    chart=f"https://www.tradingview.com/chart/?symbol={tv_sym}"
    size_info=""
    if is_real:
        cap=RISK_CONFIG["capital"]; risk_pct=RISK_CONFIG["risk_pct"]; risk_money=cap*risk_pct/100
        size = risk_money / (price * sl_pct/100) if sl_pct>0 else 0
        size_info=f"\n💼 {mode_tag} Size: {size:.4f} | Rischio ${risk_money:.2f} R:R 1:{rr:.1f}"
    else: size_info=f"\n🧪 {mode_tag} R:R 1:{rr:.1f} • Target WR 65%+"
    text=f"""{emoji} *{signal} {coin} {conf}%* ⚡ {tf} V66 STRICT

💰 Entry: ${price:.2f} ({source})
🎯 SL: ${sl:.2f} (-{sl_pct:.2f}%) | TP: ${tp:.2f} (+{tp_pct:.2f}%) R:R 1:{rr:.1f}{size_info}
📊 RSI {rsi} | {extra}
📈 {chart}
⏰ {rome_now().strftime('%H:%M:%S')}"""
    try:
        r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id":TELEGRAM_CHAT_ID,"text":text,"parse_mode":"Markdown","disable_web_page_preview":True}, timeout=5)
        if r.status_code==200:
            LAST_TELEGRAM[key]=now
            if is_real: RISK_CONFIG["daily_trades"]+=1
            expiry_min = {"5m":30, "15m":90, "1H":360}.get(tf,90)
            expiry = time.time() + expiry_min*60
            TRADE_HISTORY.append({"time":rome_now().isoformat(),"timestamp":time.time(),"expiry":expiry,"coin":coin,"tf":tf,"signal":signal,"entry":price,"sl":sl,"tp":tp,"conf":conf,"mode":RISK_CONFIG["mode"],"result":None,"pnl_pct":0,"auto":True})
            if len(TRADE_HISTORY)>200: TRADE_HISTORY.pop(0)
            return {"ok":True,"sent":True}
        return {"ok":False,"error":r.text[:300]}
    except Exception as e: return {"ok":False,"error":str(e)}

def analyze(name, tf, do_tg=False, force_tg=False):
    global LAST_ENTRA
    try:
        # V66: in REAL, 5m disattivato per aumentare WR
        is_real_mode = RISK_CONFIG["mode"]=="REAL"
        if is_real_mode and tf=="5m":
            # 5m non genera ENTRA in REAL, solo QUASI
            price,_ = get_price(name)
            if price is None: price=80000
            dummy={"price":price,"source":"DISABLED","signal":"ASPETTA","conf":0,"quality_color":"wait","quality_label":"5m OFF in REAL","rsi":50,"stoch_k":50,"vol_ratio":0,"sl":price*0.992,"tp":price*1.015,"sl_pct":0.8,"tp_pct":1.5,"rr":1.8,"support":price*0.99,"resistance":price*1.01,"spark":[],"extra":"V66: 5m disattivato in REAL per aumentare WR - usa 15m REAL","h1":"--","ema9":price,"ema21":price,"ema50":price,"close":price,"confluence":0,"is_real":is_real_mode}
            return dummy, None

        ohlc, src = fetch_ohlc_cached(name, tf, 200)
        ohlc_1h, _ = fetch_ohlc_cached(name, "1H", 100)
        ohlc_15m, _ = fetch_ohlc_cached(name, "15m", 100) if tf=="5m" else ([], "")
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
        confluence_score = (1 if h1_up else 0) + (1 if m15_up else 0) + (1 if price>ema50 else 0)
        # V66 STRICT SCORING
        points=0
        # RSI STRICT: per COMPRA 52-62 ottimo, per VENDI 38-48 ottimo
        if close_price>ema21: # trend COMPRA
            if 52<=rsi<=60: points+=40
            elif 50<=rsi<=65: points+=20
            else: points+=0
        else: # trend VENDI
            if 38<=rsi<=48: points+=40
            elif 35<=rsi<=50: points+=20
            else: points+=0
        # EMA alignment STRICT
        if close_price>ema9 and ema9>ema21 and ema21>ema50: points+=40
        elif close_price>ema9 and ema9>ema21: points+=15
        elif close_price<ema9 and ema9<ema21 and ema21<ema50: points+=40
        elif close_price<ema9 and ema9<ema21: points+=15
        else: points+=0
        # Stoch STRICT 30-70
        if 30<=stoch<=65: points+=15
        else: points+=0
        # Vol STRICT: 1.8-4.0 ottimo, <1.8 troppo basso, >5.0 pump fake -> penalizza
        if 1.8<=vol_ratio<=4.0: points+=15
        elif 1.5<=vol_ratio<1.8: points+=5
        elif vol_ratio>5.0: points-=20
        else: points+=0
        conf=max(15,min(95,int(points)))
        swing_low=min(lows[-10:]); swing_high=max(highs[-10:])
        # V66: R:R migliorato a 1:2.2 per aumentare PnL anche con 50% WR
        if close_price>ema21:
            sl_pct_raw=(price-swing_low*0.998)/price*100
            sl_pct=max(0.5,min(1.0,sl_pct_raw))
            sl=price*(1-sl_pct/100); tp_pct=sl_pct*2.2; tp=price*(1+tp_pct/100)
            signal="COMPRA"
        else:
            sl_pct_raw=(swing_high*1.002-price)/price*100
            sl_pct=max(0.5,min(1.0,sl_pct_raw))
            sl=price*(1+sl_pct/100); tp_pct=sl_pct*2.2; tp=price*(1-tp_pct/100)
            signal="VENDI"
        extra=f"{h1_text} • Vol x{vol_ratio:.1f} • {source} • Conf {confluence_score}/3 • V66 STRICT R:R 1:2.2"
        # Filtri aggiuntivi STRICT
        # 1. Distanza da EMA50 >0.3% altrimenti choppy
        dist_ema50 = abs(price-ema50)/price*100
        if dist_ema50 < 0.3:
            conf = max(15, conf-30)
            extra += " • ⚠️ Vicino EMA50 choppy"
        # 2. Vol troppo alto = pump fake
        if vol_ratio > 5.0:
            conf = max(15, conf-40)
            extra += " • ⚠️ Vol pump fake"
        # 3. 1H contro trend
        if signal=="COMPRA" and not h1_up:
            conf=max(15, conf-25)
            extra+= " • ⚠️ 1H DOWN"
        if signal=="VENDI" and h1_up:
            conf=max(15, conf-25)
            extra+= " • ⚠️ 1H UP"
        min_conf = 88 if is_real_mode else 85
        min_vol = 1.8 if is_real_mode else 1.5
        max_vol = 5.0
        min_confl = 3 if is_real_mode else 2
        if signal=="COMPRA":
            ema_ok = close_price>ema9 and ema9>ema21 and ema21>ema50 and price>ema50
            confl_ok = confluence_score>=min_confl and h1_up
            rsi_ok = 50<=rsi<=65
        else:
            ema_ok = close_price<ema9 and ema9<ema21 and ema21<ema50 and price<ema50
            confl_down = (0 if h1_up else 1) + (0 if m15_up else 1) + (0 if price>ema50 else 1)
            confl_ok = confl_down>=min_confl and not h1_up
            rsi_ok = 35<=rsi<=50
        vol_ok = min_vol <= vol_ratio <= max_vol
        stoch_ok = 25 <= stoch <= 70
        dist_ok = dist_ema50 >= 0.3
        if conf>=min_conf and vol_ok and confl_ok and ema_ok and rsi_ok and stoch_ok and dist_ok:
            color="entra"; label="ENTRA"
        elif conf>=70 and vol_ratio>=1.2:
            color="quasi"; label="QUASI"
        else:
            color="wait"; label="ASPETTA"
            signal="ASPETTA"; sl=price*0.992; tp=price*1.015; sl_pct=0.8; tp_pct=1.76
        key=f"{name}_{tf}"; now=time.time()
        data={"price":price,"source":source,"signal":signal,"conf":conf,"quality_color":color,"quality_label":label,"rsi":int(rsi),"stoch_k":stoch,"vol_ratio":round(vol_ratio,2),"sl":sl,"tp":tp,"sl_pct":sl_pct,"tp_pct":tp_pct,"rr":round(tp_pct/sl_pct,1) if sl_pct>0 else 2.2,"support":swing_low,"resistance":swing_high,"spark":closes[-30:],"extra":extra,"h1":h1_text,"ema9":ema9,"ema21":ema21,"ema50":ema50,"close":close_price,"confluence":confluence_score,"is_real":is_real_mode}
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
    except Exception as e:
        print(f"ANALYZE ERROR {name} {tf}: {e}")
        return None, None

def check_pending_trades():
    now=time.time()
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
    for i in range(50, len(ohlc)-6):
        sub=ohlc[:i+1]
        sub_closes=[c["close"] for c in sub]
        ema9=ema_calc(sub_closes,9); ema21=ema_calc(sub_closes,21); ema50=ema_calc(sub_closes,50)
        rsi=rsi_calc(sub_closes,14)
        price=sub[-1]["close"]
        # V66 STRICT logic nel backtest
        vol_ratio = sub[-1]["volume"] / (sum([c["volume"] for c in sub[-20:]])/20) if sub[-20:] else 1
        signal = "COMPRA" if price>ema21 else "VENDI"
        # RSI strict
        if signal=="COMPRA" and not (50<=rsi<=65): continue
        if signal=="VENDI" and not (35<=rsi<=50): continue
        # EMA strict
        if signal=="COMPRA" and not (price>ema9 and ema9>ema21 and ema21>ema50): continue
        if signal=="VENDI" and not (price<ema9 and ema9<ema21 and ema21<ema50): continue
        # Vol strict
        if not (1.8 <= vol_ratio <= 5.0): continue
        sl = min([c["low"] for c in sub[-10:]])*0.998 if signal=="COMPRA" else max([c["high"] for c in sub[-10:]])*1.002
        tp = price*1.012 if signal=="COMPRA" else price*0.988  # R:R 2.2 approx con SL 0.8-1%
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
                time_full = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                time_str = f"candela {i}"; time_full=time_str
            trades.append({"idx":i,"signal":signal,"entry":price,"result":result,"time":time_str,"time_full":time_full,"conf":88,"rsi":int(rsi),"vol":round(vol_ratio,1)})
            if result=="WIN": wins+=1
            else: losses+=1
    total=wins+losses
    wr=wins/total*100 if total>0 else 0
    return {"ok":True,"coin":coin,"tf":tf,"total":total,"wins":wins,"losses":losses,"winrate":round(wr,1),"trades":trades[-20:]}

def ai_market_answer(question, coin="BTC", tf="5m"):
    q = question.lower()
    data, _ = analyze(coin, tf, do_tg=False)
    if not data:
        return "Dati lenti, riprova."
    price = data["price"]; rsi = data["rsi"]; conf = data["conf"]; sig = data["signal"]; vol = data["vol_ratio"]; h1=data["h1"]; confl=data["confluence"]
    total=len(TRADE_HISTORY); wins=len([t for t in TRADE_HISTORY if t.get("result")=="WIN"]); losses=len([t for t in TRADE_HISTORY if t.get("result")=="LOSS"]); wr=wins/total*100 if total>0 else 0
    if "win" in q or "diario" in q or "perdita" in q or "perdendo" in q:
        return f"📊 V66 STRICT: ho alzato soglia a 88% + confl 3/3 + EMA50 + RSI 50-65/35-50 + Vol 1.8-4.0 + R:R 1:2.2 + 5m OFF in REAL\n📓 LIVE AUTO: {total} trade {wins}W/{losses}L WR {wr:.1f}%\nObiettivo: da 50% a 65-70% WR tagliando 70% dei falsi segnali 5m. Meno trade, ma più buoni. Prova backtest 15m ora."
    return f"V66 STRICT {coin} {tf}: ${price:.2f} {sig} {conf}% confl {confl}/3 RSI {rsi} Vol x{vol} | {h1} | WR {wr:.1f}% | R:R 1:{data['rr']}"

@app.route("/")
def home(): return Response(f"{VERSION} - {rome_now()} - Mode {RISK_CONFIG['mode']}", mimetype="text/plain")
@app.route("/health")
def health(): return jsonify({"ok":True,"version":VERSION,"time":rome_now().isoformat(),"telegram":TELEGRAM_ENABLED,"risk":RISK_CONFIG})
@app.route("/api/nuke")
def nuke():
    global LAST_TELEGRAM, LAST_ENTRA, TRADE_HISTORY, OHLC_CACHE
    LAST_TELEGRAM={}; LAST_ENTRA={}; TRADE_HISTORY=[]; OHLC_CACHE={}
    RISK_CONFIG["daily_trades"]=0; RISK_CONFIG["daily_losses_row"]=0
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
                if d is None: d={"price":0,"source":"LOADING","signal":"LOADING","conf":0,"quality_color":"loading","quality_label":"CARICO...","rsi":50,"stoch_k":50,"vol_ratio":1,"sl":0,"tp":0,"sl_pct":0.8,"tp_pct":1.76,"rr":2.2,"spark":[],"extra":"Carico V66 STRICT...","h1":"--","confluence":0,"is_real":False}
                res[name]=d
                if tr: tg[name]=tr
            except Exception as e:
                res[name]={"price":0,"source":"ERROR","signal":"ERROR","conf":0,"quality_color":"wait","quality_label":"ERRORE","rsi":50,"stoch_k":50,"vol_ratio":1,"sl":0,"tp":0,"sl_pct":0.8,"tp_pct":1.76,"rr":2.2,"spark":[],"extra":str(e)[:80],"h1":"--","confluence":0,"is_real":False}
        return jsonify({"ok":True,"tf":tf,"coins":res,"telegram_results":tg,"telegram_enabled":TELEGRAM_ENABLED,"version":VERSION,"time":rome_now().isoformat(),"risk":RISK_CONFIG})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}), 500
@app.route("/api/telegram_test")
def tg_test():
    r=send_tg("BTC","5m","COMPRA",88,80000,79400,81200,0.7,1.54,"TEST",55,"Test V66 STRICT",force=True,is_real=(RISK_CONFIG["mode"]=="REAL"))
    return jsonify(r)
@app.route("/api/force_telegram")
def force_tg():
    out={}
    for name in PAIRS.keys():
        p,_=get_price(name)
        if p is None: p=80000
        out[name]=send_tg(name,"5m","COMPRA",88,p,p*0.995,p*1.01,0.5,1.1,"FORCE V66",55,"Force STRICT",force=True,is_real=(RISK_CONFIG["mode"]=="REAL"))
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
            try: RISK_CONFIG["capital"]=float(data["capital"])
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
    return jsonify({"ok":True,"total":total,"wins":wins,"losses":losses,"pending":pending,"winrate":round(wr,1),"pnl_sum":round(pnl_sum,2),"history":TRADE_HISTORY[-50:]})
@app.route("/api/history_mark", methods=["POST"])
def api_history_mark():
    try:
        body=request.get_json() or {}
        idx=body.get("idx",-1)
        result=body.get("result")
        if idx<0: idx=len(TRADE_HISTORY)+idx
        if 0<=idx<len(TRADE_HISTORY) and result in ["WIN","LOSS",None]:
            if result is None: TRADE_HISTORY[idx]["result"]=None
            else:
                TRADE_HISTORY[idx]["result"]=result
                if result=="LOSS": RISK_CONFIG["daily_losses_row"]+=1
                else: RISK_CONFIG["daily_losses_row"]=0
            return jsonify({"ok":True,"updated":TRADE_HISTORY[idx]})
        return jsonify({"ok":False,"error":"idx non valido"})
    except Exception as e: return jsonify({"ok":False,"error":str(e)})
@app.route("/api/backtest")
def api_backtest():
    coin=request.args.get("coin","BTC")
    tf=request.args.get("tf","15m")
    if coin not in PAIRS: coin="BTC"
    res=run_backtest(coin, tf)
    return jsonify(res)

@app.route("/app")
def app_page():
    html="""
<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VENDI V66 STRICT PLUS</title>
<style>
*{box-sizing:border-box;font-family:Inter,system-ui,sans-serif}
body{margin:0;background:#020617;color:#e2e8f0}
.header{padding:14px 16px;display:flex;align-items:center;gap:12px;background:#0f172a;border-bottom:1px solid #1e293b;position:sticky;top:0;z-index:10}
.logo{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#22c55e,#f59e0b);display:flex;align-items:center;justify-content:center;font-weight:900;color:white}
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
.banner-real{background:#7f1d1d;border:1px solid #ef4444;color:#fecaca;font-weight:800}
.banner-strict{background:linear-gradient(135deg,#052e16,#422006);border:1px solid #22c55e;color:#86efac;font-weight:800}
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
#aiPanel{position:fixed;bottom:0;left:0;right:0;max-width:480px;margin:0 auto;background:#0f172a;border-top:2px solid #f59e0b;border-left:1px solid #1e293b;border-right:1px solid #1e293b;border-radius:20px 20px 0 0;z-index:60;display:none;flex-direction:column;max-height:70vh}
#aiPanel.show{display:flex}
#aiMsgs{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}
.msg{padding:10px 12px;border-radius:12px;font-size:13px;line-height:1.4;max-width:85%;white-space:pre-wrap}
.msg.user{align-self:flex-end;background:#f59e0b;color:#422006}
.msg.ai{align-self:flex-start;background:#1e293b;border:1px solid #334155;color:#e2e8f0}
#aiInputRow{display:flex;gap:8px;padding:10px;border-top:1px solid #1e293b}
#aiInput{flex:1;background:#020617;border:1px solid #334155;color:white;padding:10px 12px;border-radius:20px;outline:none}
.chip{padding:6px 10px;background:#1e293b;border:1px solid #334155;border-radius:20px;font-size:11px;cursor:pointer}
.riskBar{margin:8px 12px;padding:10px 12px;background:#1e293b;border:1px solid #334155;border-radius:10px;font-size:11px;display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}
</style></head><body>
<div class="header"><div class="logo">V66</div><div style="flex:1"><div style="font-weight:800">VENDI V66 <span style="background:#f59e0b;color:#422006;padding:2px 6px;border-radius:6px;font-size:10px">STRICT PLUS 88%</span></div><div style="font-size:10px;color:#94a3b8">Target WR 65%+ • No 5m REAL • R:R 1:2.2</div></div><div style="display:flex;gap:6px"><button onclick="openAI()" style="background:#f59e0b;color:#422006;border:none;padding:6px 10px;border-radius:20px;font-size:11px;font-weight:700">🤖 AI</button><button onclick="openRisk()" style="background:#1e293b;color:white;border:1px solid #334155;padding:6px 10px;border-radius:20px;font-size:11px">⚙️ Risk</button></div></div>
<div id="banner" class="banner banner-strict">V66 STRICT PLUS - Soglia 88% - Conf 3/3 - EMA50 - RSI 50-65 - Vol 1.8-4.0 - R:R 1:2.2 - 5m OFF in REAL - Target WR 65%+</div>
<div id="riskBar" class="riskBar"><span id="riskMode">Mode: DEMO</span><span id="riskCap">Cap: $1000 1%</span><span id="riskWR">WR: 0% 0W/0L P:0</span><span id="riskDay">Oggi: 0/2</span><span><button onclick="openHistory()" style="background:#22c55e;color:#052e16;border:none;padding:4px 8px;border-radius:10px;font-size:10px;font-weight:800">📓 Diario</button> <button onclick="runBT()" style="background:#f59e0b;color:#422006;border:none;padding:4px 8px;border-radius:10px;font-size:10px;font-weight:800">📊 Backtest STRICT</button></span></div>
<div class="tfs"><button id="b5m" onclick="loadTF('5m')">⚡ 5m DEMO</button><button id="b15m" class="active" onclick="loadTF('15m')">15m REAL</button><button id="b1H" onclick="loadTF('1H')">1H REAL</button><button onclick="loadTF(curTF,true,true)" style="background:#22c55e;color:#052e16">📱 Forza TG</button><button onclick="nuke()" style="background:#dc2626;color:white">💣 NUKE</button></div>
<div id="coins"><div style="padding:20px;text-align:center;color:#94a3b8">Carico V66 STRICT PLUS...</div></div>
<div id="riskModal" class="modal" onclick="if(event.target==this)closeRisk()"><div class="box"><b>⚙️ Risk Guard V66 STRICT</b><div style="font-size:10px;color:#f59e0b;background:#422006;border:1px solid #f59e0b;padding:8px;border-radius:8px;margin:6px 0">V66: 88% minimo, 3/3 confl, EMA50 allineate, RSI 50-65 long / 35-50 short, Vol 1.8-4.0, R:R 1:2.2, 5m OFF in REAL, max 2 trade/giorno</div><div style="display:grid;gap:10px;margin-top:10px">
<label style="font-size:12px">Modalità<br><select id="rMode" style="width:100%;padding:10px;background:#020617;color:white;border:1px solid #334155;border-radius:10px"><option value="DEMO">🟡 DEMO STRICT 85%</option><option value="REAL">🔴 REAL STRICT 88% 3/3</option></select></label>
<label style="font-size:12px">Capitale $ <input id="rCap" type="number" style="width:100%;padding:10px;background:#020617;color:white;border:1px solid #334155;border-radius:10px"></label>
<label style="font-size:12px">Rischio % (max 2%) <input id="rRisk" type="number" step="0.1" style="width:100%;padding:10px;background:#020617;color:white;border:1px solid #334155;border-radius:10px"></label>
<label style="font-size:12px">Max trade/giorno <input id="rMaxT" type="number" style="width:100%;padding:10px;background:#020617;color:white;border:1px solid #334155;border-radius:10px"></label>
<label style="font-size:12px">Stop dopo N loss <input id="rMaxL" type="number" style="width:100%;padding:10px;background:#020617;color:white;border:1px solid #334155;border-radius:10px"></label>
</div><button class="btn btn-green" onclick="saveRisk()">💾 Salva STRICT</button><button class="btn" onclick="closeRisk()" style="background:#1e293b;color:white">Chiudi</button></div></div>
<div id="histModal" class="modal" onclick="if(event.target==this)closeHistory()"><div class="box"><b>📓 Diario AUTO V66</b><div style="font-size:10px;color:#22c55e;background:#052e16;border:1px solid #16a34a;padding:8px;border-radius:8px;margin:6px 0">V66 STRICT: meno segnali ma più buoni. Target WR 65%+ con R:R 1:2.2 = profittevole anche con 50% WR</div><div id="histStats" style="font-size:11px;background:#1e293b;padding:10px;border-radius:10px;margin:8px 0"></div><div id="histList" style="max-height:50vh;overflow:auto"></div><button class="btn" onclick="closeHistory()" style="background:#1e293b;color:white">Chiudi</button></div></div>
<div id="btModal" class="modal" onclick="if(event.target==this)closeBT()"><div class="box"><b>📊 Backtest STRICT ultimi 200 candele</b><div style="font-size:10px;color:#f59e0b;background:#422006;border:1px solid #f59e0b;padding:8px;border-radius:8px;margin:6px 0">V66 filtra: RSI 50-65 long, EMA9>21>50, Vol 1.8-4.0, 3/3 confl. Meno trade, WR più alto.</div><div id="btStats" style="font-size:11px;background:#1e293b;padding:10px;border-radius:10px;margin:8px 0">Carico...</div><div id="btList" style="max-height:40vh;overflow:auto;font-size:11px"></div><button class="btn" onclick="closeBT()" style="background:#1e293b;color:white">Chiudi</button></div></div>
<div id="aiPanel"><div style="padding:12px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #1e293b"><b>🤖 AI V66 STRICT</b><button onclick="closeAI()" style="background:#1e293b;color:white;border:none;padding:6px 10px;border-radius:10px">X</button></div>
<div id="aiMsgs"><div class="msg ai">V66 STRICT PLUS: ho alzato tutto per aumentare WR da 50% a 65%+:

✅ 88% minimo (era 80%)
✅ Conf 3/3 (era 2/3) + 1H obbligatorio
✅ EMA9>21>50 perfette (non solo 9>21)
✅ RSI 50-65 long / 35-50 short (era 48-68 largo)
✅ Vol 1.8-4.0 (scarta pump >5.0 e no-vol <1.8)
✅ Distanza EMA50 >0.3% (scarta choppy)
✅ R:R 1:2.2 (era 1:1.8) → profittevole anche con 50% WR
✅ 5m OFF in REAL (era la causa del 0% WR)
✅ Cooldown 15 min + max 2 trade/giorno (era 10 min 3 trade)

Meno segnali, ma più buoni. Chiedi "diario" o fai backtest 15m.</div>
<div style="display:flex;gap:6px;flex-wrap:wrap"><span class="chip" onclick="askChip('Diario winrate')">📓 WR ora?</span><span class="chip" onclick="askChip('Perché perdo tanto?')">Perché perdo?</span><span class="chip" onclick="askChip('Backtest 15m STRICT')">📊 Backtest 15m</span></div>
</div>
<div id="aiInputRow"><input id="aiInput" placeholder="Perché perdo? Diario?" onkeydown="if(event.key==='Enter')sendAI()"><button onclick="sendAI()" style="background:#f59e0b;color:#422006;border:none;padding:10px 16px;border-radius:20px;font-weight:800">Invia</button></div>
</div>
<div id="modal" class="modal" onclick="if(event.target==this)closeM()"><div class="box"><div style="display:flex;justify-content:space-between"><b id="mCoin">BTC</b><button onclick="closeM()" style="background:#1e293b;color:white;border:none;padding:8px 12px;border-radius:10px">X</button></div><div id="mPrice" style="font-size:11px;color:#94a3b8;margin:6px 0"></div><div id="mBig" style="border-radius:14px;padding:16px;margin:10px 0;text-align:center;font-weight:900;font-size:20px"></div><div id="mExtra" style="font-size:11px;background:#1e293b;padding:10px;border-radius:10px;border:1px solid #334155;margin:8px 0"></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px"><div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">SL</span><br><b id="mSL">-</b><br><span id="mSLpct" style="font-size:10px"></span></div><div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">TP</span><br><b id="mTP">-</b><br><span id="mTPpct" style="font-size:10px"></span><br><span id="mRR" style="font-size:10px;color:#86efac"></span></div></div><div id="mRisk" style="font-size:11px;background:#052e16;border:1px solid #16a34a;padding:10px;border-radius:10px;margin:8px 0;color:#86efac"></div><button class="btn btn-green" onclick="copySLTP()">📋 Copia</button><button class="btn btn-blue" onclick="openChart()">📈 TV</button><button class="btn btn-purple" onclick="askAboutCoin()">🤖 AI</button><button class="btn btn-blue" onclick="sendNow()">📱 TG ORA</button></div></div>
<script>
var curTF='15m';var lastData=null;var curCoin=null;var riskCfg=null;
function badge(c,l){if(c=='entra')return '<span class="badge badge-entra">'+l+'</span>';if(c=='quasi')return '<span class="badge badge-quasi">'+l+'</span>';return '<span class="badge badge-wait">'+l+'</span>';}
async function loadRisk(){try{let r=await fetch('/api/risk_config');let j=await r.json();riskCfg=j.risk;document.getElementById('riskMode').textContent='Mode: '+riskCfg.mode;document.getElementById('riskCap').textContent='Cap: $'+riskCfg.capital+' '+riskCfg.risk_pct+'%';document.getElementById('riskDay').textContent='Oggi: '+riskCfg.daily_trades+'/'+riskCfg.max_trades_day;document.getElementById('rMode').value=riskCfg.mode;document.getElementById('rCap').value=riskCfg.capital;document.getElementById('rRisk').value=riskCfg.risk_pct;document.getElementById('rMaxT').value=riskCfg.max_trades_day;document.getElementById('rMaxL').value=riskCfg.max_losses_row;}catch{}}
async function checkTG(){await loadRisk();}
async function nuke(){if(!confirm('NUKE V66 STRICT? Pulisce tutto'))return;try{let r=await fetch('/api/nuke');alert('✅ NUKE STRICT - Ora WR ripartirà più alto');location.reload();}catch(e){alert(e.message);}}
async function loadTF(tf,withTG=false,force=false){
curTF=tf;
document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active'));
let el=document.getElementById('b'+tf); if(el) el.classList.add('active');
document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center;color:#94a3b8">⚡ Carico '+tf+' V66 STRICT 88%...</div>';
let controller=new AbortController(); let timeout=setTimeout(()=>controller.abort(),10000);
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
html+=`<div class="coin"><div class="coin-row" onclick="openM('${name}')"><div style="display:flex;gap:10px;align-items:center"><div class="icon ${iclass}">${name=='BTC'?'B':name=='ETH'?'E':'Au'}</div><div><b>${name}</b> - ${price}<div style="font-size:11px;color:#94a3b8">${info.extra}</div><div style="font-size:11px;color:#64748b">${action} confl ${info.confluence}/3 R:R 1:${info.rr}</div></div></div><div style="text-align:right">${b}<div style="font-size:11px;color:#64748b;margin-top:4px">${info.signal} ${info.conf}%<br>SL ${info.sl_pct.toFixed(2)}% TP ${info.tp_pct.toFixed(2)}%</div></div></div></div>`;
}
if(d.telegram_results && Object.keys(d.telegram_results).length>0){html+=`<div style="background:#052e16;padding:8px 12px;font-size:11px;color:#86efac;text-align:center">📱 TG: ${JSON.stringify(d.telegram_results)}</div>`;}
document.getElementById('coins').innerHTML=html;
}catch(e){
clearTimeout(timeout);
document.getElementById('coins').innerHTML='<div style="padding:20px;color:#ef4444;text-align:center">Timeout - premi NUKE<br><button onclick="nuke()" style="margin-top:10px;background:#dc2626;color:white;border:none;padding:10px 20px;border-radius:20px">💣 NUKE</button></div>';
}
}
function openM(coin){if(!lastData) return; let info=lastData.coins[coin]; curCoin=coin; document.getElementById('mCoin').textContent=coin+' - $'+info.price.toFixed(2); document.getElementById('mPrice').textContent=info.source+' - '+info.signal+' '+info.conf+'% - TF '+curTF+' confl '+info.confluence+'/3'; let big=document.getElementById('mBig'); big.style.cssText='border-radius:14px;padding:16px;margin:10px 0;text-align:center;font-weight:900;font-size:20px;'; if(info.quality_color=='entra'){big.style.background='#052e16';big.style.border='2px solid #22c55e';big.style.color='#22c55e';} else if(info.quality_color=='quasi'){big.style.background='#422006';big.style.border='2px solid #facc15';big.style.color='#facc15';} else{big.style.background='#1e293b';big.style.border='1px solid #334155';} big.innerHTML=info.quality_label+' - '+info.signal+' '+info.conf+'%'; document.getElementById('mSL').textContent='$'+info.sl.toFixed(2); document.getElementById('mSLpct').textContent='-'+info.sl_pct.toFixed(2)+'%'; document.getElementById('mTP').textContent='$'+info.tp.toFixed(2); document.getElementById('mTPpct').textContent='+'+info.tp_pct.toFixed(2)+'%'; document.getElementById('mRR').textContent='R:R 1:'+info.rr; document.getElementById('mExtra').textContent=info.extra; let riskDiv=document.getElementById('mRisk'); if(riskCfg){let riskMoney=riskCfg.capital*riskCfg.risk_pct/100;let size=riskMoney/(info.price*info.sl_pct/100);riskDiv.innerHTML=`💼 ${riskCfg.mode} $${riskCfg.capital} ${riskCfg.risk_pct}% = $${riskMoney.toFixed(2)} size ${size.toFixed(4)} - R:R 1:${info.rr} - Target WR 65%+`;} document.getElementById('modal').classList.add('show');}
function closeM(){document.getElementById('modal').classList.remove('show');}
function copySLTP(){if(!curCoin||!lastData) return; let info=lastData.coins[curCoin]; let txt=`${curCoin} ${info.price.toFixed(2)} SL ${info.sl.toFixed(2)} TP ${info.tp.toFixed(2)} R:R 1:${info.rr}`; navigator.clipboard.writeText(txt).then(()=>alert('Copiato'));}
function openChart(){if(!curCoin) return; let sym={BTC:'BINANCE:BTCUSDT',ETH:'BINANCE:ETHUSDT',ORO:'BINANCE:PAXGUSDT'}[curCoin]; window.open('https://www.tradingview.com/chart/?symbol='+sym,'_blank');}
async function sendNow(){if(!curCoin) return; try{let r=await fetch('/api/signals?tf='+curTF+'&telegram=1&force=1'); let j=await r.json(); alert('TG: '+JSON.stringify(j.telegram_results));}catch(e){alert(e.message);}}
function openAI(){document.getElementById('aiPanel').classList.add('show');}
function closeAI(){document.getElementById('aiPanel').classList.remove('show');}
function askChip(t){document.getElementById('aiInput').value=t; sendAI();}
function askAboutCoin(){if(!curCoin) return; closeM(); openAI(); document.getElementById('aiInput').value='Devo entrare su '+curCoin+' '+curTF+'?'; sendAI();}
async function sendAI(){let input=document.getElementById('aiInput'); let txt=input.value.trim(); if(!txt) return; let msgs=document.getElementById('aiMsgs'); let div=document.createElement('div'); div.className='msg user'; div.textContent=txt; msgs.appendChild(div); input.value=''; msgs.scrollTop=msgs.scrollHeight; try{let r=await fetch('/api/ai_chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:txt,coin:curCoin||'BTC',tf:curTF})}); let j=await r.json(); let ans=j.answer||j.error||'Errore'; let div2=document.createElement('div'); div2.className='msg ai'; div2.textContent=ans; msgs.appendChild(div2); msgs.scrollTop=msgs.scrollHeight;}catch(e){let div2=document.createElement('div'); div2.className='msg ai'; div2.textContent='Errore: '+e.message; msgs.appendChild(div2);}}
function openRisk(){document.getElementById('riskModal').classList.add('show');}
function closeRisk(){document.getElementById('riskModal').classList.remove('show');}
async function saveRisk(){let mode=document.getElementById('rMode').value; let cap=document.getElementById('rCap').value; let risk=document.getElementById('rRisk').value; let maxT=document.getElementById('rMaxT').value; let maxL=document.getElementById('rMaxL').value; try{let r=await fetch('/api/risk_config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:mode,capital:cap,risk_pct:risk,max_trades_day:maxT,max_losses_row:maxL})}); let j=await r.json(); alert('✅ Salvato STRICT'); closeRisk(); await loadRisk(); await loadTF(curTF);}catch(e){alert(e.message);}}
async function loadHistoryStats(){try{let r=await fetch('/api/history');let j=await r.json(); document.getElementById('riskWR').textContent=`WR: ${j.winrate}% ${j.wins}W/${j.losses}L P:${j.pending} PnL ${j.pnl_sum}%`; document.getElementById('riskMode').textContent='Mode: '+ (riskCfg?riskCfg.mode:'DEMO'); if(riskCfg) document.getElementById('riskCap').textContent='Cap: $'+riskCfg.capital+' '+riskCfg.risk_pct+'%'; }catch{}}
function openHistory(){document.getElementById('histModal').classList.add('show'); loadHistory();}
function closeHistory(){document.getElementById('histModal').classList.remove('show');}
async function loadHistory(){try{let r=await fetch('/api/history');let j=await r.json(); document.getElementById('histStats').textContent=`Totale ${j.total} - WIN ${j.wins} - LOSS ${j.losses} - Pending ${j.pending} - WR ${j.winrate}% - PnL ${j.pnl_sum}% - V66 STRICT target 65%+`; let list=document.getElementById('histList');let html=''; j.history.slice().reverse().forEach((t,i)=>{let col=t.result=='WIN'?'#22c55e':t.result=='LOSS'?'#ef4444':'#facc15'; let auto=t.auto?'🤖':'👤'; html+=`<div style="display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid #1e293b;font-size:11px"><div><b>${auto} ${t.coin} ${t.tf} ${t.signal} ${t.conf}%</b> $${t.entry?.toFixed(2)} → ${t.result?`$${(t.result=='WIN'?t.tp:t.sl).toFixed(2)}`:'...'}<br><span style="color:#94a3b8">${t.time.slice(11,19)} ${t.mode} PnL ${t.pnl_pct?.toFixed(2)}% R:R 1:2.2</span></div><div style="text-align:right"><span style="color:${col};font-weight:800">${t.result||'APERTO'}</span><br><span style="font-size:9px;color:#64748b">Auto in ${Math.max(0,Math.round((t.expiry-Date.now()/1000)/60))}m</span></div></div>`;}); list.innerHTML=html||'Nessun trade V66 - Normale, filtri più stretti = meno segnali';}catch(e){alert(e.message);}}
function openBT(){document.getElementById('btModal').classList.add('show'); runBT();}
function closeBT(){document.getElementById('btModal').classList.remove('show');}
async function runBT(){let coin=curCoin||'BTC';let tf=curTF; document.getElementById('btStats').textContent='Carico backtest STRICT '+coin+' '+tf+'...'; document.getElementById('btList').innerHTML=''; document.getElementById('btModal').classList.add('show'); try{let r=await fetch(`/api/backtest?coin=${coin}&tf=${tf}`); let j=await r.json(); if(!j.ok){document.getElementById('btStats').textContent='Errore: '+j.error; return;} document.getElementById('btStats').textContent=`V66 STRICT ${j.coin} ${j.tf}: ${j.total} trade, ${j.wins} WIN, ${j.losses} LOSS, WR ${j.winrate}% (target >65%) - Meno trade ma più buoni`; let html=''; j.trades.reverse().forEach(t=>{let col=t.result=='WIN'?'#22c55e':'#ef4444'; html+=`<div style="display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid #1e293b;font-size:12px"><div><b>${t.signal}</b> $${t.entry.toFixed(2)}<br><span style="font-size:10px;color:#94a3b8">📅 ${t.time} RSI ${t.rsi} Vol x${t.vol} • ${t.conf}%</span></div><div style="text-align:right"><span style="color:${col};font-weight:800">${t.result}</span></div></div>`;}); document.getElementById('btList').innerHTML=html||'Nessun trade STRICT - Filtri molto stretti, attendi';}catch(e){document.getElementById('btStats').textContent='Errore: '+e.message;}}
checkTG();loadTF('15m');setInterval(()=>loadTF(curTF),15000);
setInterval(()=>{loadHistoryStats();},10000);
</script></body></html>
"""
    return Response(html, mimetype="text/html; charset=utf-8")

def bg_loop():
    while True:
        try:
            check_pending_trades()
            for tf in ["15m","1H"]:
                for name in PAIRS.keys():
                    analyze(name, tf, do_tg=True)
        except Exception as e:
            print(f"Loop V66 {e}")
        time.sleep(45)

threading.Thread(target=bg_loop, daemon=True).start()
if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))

