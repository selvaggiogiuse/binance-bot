# -*- coding: utf-8 -*-
from flask import Flask, jsonify, Response, request, make_response
import os, requests, time, json, threading
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
    def rome_now():
        return datetime.now(ZoneInfo("Europe/Rome"))
    def rome_today_str():
        return datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d")
except:
    def rome_now():
        return datetime.now(timezone.utc) + timedelta(hours=2)
    def rome_today_str():
        return (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%d")

app = Flask(__name__)

# --- CONFIG ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
APP_PASSWORD = os.getenv("APP_PASSWORD", "")  # metti una password su Render per proteggere /app
CAPITAL = float(os.getenv("CAPITAL", "1000"))  # capitale in $ per calcolo lotto
RISK_PCT = float(os.getenv("RISK_PCT", "1.0"))  # rischio % a trade

TELEGRAM_MIN_CONF = 75
PAIRS_LIVE = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "ORO": "PAXGUSDT"}
TF_MAP = {"5m": "5m", "15m": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}
VERSION = "V58 PRO - REAL MONEY - 3 COIN - RISK MGMT"

LAST_TELEGRAM = {}
TELEGRAM_COOLDOWN = 600
TRADE_HISTORY_FILE = "trade_history.json"
LAST_TG_FILE = "last_telegram.json"
DAILY_STATS_FILE = "daily_stats.json"

