# -*- coding: utf-8 -*-
from flask import Flask, jsonify, Response, request
import os, requests, time, json, threading
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
    def rome_now():
        return datetime.now(ZoneInfo("Europe/Rome"))
except:
    def rome_now():
        return datetime.now(timezone.utc) + timedelta(hours=2)

app = Flask(__name__)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
TELEGRAM_MIN_CONF = 75
PAIRS_LIVE = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "ORO": "PAXGUSDT"}
PAIRS_OHLC = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "ORO": "PAXGUSDT"}
TF_MAP = {"5m": "5m", "15m": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}
VERSION = "V57 DEBUG 75% - 1min cooldown"
LAST_TELEGRAM = {}
TELEGRAM_COOLDOWN = 60  # 1 min per debug

def send_telegram_signal(coin, tf, signal, conf, price, rsi, stoch, sl, tp, sl_pct, tp_pct, source, force=False):
    if not TELEGRAM_ENABLED:
        return {"ok": False, "error": "Telegram non configurato"}
    if not force and conf < TELEGRAM_MIN_CONF:
        return {"ok": False, "error": f"Conf {conf}% < soglia {TELEGRAM_MIN_CONF}%"}
    key = f"{coin}_{tf}"
    now = time.time()
    last = LAST_TELEGRAM.get(key, 0)
    if not force and now - last < TELEGRAM_COOLDOWN:
        return {"ok": False, "error": f"Cooldown {int((TELEGRAM_COOLDOWN - (now-last))/60)} min"}
    emoji = "🚀" if signal=="COMPRA" else "🔻" if signal=="VENDI" else "⏸️"
    tf_emoji = "⚡" if tf=="5m" else "🔍"
    text = f"""{emoji} *{signal} {coin} {conf}%* {tf_emoji} {tf} SCALP {'[FORCE]' if force else ''}

💰 Prezzo: ${price:.2f} ({source})
📊 RSI: {rsi} | Stoch: {stoch}
🎯 SL: ${sl:.2f} (-{sl_pct:.2f}%)
🎯 TP: ${tp:.2f} (+{tp_pct:.2f}%)
⏰ {rome_now().strftime('%H:%M:%S')} Europe/Rome

Soglia {TELEGRAM_MIN_CONF}% - Debug mode"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code==200:
            LAST_TELEGRAM[key]=now
            print(f"[{rome_now()}] Telegram INVIATO {coin} {conf}%")
            return {"ok": True, "sent": text}
        else:
            return {"ok": False, "error": f"Telegram API {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def ema_calc(data, period):
    if not data: return 0
    if len(data) < period: return sum(data)/len(data)
    k=2/(period+1)
    ema=sum(data[:period])/period
    for price in data[period:]: ema=price*k+ema*(1-k)
    return ema

def rsi_calc(closes, period=14):
    if len(closes) < period+1: return 50
    gains=0; losses=0
    for i in range(1, period+1):
        diff=closes[-i]-closes[-i-1]
        if diff>0: gains+=diff
        else: losses-=diff
    if losses==0: return 70 if gains>0 else 50
    rs=gains/losses if losses!=0 else 0
    return 100-(100/(1+rs))

def get_live_price_ticker(name):
    symbol=PAIRS_LIVE.get(name,"BTCUSDT")
    try:
        r=requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",timeout=2,headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code==200:
            return float(r.json()['price']), f"BINANCE:{symbol}"
    except: pass
    return None, "CACHE"

def fetch_binance_klines(symbol, interval, limit=200):
    try:
        url=f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        r=requests.get(url,timeout=4,headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code!=200: return []
        data=r.json()
        return [{"time":int(k[0]/1000),"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5])} for k in data]
    except: return []

def fetch_ohlc_with_fallback(name, interval, limit=200):
    symbol=PAIRS_OHLC.get(name,"BTCUSDT")
    ohlc=fetch_binance_klines(symbol,interval,limit)
    if ohlc and len(ohlc)>=20: return ohlc, "binance"
    return [], "fail"

def analyze_coin(name, tf, send_telegram=False):
    interval=TF_MAP.get(tf,"5m")
    live_price, source = get_live_price_ticker(name)
    ohlc, ohlc_src = fetch_ohlc_with_fallback(name, interval, 200)
    if not ohlc or len(ohlc)<20:
        if live_price is None: return None, None
        return {"price":live_price,"real_price":live_price,"close_price":live_price,"source":source,"ohlc_src":ohlc_src,"signal":"LOADING","conf":0,"quality_color":"loading","quality_label":"AGGIORNAMENTO","quality_score":0,"quality_simple":f"Scalp {tf}...","rsi":50,"rsi_fast":50,"ema9":live_price,"ema21":live_price,"ema50":live_price,"st_trend":0,"st_val":live_price,"stoch_k":50,"vwap":live_price,"support":live_price*0.998,"resistance":live_price*1.002,"adx":20,"vol_ratio":1.0,"sl":live_price*0.992,"tp":live_price*1.008,"sl_pct":0.8,"tp_pct":1.5,"spark": [live_price]*20}, None
    closes=[c["close"] for c in ohlc]
    close_price=closes[-1]
    price = live_price if live_price is not None else close_price
    ema9=ema_calc(closes,9); ema21=ema_calc(closes,21)
    rsi=rsi_calc(closes,14); rsi_fast=rsi_calc(closes,7)
    lows=[c["low"] for c in ohlc]; highs=[c["high"] for c in ohlc]
    support=min(lows[-10:]); resistance=max(highs[-10:])
    vwap=sum(closes[-20:])/20
    st_trend=1 if close_price>ema21 else -1; st_val=ema21
    try:
        low_min=min(lows[-14:]); high_max=max(highs[-14:])
        stoch_k=int((close_price-low_min)/(high_max-low_min)*100) if high_max!=low_min else 50
    except: stoch_k=50
    adx=20
    points=0; max_points=100
    if 50<=rsi<=65: points+=20
    elif 45<=rsi<50 or 65<rsi<=70: points+=15
    else: points+=5
    if close_price>ema9 and ema9>ema21: points+=30
    elif close_price>ema9: points+=15
    else: points+=5
    if st_trend==1: points+=25
    else: points+=10
    if 30<=stoch_k<=70: points+=25
    else: points+=5
    conf=int(points/max_points*100)
    conf=max(15,min(95,conf))
    sl_pct = 0.008; tp_pct = 0.015
    # DEBUG: soglia ENTRA bassissima a 60% per far scattare notifiche subito
    if conf>=60 and st_trend==1:
        signal="COMPRA"; quality_color="entra" if conf>=60 else "quasi"; quality_label="ENTRA" if conf>=60 else "QUASI"
        quality_simple=f"DEBUG {tf} LIVE ${price:.2f} RSI{int(rsi)} {conf}%"
    elif conf>=60 and st_trend==-1:
        signal="VENDI"; quality_color="entra" if conf>=60 else "quasi"; quality_label="ENTRA"
        quality_simple=f"DEBUG SHORT {tf} ${price:.2f} {conf}%"
    else:
        signal="ASPETTA"; quality_color="wait"; quality_label="ASPETTA"; quality_simple=f"DEBUG {tf} {conf}%"
    sl=price*(1-sl_pct) if signal=="COMPRA" else price*(1+sl_pct)
    tp=price*(1+tp_pct) if signal=="COMPRA" else price*(1-tp_pct)
    data={"price":price,"real_price":price,"close_price":close_price,"source":source,"ohlc_src":ohlc_src,"signal":signal,"conf":int(conf),"quality_color":quality_color,"quality_label":quality_label,"quality_score":int(conf),"quality_simple":quality_simple,"rsi":int(rsi),"rsi_fast":int(rsi_fast),"ema9":ema9,"ema21":ema21,"ema50":0,"st_trend":st_trend,"st_val":st_val,"stoch_k":stoch_k,"vwap":vwap,"support":support,"resistance":resistance,"adx":adx,"vol_ratio":1.0,"sl":sl,"tp":tp,"sl_pct":sl_pct*100,"tp_pct":tp_pct*100,"spark":closes[-30:]}
    telegram_result=None
    if send_telegram and quality_color=="entra" and conf>=TELEGRAM_MIN_CONF:
        telegram_result=send_telegram_signal(coin, tf, signal, conf, price, rsi, stoch_k, sl, tp, sl_pct*100, tp_pct*100, source)
        print(f"Scan {coin} conf {conf}% -> {telegram_result}")
    return data, telegram_result

@app.route("/")
def home():
    return Response(f"Bot {VERSION} - Soglia {TELEGRAM_MIN_CONF}% Cooldown {TELEGRAM_COOLDOWN}s - {rome_now()}", mimetype="text/plain")

@app.route("/api/signals")
def api_signals():
    tf=request.args.get("tf","5m")
    send_tg = request.args.get("telegram","0")=="1"
    result={}; tg_results={}
    for name in PAIRS_LIVE.keys():
        data, tg_res = analyze_coin(name,tf, send_telegram=send_tg)
        if data is None:
            data={"price":0,"signal":"LOADING","conf":0,"quality_color":"loading","quality_label":"LOAD","quality_score":0,"quality_simple":"...","rsi":50,"ema9":0,"ema21":0,"st_trend":0,"st_val":0,"stoch_k":50,"vwap":0,"support":0,"resistance":0,"adx":20,"sl":0,"tp":0,"sl_pct":0.8,"tp_pct":1.5,"spark":[]}
        result[name]=data
        if tg_res: tg_results[name]=tg_res
    return jsonify({"ok":True,"tf":tf,"coins":result,"telegram_results":tg_results,"telegram_enabled":TELEGRAM_ENABLED,"time":rome_now().isoformat(),"version":VERSION,"threshold":TELEGRAM_MIN_CONF,"cooldown":TELEGRAM_COOLDOWN,"last":LAST_TELEGRAM})

@app.route("/api/telegram_test")
def api_telegram_test():
    res = send_telegram_signal("BTC", "5m", "COMPRA", 85, 80168.00, 58, 62, 79500, 81300, 0.8, 1.5, "TEST", force=True)
    return jsonify(res)

@app.route("/api/force_telegram")
def api_force_telegram():
    # Manda subito ETH/BTC anche se conf bassa - per test
    results={}
    for name in PAIRS_LIVE.keys():
        price,_ = get_live_price_ticker(name)
        if price is None: price=80000
        res = send_telegram_signal(name, "5m", "COMPRA", 75, price, 56, 54, price*0.992, price*1.015, 0.8, 1.5, "FORCE TEST", force=True)
        results[name]=res
    return jsonify(results)

@app.route("/api/telegram_config")
def api_telegram_config():
    return jsonify({"enabled": TELEGRAM_ENABLED, "min_confidence": TELEGRAM_MIN_CONF, "cooldown_sec": TELEGRAM_COOLDOWN, "last_sent": LAST_TELEGRAM, "has_token": bool(TELEGRAM_BOT_TOKEN), "has_chat_id": bool(TELEGRAM_CHAT_ID)})

@app.route("/app")
def app_page():
    return Response("DEBUG MODE - Apri /api/signals?tf=5m&telegram=1 e /api/force_telegram per test immediato", mimetype="text/plain")

def background_loop():
    print(f"Background loop started - soglia {TELEGRAM_MIN_CONF}% cooldown {TELEGRAM_COOLDOWN}s")
    while True:
        try:
            for name in PAIRS_LIVE.keys():
                analyze_coin(name, "5m", send_telegram=True)
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(60)

threading.Thread(target=background_loop, daemon=True).start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