# --- PERSISTENZA SU FILE (sopravvive ai restart brevi) ---
def load_json_file(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except: pass
    return default

def save_json_file(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Save {path} error: {e}")

LAST_TELEGRAM = load_json_file(LAST_TG_FILE, {})
TRADE_HISTORY = load_json_file(TRADE_HISTORY_FILE, [])
DAILY_STATS = load_json_file(DAILY_STATS_FILE, {"date": rome_today_str(), "trades": 0, "loss_streak": 0, "daily_pnl_pct": 0.0, "blocked": False})

def reset_daily_if_needed():
    global DAILY_STATS
    today = rome_today_str()
    if DAILY_STATS.get("date") != today:
        DAILY_STATS = {"date": today, "trades": 0, "loss_streak": 0, "daily_pnl_pct": 0.0, "blocked": False}
        save_json_file(DAILY_STATS_FILE, DAILY_STATS)

def send_telegram_signal(coin, tf, signal, conf, price, rsi, stoch, sl, tp, sl_pct, tp_pct, source, extra_info=""):
    if not TELEGRAM_ENABLED:
        return {"ok": False, "error": "Telegram non configurato"}
    if conf < TELEGRAM_MIN_CONF:
        return {"ok": False, "error": f"Conf {conf}% < {TELEGRAM_MIN_CONF}%"}
    reset_daily_if_needed()
    if DAILY_STATS.get("blocked"):
        return {"ok": False, "error": f"Daily STOP attivo - Max loss raggiunto {DAILY_STATS.get('daily_pnl_pct')}% "}
    if DAILY_STATS.get("trades", 0) >= 5:
        return {"ok": False, "error": "Max 5 trade/giorno raggiunto"}
    if DAILY_STATS.get("loss_streak", 0) >= 2:
        return {"ok": False, "error": "Stop dopo 2 loss di fila"}

    key = f"{coin}_{tf}"
    now = time.time()
    last = LAST_TELEGRAM.get(key, 0)
    if now - last < TELEGRAM_COOLDOWN:
        return {"ok": False, "error": f"Cooldown {int((TELEGRAM_COOLDOWN - (now-last))/60)}m"}

    # Calcolo position size reale
    risk_amount = CAPITAL * RISK_PCT / 100.0
    risk_per_coin = abs(price - sl)
    qty = risk_amount / risk_per_coin if risk_per_coin > 0 else 0
    position_value = qty * price
    rr = tp_pct / sl_pct if sl_pct>0 else 0

    emoji = "🚀" if signal=="COMPRA" else "🔻"
    tf_emoji = "⚡" if tf=="5m" else "🔍"
    
    # Link TradingView
    tv_symbol = {"BTC": "BINANCE:BTCUSDT", "ETH": "BINANCE:ETHUSDT", "ORO": "BINANCE:PAXGUSDT"}.get(coin, "BINANCE:BTCUSDT")
    chart_link = f"https://www.tradingview.com/chart/?symbol={tv_symbol}"

    text = f"""{emoji} *{signal} {coin} {conf}%* {tf_emoji} {tf} SCALP - V58 PRO

💰 Entry: ${price:.2f} ({source})
🎯 SL: ${sl:.2f} (-{sl_pct:.2f}%) | TP: ${tp:.2f} (+{tp_pct:.2f}%)
📊 RSI: {rsi} | Stoch: {stoch} | R:R 1:{rr:.1f}
💼 Risk: {RISK_PCT}% = ${risk_amount:.2f} su ${CAPITAL:.0f}$ | Qty: {qty:.4f} | Pos: ${position_value:.0f}

{extra_info}
📈 Chart: {chart_link}
⏰ {rome_now().strftime('%H:%M:%S %d/%m')} Rome

⚠️ Paper trading - verifica sempre"""

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code==200:
            LAST_TELEGRAM[key]=now
            save_json_file(LAST_TG_FILE, LAST_TELEGRAM)
            # salva storico
            TRADE_HISTORY.append({
                "time": rome_now().isoformat(),
                "coin": coin,
                "tf": tf,
                "signal": signal,
                "conf": conf,
                "price": price,
                "sl": sl,
                "tp": tp,
                "sl_pct": sl_pct,
                "tp_pct": tp_pct,
                "rsi": rsi,
                "qty": qty,
                "risk": risk_amount
            })
            if len(TRADE_HISTORY) > 200:
                TRADE_HISTORY[:] = TRADE_HISTORY[-200:]
            save_json_file(TRADE_HISTORY_FILE, TRADE_HISTORY)
            # aggiorna daily
            DAILY_STATS["trades"] = DAILY_STATS.get("trades",0)+1
            save_json_file(DAILY_STATS_FILE, DAILY_STATS)
            print(f"[{rome_now()}] TELEGRAM PRO INVIATO {coin} {conf}% RR {rr:.1f}")
            return {"ok": True, "rr": rr, "qty": qty}
        else:
            return {"ok": False, "error": f"TG API {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def ema_calc(data, period):
    if not data: return 0
    if len(data) < period: return sum(data)/len(data)
    k=2/(period+1)
    ema=sum(data[:period])/period
    for p in data[period:]: ema=p*k+ema*(1-k)
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
    symbol=PAIRS_LIVE.get(name,"BTCUSDT")
    ohlc=fetch_binance_klines(symbol,interval,limit)
    if ohlc and len(ohlc)>=20: return ohlc, "binance"
    return [], "fail"

def analyze_coin_pro(name, tf="5m", send_telegram=False):
    # --- 5m data ---
    ohlc_5m, src_5m = fetch_ohlc_with_fallback(name, TF_MAP.get(tf,"5m"), 200)
    # --- 1H data per filtro trend ---
    ohlc_1h, src_1h = fetch_ohlc_with_fallback(name, "1h", 100)

    live_price, live_src = get_live_price_ticker(name)
    if not ohlc_5m or len(ohlc_5m)<20:
        if live_price is None: return None, None
        closes=[live_price]*20
        ohlc_5m=[{"close":live_price,"low":live_price*0.998,"high":live_price*1.002,"volume":1}]*20
    else:
        closes=[c["close"] for c in ohlc_5m]

    close_price=closes[-1]
    price = live_price if live_price is not None else close_price
    source = live_src if live_price else src_5m

    ema9=ema_calc(closes,9); ema21=ema_calc(closes,21)
    rsi=rsi_calc(closes,14); rsi_fast=rsi_calc(closes,7)
    lows=[c["low"] for c in ohlc_5m]; highs=[c["high"] for c in ohlc_5m]
    vols=[c["volume"] for c in ohlc_5m]
    vwap=sum(closes[-20:])/20
    st_trend=1 if close_price>ema21 else -1
    try:
        stoch_k=int((close_price-min(lows[-14:]))/(max(highs[-14:])-min(lows[-14:]))*100)
    except: stoch_k=50
    avg_vol=sum(vols[-20:])/20 if vols else 1
    cur_vol=vols[-1] if vols else 1
    vol_ratio=cur_vol/avg_vol if avg_vol>0 else 1

    # --- 1H trend ---
    h1_trend_text="N/A"
    h1_ok=False
    if ohlc_1h and len(ohlc_1h)>=21:
        closes_1h=[c["close"] for c in ohlc_1h]
        ema21_1h=ema_calc(closes_1h,21)
        rsi_1h=rsi_calc(closes_1h,14)
        h1_up = closes_1h[-1] > ema21_1h
        h1_trend_text = f"1H {'UP' if h1_up else 'DOWN'} RSI{int(rsi_1h)} EMA21 {ema21_1h:.0f}"
        # per COMPRA serve 1H UP o RSI 1H >40, per VENDI 1H DOWN o RSI<60
        h1_ok = True  # lo valutiamo dopo per decidere
    else:
        h1_trend_text="1H loading"

    # --- scoring ---
    points=0
    if 50<=rsi<=65: points+=25
    elif 45<=rsi<50 or 65<rsi<=70: points+=18
    elif 40<=rsi<45: points+=10
    else: points+=3

    if close_price>ema9 and ema9>ema21: points+=30
    elif close_price>ema9: points+=18
    elif close_price>ema21: points+=8

    if 30<=stoch_k<=65: points+=20
    elif 20<=stoch_k<30 or 65<stoch_k<=80: points+=10
    else: points+=3

    if vol_ratio>=0.9: points+=15
    elif vol_ratio>=0.7: points+=8
    else: points+=2

    if st_trend==1 and close_price>vwap: points+=10
    elif st_trend==1: points+=5

    conf=int(points)  # max 100
    conf=max(15,min(95,conf))

    # --- SL/TP DINAMICI REAL MONEY ---
    swing_low=min(lows[-10:])
    swing_high=max(highs[-10:])
    # SL dinamico: sotto swing low per COMPRA, sopra swing high per VENDI
    if st_trend==1:
        sl_raw=swing_low*0.998  # 0.2% sotto minimo
        sl_pct_raw=(price-sl_raw)/price*100
        sl_pct = max(0.5, min(2.0, sl_pct_raw))  # tra 0.5% e 2%
        sl=price*(1-sl_pct/100)
        tp_pct=sl_pct*1.8  # R:R 1:1.8
        tp=price*(1+tp_pct/100)
        signal="COMPRA"
    else:
        sl_raw=swing_high*1.002
        sl_pct_raw=(sl_raw-price)/price*100
        sl_pct = max(0.5, min(2.0, sl_pct_raw))
        sl=price*(1+sl_pct/100)
        tp_pct=sl_pct*1.8
        tp=price*(1-tp_pct/100)
        signal="VENDI"

    # Filtro qualità
    if conf>=70 and vol_ratio>=0.7:
        quality_color="entra"
        quality_label="ENTRA"
    elif conf>=60:
        quality_color="quasi"
        quality_label="QUASI PRONTO"
    else:
        quality_color="wait"
        quality_label="ASPETTA"
        signal="ASPETTA"
        sl=price*0.992
        tp=price*1.008
        sl_pct=0.8
        tp_pct=1.5

    # FILTRO MTF per soldi veri: se 1H è opposto, declassa a QUASI
    mtf_block=False
    if ohlc_1h and len(ohlc_1h)>=21:
        closes_1h=[c["close"] for c in ohlc_1h]
        ema21_1h=ema_calc(closes_1h,21)
        if signal=="COMPRA" and closes_1h[-1] < ema21_1h:
            # 5m long ma 1H down -> rischioso
            if conf>=75:
                quality_color="quasi"
                quality_label="QUASI - 1H CONTRO"
                mtf_block=True
            else:
                quality_color="wait"
                quality_label="BLOCCATO 1H"
                mtf_block=True
        if signal=="VENDI" and closes_1h[-1] > ema21_1h:
            if conf>=75:
                quality_color="quasi"
                quality_label="QUASI - 1H CONTRO"
                mtf_block=True
            else:
                quality_color="wait"
                quality_label="BLOCCATO 1H"
                mtf_block=True

    extra_info = f"🔍 {h1_trend_text} | Vol x{vol_ratio:.1f} {'✅' if vol_ratio>=0.9 else '⚠️'}"
    if mtf_block:
        extra_info += " | ⛔ MTF BLOCCO - aspetta allineamento"

    data={
        "price":price,"real_price":price,"close_price":close_price,"source":source,
        "signal":signal,"conf":int(conf),"quality_color":quality_color,"quality_label":quality_label,
        "quality_score":int(conf),"quality_simple":f"PRO {tf} {signal} {conf}% {h1_trend_text} Vol{vol_ratio:.1f}",
        "rsi":int(rsi),"rsi_fast":int(rsi_fast),"ema9":ema9,"ema21":ema21,"st_trend":st_trend,
        "stoch_k":stoch_k,"vwap":vwap,"support":swing_low,"resistance":swing_high,
        "vol_ratio": round(vol_ratio,2), "h1_trend": h1_trend_text,
        "sl":sl,"tp":tp,"sl_pct":sl_pct,"tp_pct":tp_pct,
        "spark":closes[-30:],
        "mtf_block": mtf_block,
        "extra": extra_info
    }

    tg_res=None
    if send_telegram and quality_color=="entra" and not mtf_block and conf>=TELEGRAM_MIN_CONF:
        tg_res=send_telegram_signal(coin, tf, signal, conf, price, rsi, stoch_k, sl, tp, sl_pct, tp_pct, source, extra_info)

    return data, tg_res

@app.route("/")
def home():
    return Response(f"Bot {VERSION} - Cap {CAPITAL}$ Risk {RISK_PCT}% - {rome_now()}", mimetype="text/plain")

@app.route("/api/signals")
def api_signals():
    tf=request.args.get("tf","5m")
    send_tg = request.args.get("telegram","0")=="1"
    reset_daily_if_needed()
    result={}; tg_results={}
    for name in PAIRS_LIVE.keys():
        data, tg_res = analyze_coin_pro(name,tf, send_telegram=send_tg)
        if data is None:
            data={"price":0,"signal":"LOADING","conf":0,"quality_color":"loading","quality_label":"LOAD","rsi":50,"sl":0,"tp":0,"sl_pct":0.8,"tp_pct":1.5,"spark":[]}
        result[name]=data
        if tg_res: tg_results[name]=tg_res
    return jsonify({"ok":True,"tf":tf,"coins":result,"telegram_results":tg_results,"telegram_enabled":TELEGRAM_ENABLED,"time":rome_now().isoformat(),"version":VERSION,"daily":DAILY_STATS,"capital":CAPITAL,"risk":RISK_PCT})

@app.route("/api/history")
def api_history():
    return jsonify({"history": TRADE_HISTORY[-50:], "daily": DAILY_STATS})

@app.route("/api/stats")
def api_stats():
    reset_daily_if_needed()
    total=len(TRADE_HISTORY)
    return jsonify({"version":VERSION,"total_signals":total,"daily":DAILY_STATS,"last_telegram":LAST_TELEGRAM,"capital":CAPITAL,"risk_pct":RISK_PCT,"threshold":TELEGRAM_MIN_CONF})

@app.route("/api/telegram_test")
def api_telegram_test():
    if not TELEGRAM_ENABLED:
        return jsonify({"ok":False,"error":"Configura ENV"}), 400
    res=send_telegram_signal("BTC","5m","COMPRA",80,67000,58,55,66500,68000,0.7,1.5,"TEST","Test V58 PRO - Multi TF ✅ Volume ✅ R:R 1:2.1")
    return jsonify(res)

@app.route("/api/force_telegram")
def api_force_telegram():
    results={}
    for name in PAIRS_LIVE.keys():
        price,_ = get_live_price_ticker(name)
        if price is None: price=67000
        res=send_telegram_signal(name,"5m","COMPRA",75,price,56,54,price*0.993,price*1.013,0.7,1.3,"FORCE","Force V58 PRO - 1% risk test",)
        results[name]=res
    return jsonify(results)

@app.route("/api/telegram_config")
def api_telegram_config():
    reset_daily_if_needed()
    return jsonify({"enabled":TELEGRAM_ENABLED,"threshold":TELEGRAM_MIN_CONF,"cooldown":TELEGRAM_COOLDOWN,"daily":DAILY_STATS,"capital":CAPITAL,"risk":RISK_PCT,"has_token":bool(TELEGRAM_BOT_TOKEN),"has_chat_id":bool(TELEGRAM_CHAT_ID),"app_protected":bool(APP_PASSWORD)})

def check_auth():
    if not APP_PASSWORD:
        return True
    pwd=request.args.get("pwd") or request.cookies.get("app_pwd")
    return pwd==APP_PASSWORD

@app.route("/app")
def app_page():
    if not check_auth():
        return Response(f"""
        <html><body style="background:#020617;color:white;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh">
        <form><h2>🔒 V58 PRO Protetta</h2><p>Inserisci password impostata su Render APP_PASSWORD</p>
        <input type="password" name="pwd" style="padding:10px;border-radius:8px;border:none;width:250px">
        <button style="padding:10px 15px;border-radius:8px;background:#22c55e;border:none;font-weight:bold;margin-left:8px">Entra</button>
        </form></body></html>
        """, mimetype="text/html")
    html = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VENDI V58 PRO REAL MONEY</title>
<style>
*{box-sizing:border-box;font-family:Inter,system-ui,sans-serif}
body{margin:0;background:#020617;color:#f1f5f9}
.header{background:linear-gradient(135deg,#020617,#1e293b);padding:12px 16px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:10;border-bottom:1px solid #1e293b}
.logo{width:48px;height:48px;border-radius:12px;background:linear-gradient(135deg,#22c55e,#16a34a);display:flex;align-items:center;justify-content:center;font-weight:900;color:#052e16}
.badge{padding:4px 10px;border-radius:20px;font-size:11px;font-weight:800}
.badge-entra{background:#22c55e;color:#052e16;animation:glow 1s infinite alternate}
.badge-quasi{background:#facc15;color:#422006}.badge-wait{background:#1e293b;color:#94a3b8}
@keyframes glow{0%{box-shadow:0 0 5px #22c55e}100%{box-shadow:0 0 15px #22c55e}}
.tfs{display:flex;gap:6px;padding:10px 12px;overflow-x:auto;background:#0f172a}
.tfs button{border:1px solid #1e293b;background:#1e293b;color:#cbd5e1;padding:8px 14px;border-radius:20px;font-weight:700;cursor:pointer;font-size:13px}
.tfs button.active{background:#22c55e;color:#052e16}
.coin-row{display:flex;justify-content:space-between;align-items:center;padding:14px;border-bottom:1px solid #1e293b;background:#0f172a;cursor:pointer}
.coin-icon{width:38px;height:38px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:900;color:white}
.coin-icon.btc{background:#f7931a}.coin-icon.eth{background:#8b5cf6}.coin-icon.oro{background:#ca8a04}
.stats-bar{display:flex;gap:8px;margin:8px 12px}
.stat-mini{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:8px 10px;flex:1;text-align:center}
.stat-mini b{display:block;font-size:13px}.stat-mini span{font-size:9px;color:#94a3b8}
.tele-banner{margin:8px 12px;padding:10px 12px;border-radius:10px;font-size:12px}
.tele-on{background:#052e16;border:1px solid #16a34a;color:#86efac}.tele-off{background:#450a0a;border:1px solid #dc2626;color:#fca5a5}
.modal{position:fixed;inset:0;background:rgba(0,0,0,0.7);display:none;align-items:flex-end;justify-content:center;z-index:50}
.modal.show{display:flex}
.modal-box{background:#0f172a;width:100%;max-width:500px;border-radius:20px 20px 0 0;padding:20px;max-height:92vh;overflow:auto;border:1px solid #1e293b}
.big-box{border-radius:14px;padding:16px;margin:12px 0;text-align:center}
.entra-big{background:#052e16;border:2px solid #22c55e}.quasi-big{background:#422006;border:2px solid #facc15}.wait-big{background:#1e293b;border:1px solid #334155}
</style>
</head>
<body>
<div class="header">
<div class="logo">V58</div>
<div style="flex:1"><div style="font-weight:800">VENDI V58 PRO <span style="background:#22c55e;color:#052e16;padding:2px 6px;border-radius:6px;font-size:10px">REAL MONEY</span></div>
<div style="font-size:10px;opacity:0.7">MTF 5m+1H • SL dinamico • Risk 1% • Max 5 trade/giorno</div></div>
<div><button onclick="testTelegram()" style="background:#0088cc;color:white;border:none;padding:6px 10px;border-radius:20px;font-size:11px;font-weight:700">📱 Test</button></div>
</div>
<div id="statsBar" class="stats-bar"><div class="stat-mini"><span>OGGI</span><b id="sTrades">-</b></div><div class="stat-mini"><span>LOSS STREAK</span><b id="sLoss">-</b></div><div class="stat-mini"><span>CAPITALE</span><b id="sCap">-</b></div><div class="stat-mini"><span>RISCHIO</span><b id="sRisk">-</b></div></div>
<div id="teleBanner" class="tele-banner tele-off">Verifico...</div>
<div class="tfs"><button id="b5m" class="active" onclick="loadTF('5m')">⚡ 5m PRO</button><button id="b15m" onclick="loadTF('15m')">15m</button><button id="b1H" onclick="loadTF('1H')">1H</button><button onclick="loadTF('5m', true)" style="background:#0088cc;color:white">📱 Con TG</button><button onclick="loadHistory()" style="background:#1e293b">📜 Storico</button></div>
<div id="coins" style="background:#0f172a;border-radius:12px;margin:0 8px;overflow:hidden;border:1px solid #1e293b;min-height:100px"><div style="padding:20px;text-align:center;color:#94a3b8">Carico V58 PRO...</div></div>
<div id="modal" class="modal" onclick="if(event.target==this)closeModal()"><div class="modal-box"><div style="display:flex;justify-content:space-between"><b id="mCoin" style="font-size:18px">BTC</b><button onclick="closeModal()" style="background:#1e293b;color:white;border:none;padding:8px 12px;border-radius:10px">X</button></div><div id="mPrice" style="font-size:11px;color:#94a3b8;margin:8px 0"></div><div id="mQualityBig" class="big-box"></div><div id="mExtra" style="font-size:11px;background:#1e293b;padding:10px;border-radius:10px;border:1px solid #334155;margin:8px 0"></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:10px 0"><div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">STOP LOSS DINAMICO</span><br><b id="mSL">-</b><br><span id="mSLpct" style="font-size:9px;color:#94a3b8"></span></div><div style="background:#052e16;border:1px solid #16a34a;border-radius:10px;padding:10px;text-align:center"><span style="font-size:9px;color:#86efac">TAKE PROFIT 1:1.8</span><br><b id="mTP">-</b><br><span id="mTPpct" style="font-size:9px;color:#94a3b8"></span></div></div><div id="mPos" style="background:#1e293b;padding:10px;border-radius:10px;font-size:11px;border:1px solid #334155"></div><button onclick="sendThisToTelegram()" style="width:100%;background:#0088cc;color:white;border:none;padding:12px;border-radius:10px;font-weight:800;margin-top:8px">📱 MANDA SU TELEGRAM ORA</button></div></div>
<script>
var curTF='5m'; var lastData=null;
function qualityBadge(info){var c=info.quality_color||'wait';var l=info.quality_label||'ASPETTA';if(c=='entra')return '<span class="badge badge-entra">'+l+'</span>';if(c=='quasi')return '<span class="badge badge-quasi">'+l+'</span>';return '<span class="badge badge-wait">'+l+'</span>';}
async function checkTelegram(){try{var r=await fetch('/api/telegram_config');var j=await r.json();var banner=document.getElementById('teleBanner');document.getElementById('sTrades').textContent=j.daily.trades+'/5';document.getElementById('sLoss').textContent=j.daily.loss_streak+'/2';document.getElementById('sCap').textContent='$'+j.capital;document.getElementById('sRisk').textContent=j.risk+'%';if(j.enabled){banner.className='tele-banner tele-on';banner.innerHTML=`✅ Telegram ON - Soglia ${j.threshold}% - ${j.daily.blocked?'⛔ BLOCCATO oggi': 'Attivo'} - Cap $${j.capital} Risk ${j.risk}%`;}else{banner.className='tele-banner tele-off';banner.innerHTML='❌ Telegram OFF';}}catch(e){}}
async function loadTF(tf,withTelegram=false){curTF=tf;document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active'));var el=document.getElementById('b'+tf);if(el)el.classList.add('active');document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center;color:#94a3b8">⚡ Carico '+tf+(withTelegram?' + TG...':'...')+'</div>';try{var url='/api/signals?tf='+tf+(withTelegram?'&telegram=1':'');var res=await fetch(url);var d=await res.json();lastData=d;checkTelegram();var html='';for(var name in d.coins){var info=d.coins[name];var iconClass=name=='BTC'?'btc':name=='ETH'?'eth':'oro';var ico=name=='BTC'?'B':name=='ETH'?'E':'Au';var qBadge=qualityBadge(info);var price='$'+info.price.toFixed(2);var actionText=info.quality_color=='entra'?(info.signal=='COMPRA'?'🚀 COMPRA ORA':'🔻 VENDI ORA'):'⏸️ Aspetta';html+=`<div class="coin-row" onclick="openDetails('${name}')"><div style="display:flex;gap:10px;align-items:center"><div class="coin-icon ${iconClass}">${ico}</div><div><b>${name}</b> - ${price}<div style="font-size:11px;color:#94a3b8">${info.h1_trend||''} • Vol x${info.vol_ratio||1} • ${actionText}</div><div style="font-size:10px;color:#64748b">${info.extra||''}</div></div></div><div style="text-align:right">${qBadge}<div style="font-size:11px;color:#64748b;margin-top:4px">${info.signal} ${info.conf}%<br>SL ${info.sl_pct.toFixed(2)}% TP ${info.tp_pct.toFixed(2)}%</div></div></div>`;}if(d.telegram_results&&Object.keys(d.telegram_results).length>0){html+=`<div style="background:#052e16;padding:10px 14px;font-size:11px;color:#86efac">📱 Inviati: ${Object.keys(d.telegram_results).join(', ')}</div>`;}document.getElementById('coins').innerHTML=html;}catch(e){document.getElementById('coins').innerHTML='<div style="padding:20px;color:#ef4444">Errore: '+e.message+'</div>';}}
async function openDetails(coin){if(!lastData)return;var info=lastData.coins[coin];document.getElementById('mCoin').textContent=coin+' - $'+info.price.toFixed(2);document.getElementById('mPrice').textContent=info.source+' - '+info.signal+' '+info.conf+'% - TF '+curTF;var big=document.getElementById('mQualityBig');big.className='big-box '+(info.quality_color=='entra'?'entra-big':info.quality_color=='quasi'?'quasi-big':'wait-big');big.innerHTML=`<div style="font-size:20px;font-weight:900">${info.quality_label} - ${info.signal} ${info.conf}%</div><div style="font-size:12px;margin-top:6px">${info.h1_trend||''}</div>`;document.getElementById('mSL').textContent='$'+Math.round(info.sl);document.getElementById('mSLpct').textContent='-'+info.sl_pct.toFixed(2)+'%';document.getElementById('mTP').textContent='$'+Math.round(info.tp);document.getElementById('mTPpct').textContent='+'+info.tp_pct.toFixed(2)+'% R:R 1:'+(info.tp_pct/info.sl_pct).toFixed(1);document.getElementById('mExtra').textContent=info.extra||'';var riskAmt=lastData.capital*lastData.risk/100;var qty=riskAmt/(Math.abs(info.price-info.sl)||1);document.getElementById('mPos').innerHTML=`💼 Capitale $${lastData.capital} Risk ${lastData.risk}% = $${riskAmt.toFixed(2)}<br>Qty: ${qty.toFixed(4)} ${coin} | Posizione: $${(qty*info.price).toFixed(0)}<br>R:R 1:${(info.tp_pct/info.sl_pct).toFixed(2)} | Daily ${lastData.daily.trades}/5 trades`;document.getElementById('modal').classList.add('show');window._currentCoin=coin;}
function closeModal(){document.getElementById('modal').classList.remove('show');}
async function testTelegram(){try{var r=await fetch('/api/telegram_test');var j=await r.json();alert(j.ok?'✅ Test inviato!':'❌ '+j.error);}catch(e){alert(e.message);}}
async function sendThisToTelegram(){if(!window._currentCoin)return;try{var r=await fetch(`/api/signals?tf=${curTF}&telegram=1`);var j=await r.json();alert('Risultato: '+JSON.stringify(j.telegram_results[window._currentCoin]||'Nessun ENTRA - MTF o volume bloccato'));}catch(e){alert(e.message);}}
async function loadHistory(){try{var r=await fetch('/api/history');var j=await r.json();var html='<div style="padding:12px"><h3>📜 Ultimi segnali</h3>';j.history.reverse().forEach(h=>{html+=`<div style="background:#1e293b;padding:8px;border-radius:8px;margin:6px 0;font-size:11px;border:1px solid #334155">${h.time.slice(11,19)} ${h.coin} ${h.signal} ${h.conf}% Entry $${h.price.toFixed(0)} SL ${h.sl_pct.toFixed(2)}% TP ${h.tp_pct.toFixed(2)}%</div>`});html+='</div>';document.getElementById('coins').innerHTML=html;}catch(e){alert(e.message);}}
checkTelegram();loadTF('5m');setInterval(()=>loadTF(curTF),15000);
</script>
</body></html>
"""
    resp=make_response(html)
    if APP_PASSWORD and request.args.get("pwd"):
        resp.set_cookie("app_pwd", request.args.get("pwd"), max_age=86400*30)
    return resp

def background_loop():
    print(f"V58 PRO loop started - Cap {CAPITAL} Risk {RISK_PCT}%")
    while True:
        try:
            reset_daily_if_needed()
            if not DAILY_STATS.get("blocked") and DAILY_STATS.get("trades",0)<5 and DAILY_STATS.get("loss_streak",0)<2:
                for name in PAIRS_LIVE.keys():
                    analyze_coin_pro(name, "5m", send_telegram=True)
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(60)

threading.Thread(target=background_loop, daemon=True).start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
