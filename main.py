from flask import Flask, jsonify, Response, request
import os, requests, time, math, json
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
    def rome_now():
        return datetime.now(ZoneInfo("Europe/Rome"))
except:
    def rome_now():
        return datetime.now(timezone.utc) + timedelta(hours=2)
app = Flask(__name__)
OHLC_CACHE = {}; CACHE_TTL = 45
PAIRS_KRAKEN = {"BTC": "XBTUSD","ETH": "ETHUSD","ORO": "PAXGUSD"}
PAIRS_BINANCE = {"BTC": "BTCUSDT","ETH": "ETHUSDT","ORO": "PAXGUSDT"}
TF_MAP = {"5m": 5,"15m": 15,"1H": 60,"4H": 240,"1D": 1440}
SUBS_FILE = "/tmp/subs.json"; LAST_SIGNALS_FILE = "/tmp/last_signals.json"
VAPID_PUBLIC = "BCOxkGJ3MRDgLq_3IquF1JxqyP1YbeC66cljBJvfHHB5419NkCyI81KaUuFhOfLstMQZDwErgSQR78d0A7OUoUk"
VAPID_PRIVATE = "62w7j7S479UURp1ykUN3D87uLvI0z7OzXj5eXqwOAqM"
VAPID_SUBJECT = "mailto:tuo@binance-bot-ftx6.onrender.com"
def load_subs():
    try:
        if os.path.exists(SUBS_FILE):
            with open(SUBS_FILE,"r") as f: return json.load(f)
    except: pass
    return []
def save_subs(subs):
    try:
        with open(SUBS_FILE,"w") as f: json.dump(subs,f)
    except: pass
def load_last():
    try:
        if os.path.exists(LAST_SIGNALS_FILE):
            with open(LAST_SIGNALS_FILE,"r") as f: return json.load(f)
    except: pass
    return {}
def save_last(d):
    try:
        with open(LAST_SIGNALS_FILE,"w") as f: json.dump(d,f)
    except: pass

def ema_calc(data, period):
    if len(data) < period: period = len(data) or 1
    k = 2 / (period + 1); ema = data[0]
    for price in data[1:]: ema = price * k + ema * (1 - k)
    return ema
def rsi_calc(closes, period=14):
    if len(closes) < period+1: return 50.0
    gains=0; losses=0
    for i in range(1, period+1):
        diff = closes[-i] - closes[-i-1]
        if diff>0: gains+=diff
        else: losses+=abs(diff)
    if losses==0: return 70.0
    rs = (gains/period) / (losses/period)
    return 100 - (100/(1+rs))
def atr_calc(highs, lows, closes, period=14):
    if len(closes) < period+1: return closes[-1]*0.02
    trs=[]
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])); trs.append(tr)
    return sum(trs[-period:])/period if trs else closes[-1]*0.02

def supertrend_calc(highs, lows, closes, period=10, multiplier=3.0):
    if len(closes) < period+5:
        return closes[-1]*0.99, 1
    trs=[]
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])); trs.append(tr)
    atrs=[]
    for i in range(len(trs)):
        if i < period-1:
            atrs.append(sum(trs[:i+1])/(i+1))
        else:
            atrs.append(sum(trs[i-period+1:i+1])/period)
    # prepend 0 for first candle
    atrs = [atrs[0]] + atrs
    upper = []; lower=[]
    for i in range(len(closes)):
        hl2 = (highs[i]+lows[i])/2
        atr = atrs[i] if i < len(atrs) else atrs[-1]
        upper.append(hl2 + multiplier*atr)
        lower.append(hl2 - multiplier*atr)
    trend = 1
    st = lower[0]
    for i in range(1, len(closes)):
        if closes[i] > upper[i-1]:
            trend = 1
        elif closes[i] < lower[i-1]:
            trend = -1
        if trend == 1:
            st = lower[i]
        else:
            st = upper[i]
    return st, trend

def stoch_calc(highs, lows, closes, period=14, smooth=3):
    if len(closes) < period:
        return 50.0, 50.0
    k_vals=[]
    for i in range(len(closes)):
        if i < period-1:
            k_vals.append(50.0)
        else:
            highest = max(highs[i-period+1:i+1])
            lowest = min(lows[i-period+1:i+1])
            if highest == lowest:
                k_vals.append(50.0)
            else:
                k_vals.append((closes[i]-lowest)/(highest-lowest)*100)
    d_vals=[]
    for i in range(len(k_vals)):
        if i < smooth-1:
            d_vals.append(50.0)
        else:
            d_vals.append(sum(k_vals[i-smooth+1:i+1])/smooth)
    return k_vals[-1], d_vals[-1]

def vwap_calc(highs, lows, closes, volumes, period=20):
    period = min(period, len(closes))
    if period < 2:
        return closes[-1]
    tp = [(h+l+c)/3 for h,l,c in zip(highs[-period:], lows[-period:], closes[-period:])]
    vol = volumes[-period:]
    s = sum(vol)
    if s == 0:
        return closes[-1]
    return sum(t*v for t,v in zip(tp, vol))/s

def sr_calc(highs, lows, closes, lookback=20):
    if len(closes) < lookback+2:
        return min(lows), max(highs)
    recent_lows = lows[-lookback-1:-1]
    recent_highs = highs[-lookback-1:-1]
    support = min(recent_lows) if recent_lows else min(lows)
    resistance = max(recent_highs) if recent_highs else max(highs)
    return support, resistance

def macd_calc(closes):
    ema12 = ema_calc(closes[-100:], 12) if len(closes)>=12 else ema_calc(closes, 12)
    ema26 = ema_calc(closes[-100:], 26) if len(closes)>=26 else ema_calc(closes, 26)
    macd = ema12 - ema26
    macds=[]
    for i in range(9, len(closes)):
        e12 = ema_calc(closes[:i], 12); e26 = ema_calc(closes[:i], 26); macds.append(e12-e26)
    signal = ema_calc(macds[-20:], 9) if len(macds)>=9 else macd*0.9
    return macd, signal
def bollinger_calc(closes, period=20):
    if len(closes) < period: period = len(closes)
    sma = sum(closes[-period:])/period
    variance = sum((x-sma)**2 for x in closes[-period:])/period
    std = math.sqrt(variance)
    return sma+2*std, sma-2*std, sma
def adx_calc(highs, lows, closes, period=14):
    if len(closes) < period*2: return 20 + (closes[-1] % 10)
    plus_dm=[]; minus_dm=[]; tr_list=[]
    for i in range(1, len(closes)):
        up_move = highs[i]-highs[i-1]; down_move = lows[i-1]-lows[i]
        plus = up_move if up_move>down_move and up_move>0 else 0
        minus = down_move if down_move>up_move and down_move>0 else 0
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        plus_dm.append(plus); minus_dm.append(minus); tr_list.append(tr)
    atr = sum(tr_list[-period:])/period if tr_list else 1
    plus_di = (sum(plus_dm[-period:])/atr*100) if atr else 0
    minus_di = (sum(minus_dm[-period:])/atr*100) if atr else 0
    dx = abs(plus_di-minus_di)/(plus_di+minus_di+1)*100
    return min(60, max(10, dx + 10))
def get_ohlc(coin, tf):
    key = f"{coin}_{tf}"; now = time.time()
    if key in OHLC_CACHE and now - OHLC_CACHE[key][0] < CACHE_TTL: return OHLC_CACHE[key][1]
    try:
        pair = PAIRS_KRAKEN[coin]; interval = TF_MAP.get(tf, 240)
        url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval}"
        r = requests.get(url, timeout=3); j = r.json()
        result = j.get("result", {}); ohlc = None
        for k,v in result.items():
            if k != "last" and isinstance(v, list): ohlc = v; break
        if not ohlc or len(ohlc) < 30: return None
        OHLC_CACHE[key] = (now, ohlc); return ohlc
    except: return None

def compute_from_ohlc(ohlc, live_price=None, sens=55):
    closes = [float(x[4]) for x in ohlc]; highs = [float(x[2]) for x in ohlc]; lows = [float(x[3]) for x in ohlc]; volumes = [float(x[6]) for x in ohlc]
    close_price = live_price if live_price else closes[-1]; closes[-1] = close_price
    rsi = rsi_calc(closes); ema50 = ema_calc(closes, 50); ema200 = ema_calc(closes, 200)
    bb_up, bb_low, bb_mid = bollinger_calc(closes); macd, macd_sig = macd_calc(closes)
    adx = adx_calc(highs, lows, closes); atr = atr_calc(highs, lows, closes)
    # NEW INDICATORS V9
    st_val, st_trend = supertrend_calc(highs, lows, closes, 10, 3.0)
    stoch_k, stoch_d = stoch_calc(highs, lows, closes, 14, 3)
    vwap = vwap_calc(highs, lows, closes, volumes, 20)
    support, resistance = sr_calc(highs, lows, closes, 20)
    vol_avg = sum(volumes[-20:])/20 if len(volumes)>=20 else volumes[-1] if volumes else 1
    vol_ratio = volumes[-1]/vol_avg if vol_avg else 1.0
    bullish = 50; bearish = 50; reasons = []
    # RSI
    if rsi < 30: bullish+=20; reasons.append(f"RSI ipervenduto {rsi:.0f}")
    elif rsi > 70: bearish+=20; reasons.append(f"RSI ipercomprato {rsi:.0f}")
    elif rsi > 55: bullish+=8; reasons.append(f"RSI {rsi:.0f} rialzista")
    elif rsi < 45: bearish+=8; reasons.append(f"RSI {rsi:.0f} ribassista")
    else: reasons.append(f"RSI neutro {rsi:.0f}")
    # EMA
    if ema50 > ema200: bullish+=10; reasons.append("EMA 50>200 rialzista")
    else: bearish+=10; reasons.append("EMA 50<200 ribassista")
    if close_price > ema50: bullish+=6
    else: bearish+=6
    # MACD
    if macd > macd_sig: bullish+=8; reasons.append("MACD ↑")
    else: bearish+=8; reasons.append("MACD ↓")
    # BB
    if close_price > bb_up: bearish+=8; reasons.append("Sopra BB upper")
    elif close_price < bb_low: bullish+=8; reasons.append("Sotto BB lower")
    # NEW: Supertrend
    if st_trend == 1 and close_price > st_val:
        bullish+=12; reasons.append(f"Supertrend 🟢")
    elif st_trend == -1 and close_price < st_val:
        bearish+=12; reasons.append(f"Supertrend 🔴")
    else:
        reasons.append("Supertrend laterale")
    # NEW: Stochastic
    if stoch_k < 20 and stoch_k > stoch_d:
        bullish+=10; reasons.append(f"Stoch ipervenduto {stoch_k:.0f}")
    elif stoch_k > 80 and stoch_k < stoch_d:
        bearish+=10; reasons.append(f"Stoch ipercomprato {stoch_k:.0f}")
    elif stoch_k > stoch_d:
        bullish+=5; reasons.append(f"Stoch ↑ {stoch_k:.0f}")
    else:
        bearish+=5; reasons.append(f"Stoch ↓ {stoch_k:.0f}")
    # NEW: VWAP
    if close_price > vwap:
        bullish+=6; reasons.append(f"Sopra VWAP")
    else:
        bearish+=6; reasons.append(f"Sotto VWAP")
    # NEW: Support/Resistance
    dist_sup = (close_price - support)/close_price*100 if close_price else 0
    dist_res = (resistance - close_price)/close_price*100 if close_price else 0
    if dist_sup < 1.0:
        bullish+=6; reasons.append(f"Vicino supporto")
    if dist_res < 1.0:
        bearish+=6; reasons.append(f"Vicino resistenza {dist_res:.1f}%")
    # Vol
    if vol_ratio > 1.2:
        if bullish>bearish: bullish+=4
        else: bearish+=4
        reasons.append(f"Vol x{vol_ratio:.1f}")

    total = bullish+bearish; bull_pct = bullish/total*100
    buy_thr = sens; sell_thr = 100 - sens
    if bull_pct >= buy_thr: signal = "COMPRA"; conf = int(bull_pct)
    elif bull_pct <= sell_thr: signal = "VENDI"; conf = int(100-bull_pct)
    else: signal = "FERMO"; conf = int(50 + abs(bull_pct-50)*0.8); conf = max(conf,50)
    trend = "Rialzista" if bullish>bearish else "Ribassista" if bearish>bullish else "Laterale"
    if signal == "COMPRA": sl = close_price - atr*1.5; tp = close_price + atr*2.5
    elif signal == "VENDI": sl = close_price + atr*1.5; tp = close_price - atr*2.5
    else: sl = close_price - atr; tp = close_price + atr
    return {"price": close_price,"rsi": round(rsi,1),"signal": signal,"conf": conf,"trend": trend,"ema50": ema50,"ema200": ema200,"bb_up": bb_up,"bb_low": bb_low,"macd": macd,"macd_signal": macd_sig,"vol_ratio": round(vol_ratio,2),"adx": round(adx,0),"atr": round(atr,2),"sl": sl,"tp": tp,"reasons": reasons[:6],"bullish": int(bull_pct),"bearish": int(100-bull_pct),
            "st_val": st_val, "st_trend": st_trend, "stoch_k": round(stoch_k,1), "stoch_d": round(stoch_d,1), "vwap": vwap, "support": support, "resistance": resistance, "dist_sup": round(dist_sup,2), "dist_res": round(dist_res,2)}

def binance_fast_price():
    try:
        out={}
        for coin, sym in PAIRS_BINANCE.items():
            r=requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}", timeout=2)
            j=r.json(); p=float(j["price"]); out[coin]=p
        return out
    except: return {}
def kraken_fast_price_fallback():
    try:
        r=requests.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSD,ETHUSD,PAXGUSD", timeout=2); j=r.json(); out={}
        for k,v in j.get("result",{}).items():
            p=float(v["c"][0])
            if "XBT" in k: out["BTC"]=p
            elif "ETH" in k: out["ETH"]=p
            elif "PAXG" in k: out["ORO"]=p
        return out
    except: return {}
def send_push_to_all(title, body, url="/app?v=9"):
    subs = load_subs()
    if not subs: return {"sent":0}
    try:
        from pywebpush import webpush
        sent=0
        for sub in subs:
            try:
                webpush(subscription_info=sub, data=json.dumps({"title": title, "body": body, "url": url}), vapid_private_key=VAPID_PRIVATE, vapid_claims={"sub": VAPID_SUBJECT})
                sent+=1
            except: pass
        return {"sent":sent, "total": len(subs)}
    except: return {"sent":0}

@app.route("/api/ping")
def ping(): return jsonify({"ok":True,"msg":"V9 SUPERTREND STOCH VWAP SR","time":rome_now().isoformat(),"subs": len(load_subs())})
@app.route("/api/signals")
def signals():
    tf = request.args.get("tf","1H"); sens = int(request.args.get("sens","55"))
    live_prices = binance_fast_price()
    if not live_prices: live_prices = kraken_fast_price_fallback()
    source_name = "Binance" if live_prices else "Kraken"
    coins_data = {}
    for coin in ["BTC","ETH","ORO"]:
        ohlc = get_ohlc(coin, tf); live = live_prices.get(coin)
        if ohlc:
            computed = compute_from_ohlc(ohlc, live_price=live, sens=sens)
            coins_data[coin] = computed
            coins_data[coin]["symbol"]=f"{coin}USD"
            coins_data[coin]["tf"]=tf
        else:
            price = live if live else (1881 if coin=="ETH" else 63090)
            coins_data[coin] = {"symbol": f"{coin}USD","price": price,"rsi": 50.0,"signal": "FERMO","conf": 50,"trend": "Caricamento","tf": tf,"ema50": price*0.99,"ema200": price*0.98,"bb_up": price*1.02,"bb_low": price*0.98,"macd": 0,"macd_signal": 0,"vol_ratio": 1.0,"adx": 20,"atr": price*0.02,"sl": price*0.99,"tp": price*1.01,"reasons": ["OHLC in caricamento..."],"bullish": 50,"bearish": 50,"st_val": price*0.99,"st_trend":1,"stoch_k":50,"stoch_d":50,"vwap":price,"support":price*0.98,"resistance":price*1.02,"dist_sup":2,"dist_res":2}
    max_conf=0; globale="FERMO"
    for v in coins_data.values():
        if v["signal"] in ("COMPRA","VENDI") and v["conf"]>max_conf: max_conf=v["conf"]; globale=v["signal"]
    if max_conf==0:
        for v in coins_data.values():
            if v["conf"]>max_conf: max_conf=v["conf"]; globale=v["signal"]
    btc_price = coins_data["BTC"]["price"]
    return jsonify({"coins": coins_data,"globale": globale,"tf": tf,"updated": rome_now().strftime("%H:%M:%S"),"source": f"{source_name} V9 TF {tf} BTC ${btc_price:.2f} • Roma {rome_now().strftime('%H:%M')}"})
@app.route("/api/backtest")
def backtest():
    coin = request.args.get("coin","ETH"); tf = request.args.get("tf","1H"); sens = int(request.args.get("sens","55"))
    ohlc = get_ohlc(coin, tf)
    if not ohlc or len(ohlc) < 80: return jsonify({"ok":True, "total_signals":0, "wins":0, "win_rate":0, "last20_win":0, "last20":[]})
    results=[]; wins=0; total=0
    for i in range(60, len(ohlc)-3):
        slice_ohlc = ohlc[:i+1]
        comp = compute_from_ohlc(slice_ohlc, sens=sens)
        if comp["signal"] not in ("COMPRA","VENDI"): continue
        if comp["conf"] < 50: continue
        entry = float(ohlc[i][4])
        future_close = float(ohlc[i+3][4]) if i+3 < len(ohlc) else float(ohlc[i+1][4])
        win = (future_close > entry) if comp["signal"]=="COMPRA" else (future_close < entry)
        total+=1
        if win: wins+=1
        results.append({"entry": entry, "future": future_close, "signal": comp["signal"], "win": win, "conf": comp["conf"]})
    last20 = results[-20:] if len(results)>=20 else results
    win_rate = (wins/total*100) if total else 0
    last20_win = (sum(1 for r in last20 if r["win"])/len(last20)*100) if last20 else 0
    return jsonify({"ok":True, "coin":coin, "tf":tf, "sens":sens, "total_signals": total, "wins": wins, "win_rate": round(win_rate,1), "last20_win": round(last20_win,1), "last20": last20[::-1][:12]})
@app.route("/api/chart")
def chart_data():
    coin = request.args.get("coin","ETH"); tf = request.args.get("tf","1H")
    ohlc = get_ohlc(coin, tf)
    if not ohlc: return jsonify({"ok":False})
    data=[]
    for c in ohlc[-120:]:
        data.append({"time": int(c[0]), "open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4])})
    live = binance_fast_price()
    if live.get(coin) and data:
        data[-1]["close"] = live[coin]
    return jsonify({"ok":True, "data": data})
@app.route("/api/history")
def history():
    sens = int(request.args.get("sens","55")); live = binance_fast_price()
    if not live: live = kraken_fast_price_fallback()
    all_signals = []
    for tf in ["5m","15m","1H","4H","1D"]:
        for coin in ["BTC","ETH","ORO"]:
            ohlc = get_ohlc(coin, tf)
            if not ohlc: continue
            comp = compute_from_ohlc(ohlc, live.get(coin), sens=sens)
            if comp["signal"] in ("COMPRA","VENDI") and comp["conf"] >= sens:
                all_signals.append({"coin": coin,"tf": tf,"signal": comp["signal"],"conf": comp["conf"],"rsi": comp["rsi"],"price": comp["price"],"time": f"{tf} • {rome_now().strftime('%H:%M')}","adx": comp["adx"],"reasons": comp["reasons"]})
    all_signals.sort(key=lambda x: x["conf"], reverse=True)
    return jsonify(all_signals[:20])
@app.route("/api/push/subscribe", methods=["POST"])
def sub():
    try:
        data = request.get_json(force=True); subs = load_subs()
        ep = data.get("endpoint",""); subs = [s for s in subs if s.get("endpoint")!=ep]
        subs.append(data); save_subs(subs)
        return jsonify({"ok":True,"total":len(subs)})
    except Exception as e:
        return jsonify({"ok":False,"error": str(e)}), 500
@app.route("/api/push/clear", methods=["POST"])
def clear_subs():
    save_subs([]); return jsonify({"ok":True,"total":0})
@app.route("/api/push/test", methods=["POST"])
def testp():
    subs = load_subs()
    result = send_push_to_all(f"🔔 Test V9", f"PUSH OK {len(subs)} con nuovi indicatori")
    return jsonify({"ok": True, "result": result, "subs": len(subs)})
@app.route("/api/cron/check", methods=["GET","POST"])
def cron_check():
    sens = int(request.args.get("sens","55")); live = binance_fast_price()
    if not live: live = kraken_fast_price_fallback()
    last = load_last(); new_signals = []
    for tf in ["5m","15m","1H"]:
        for coin in ["BTC","ETH","ORO"]:
            ohlc = get_ohlc(coin, tf)
            if not ohlc: continue
            comp = compute_from_ohlc(ohlc, live.get(coin), sens=sens)
            if comp["signal"] in ("COMPRA","VENDI") and comp["conf"] >= sens:
                key = f"{coin}_{tf}_{comp['signal']}"
                if last.get(key) != comp["conf"]:
                    new_signals.append({"coin": coin,"tf": tf,"signal": comp["signal"],"conf": comp["conf"],"price": comp["price"]})
                    last[key]=comp["conf"]
    save_last(last); sent_total=0
    for sig in new_signals:
        r = send_push_to_all(f"{'🟢' if sig['signal']=='COMPRA' else '🔴'} {sig['coin']} {sig['signal']} {sig['conf']}%", f"${sig['price']:.2f}", url=f"/app?v=9&tf={sig['tf']}")
        sent_total+=r.get("sent",0)
    return jsonify({"ok": True, "new_signals": new_signals, "sent": sent_total, "subs": len(load_subs())})
@app.route("/sw.js")
def sw():
    return Response("self.addEventListener('push',function(e){let d={};try{d=e.data.json()}catch{d={title:'Vendi PRO',body:e.data.text()}}const t=d.title||'Vendi PRO V9';const o={body:d.body||'Segnale!',icon:'https://cdn-icons-png.flaticon.com/512/6001/6001527.png',badge:'https://cdn-icons-png.flaticon.com/512/6001/6001527.png',data:{url:d.url||'/app?v=9'},vibrate:[200,100,200]};e.waitUntil(self.registration.showNotification(t,o))});self.addEventListener('notificationclick',function(e){e.notification.close();e.waitUntil(clients.openWindow(e.notification.data.url||'/app?v=9'))});", mimetype="application/javascript")
@app.route("/")
@app.route("/app")
def app_page():
    return f"""
<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>V9 SUPERTREND STOCH VWAP</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{{font-family:'Inter',sans-serif;box-sizing:border-box;margin:0;padding:0}}
body{{background:#f8fafc;min-height:100vh;padding:12px 12px 120px}}
.header{{background:linear-gradient(135deg,#0f172a 0%,#10b981 100%);border-radius:20px;padding:14px;color:white;display:flex;justify-content:space-between;align-items:center}}
.logo{{width:40px;height:40px;background:rgba(255,255,255,.15);border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800}}
.tfs{{display:flex;gap:5px;margin:10px 0;overflow-x:auto}}
.tfs button{{border:none;background:white;padding:8px 12px;border-radius:999px;font-weight:700;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.tfs button.active{{background:#0f172a;color:white}}
.sens{{display:flex;gap:6px;margin:8px 0}}
.sens button{{border:1px solid #e2e8f0;background:white;padding:6px 10px;border-radius:999px;font-weight:700;font-size:11px}}
.sens button.active{{background:#10b981;color:white;border-color:#10b981}}
.coin-card{{background:white;border-radius:18px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.05);border:1px solid #f1f5f9;margin-top:10px}}
.coin-row{{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-bottom:1px solid #f8fafc;cursor:pointer}}
.coin-icon{{width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:700;color:white;font-size:13px}}
.btc{{background:linear-gradient(135deg,#f59e0b,#f97316)}}.eth{{background:linear-gradient(135deg,#6366f1,#8b5cf6)}}.oro{{background:linear-gradient(135deg,#eab308,#ca8a04)}}
.badge{{padding:4px 8px;border-radius:999px;font-weight:800;font-size:10px}}
.FERMO-bg{{background:#fef3c7;color:#92400e}}.COMPRA-bg{{background:#dcfce7;color:#166534}}.VENDI-bg{{background:#fee2e2;color:#991b1b}}
.paper-bar{{background:#0f172a;color:white;border-radius:14px;padding:10px 12px;margin-top:10px;display:flex;justify-content:space-between;align-items:center;font-size:12px}}
.fab{{position:fixed;bottom:12px;left:10px;right:10px;display:flex;gap:6px;z-index:20}}
.fab button{{flex:1;padding:10px;border-radius:14px;border:none;font-weight:700;box-shadow:0 8px 20px rgba(0,0,0,.15);font-size:11px}}
.btn-dark{{background:#0f172a;color:white}}.btn-light{{background:white;color:#0f172a;border:1px solid #e2e8f0!important}}.btn-blue{{background:#10b981;color:white}}
#modal{{position:fixed;inset:0;background:rgba(15,23,42,.75);backdrop-filter:blur(12px);display:none;align-items:end;justify-content:center;z-index:50;padding:8px}}
#modal.show{{display:flex}}
.modal-box{{background:white;width:100%;max-width:580px;border-radius:20px;padding:14px;max-height:96vh;overflow:auto}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:8px 0}}
.grid3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin:8px 0}}
.reason{{display:inline-block;background:#f1f5f9;padding:3px 6px;border-radius:6px;font-size:9px;margin:2px}}
.chart-wrap{{background:#0f172a;border-radius:12px;padding:8px;margin:8px 0}}
.win-badge{{display:inline-block;padding:5px 10px;border-radius:999px;font-weight:800;font-size:12px;margin-left:6px}}
.win-high{{background:#dcfce7;color:#166534;border:1px solid #bbf7d0}}.win-mid{{background:#fef3c7;color:#92400e}}.win-low{{background:#fee2e2;color:#991b1b}}
.open-trade{{background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:8px;margin:6px 0;font-size:11px;display:flex;justify-content:space-between;align-items:center}}
.winrate-big{{background:linear-gradient(135deg,#eff6ff 0%,#dcfce7 100%);border:2px solid #10b981;border-radius:12px;padding:10px;margin:8px 0;text-align:center}}
.new-ind{{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:8px;font-size:11px}}
</style>
</head><body>
<div class="header"><div style="display:flex;gap:10px;align-items:center"><div class="logo">V9</div><div><b>Vendi PRO V9</b><br><small>Supertrend + Stoch + VWAP + SR</small><br><small id=subStatus>Push: verifica...</small></div></div><div>🚀</div></div>
<div class="paper-bar" id=paperBar>
<div><b>💰 Paper Trading</b><br><span id=paperBalance>Saldo: €10.00</span><br><span id=paperPNL style="font-size:10px;color:#94a3b8">P/L: €0.00</span></div>
<div style="text-align:right"><button onclick="resetPaper()" style="background:rgba(255,255,255,.15);border:none;color:white;padding:6px 10px;border-radius:8px;font-size:10px">Reset</button><div style="font-size:9px;color:#4ade80" id=openCount>0 aperti</div></div>
</div>
<div id=openTradesList></div>
<div class="tfs">
<button onclick="loadTF('5m')" id=b5m>5m ⚡</button>
<button onclick="loadTF('15m')" id=b15m>15m ⚡</button>
<button onclick="loadTF('1H')" id=b1H class=active>1H</button>
<button onclick="loadTF('4H')" id=b4H>4H</button>
<button onclick="loadTF('1D')" id=b1D>1D</button>
</div>
<div class="sens">
<button onclick="setSens(55)" id=s55 class=active>SCALPER 55%</button>
<button onclick="setSens(60)" id=s60>PRO 60%</button>
<button onclick="setSens(65)" id=s65>ULTRA 65%</button>
</div>
<div class="coin-card"><div style="display:flex;justify-content:space-between;padding:12px"><div><small style="color:#64748b">GLOBALE V9</small><div id=globale style="font-weight:800;color:#dc2626;font-size:18px">...</div><small id=globaleSub style="color:#64748b"></small></div><div style="text-align:right"><small style="color:#64748b">AGGIORNATO</small><div id=agg style="font-weight:800">--</div><small id=srcInfo style="color:#10b981;font-size:10px"></small></div></div></div>
<div class="coin-card" id=coins>Caricamento V9...</div>

<div id=modal><div class="modal-box">
<div style="display:flex;justify-content:space-between;align-items:center"><div><b id=mCoin>ETH</b> <span id=mWinRate></span></div><span onclick="closeModal()" style="cursor:pointer;font-size:20px">✕</span></div>
<small id=mPrice style="color:#64748b"></small>
<div id=mWinRateBig class="winrate-big" style="display:none"></div>
<div class="chart-wrap"><div id=chart style="height:200px"></div><small id=chartInfo style="color:#94a3b8;font-size:10px">Grafico + Supertrend linea verde/rossa</small></div>

<div class="grid2" style="margin-top:8px">
<div style="background:#f8fafc;padding:8px;border-radius:10px;text-align:center"><small>SEGNALE</small><div id=mSignal style="font-weight:800"></div></div>
<div style="background:#f8fafc;padding:8px;border-radius:10px;text-align:center"><small>AFFID.</small><div id=mConf style="font-weight:800"></div></div>
<div style="background:#f8fafc;padding:8px;border-radius:10px;text-align:center"><small>RSI</small><div id=mRsi></div></div>
<div style="background:#f8fafc;padding:8px;border-radius:10px;text-align:center"><small>ADX / VOL</small><div id=mAdx></div></div>
</div>

<div class="new-ind" id=mNewInd>
<b>🚀 NUOVI INDICATORI V9</b><br>
<div class="grid2" style="margin-top:6px">
<div><small>Supertrend</small><div id=mST style="font-weight:700"></div></div>
<div><small>Stochastic K/D</small><div id=mStoch style="font-weight:700"></div></div>
<div><small>VWAP</small><div id=mVwap style="font-weight:700"></div></div>
<div><small>Supporto / Resistenza</small><div id=mSR style="font-size:10px"></div></div>
</div>
</div>

<div class="grid2" style="margin-top:8px">
<div style="background:#f8fafc;padding:8px;border-radius:10px"><small>EMA 50/200</small><div id=mEma style="font-size:11px"></div><small id=mEmaDetail style="color:#64748b"></small></div>
<div style="background:#f8fafc;padding:8px;border-radius:10px"><small>BB / MACD</small><div id=mBb style="font-size:11px"></div><div id=mMacd style="font-size:10px;color:#64748b"></div></div>
</div>
<div class="grid2">
<div style="background:#f8fafc;padding:8px;border-radius:10px"><small>ENTRY</small><div id=mEntry style="font-weight:700"></div></div>
<div style="background:#f8fafc;padding:8px;border-radius:10px"><small>SL / TP</small><div style="font-size:11px"><span id=mSL></span> / <span id=mTP></span></div></div>
</div>
<div><small style="font-weight:700;font-size:11px">Perché (con nuovi filtri):</small><div id=mReasons style="margin-top:4px"></div></div>

<div style="display:flex;gap:6px;margin-top:10px">
<button onclick="paperTrade('buy')" style="flex:1;padding:12px;border-radius:10px;border:none;background:#dcfce7;color:#166534;font-weight:700;font-size:13px">💰 Compra 1€</button>
<button onclick="paperTrade('sell')" style="flex:1;padding:12px;border-radius:10px;border:none;background:#fee2e2;color:#991b1b;font-weight:700;font-size:13px">💰 Vendi 1€</button>
</div>
<button onclick="openChart()" style="margin-top:8px;width:100%;padding:9px;border-radius:10px;border:none;background:#0f172a;color:white;font-weight:700;font-size:12px">📈 TradingView</button>
</div></div>

<script>
let curTF='1H', curSens=55, lastData=null, currentDetail=null;
const VAPID_PUBLIC_KEY="{VAPID_PUBLIC}";
function urlBase64ToUint8Array(b64){{const p='='.repeat((4-b64.length%4)%4);const base64=(b64+p).replace(/-/g,'+').replace(/_/g,'/');const raw=atob(base64);return Uint8Array.from([...raw].map(c=>c.charCodeAt(0)));}}
function getPaper(){{try{{return JSON.parse(localStorage.getItem('paper_v9')||'{{"balance":10,"trades":[],"open":[],"pnl":0,"closed":0}}')}}catch{{return {{"balance":10,"trades":[],"open":[],"pnl":0,"closed":0}}}}}}
function savePaper(p){{localStorage.setItem('paper_v9', JSON.stringify(p)); updatePaperBar(); renderOpen();}}
function updatePaperBar(){{const p=getPaper();document.getElementById('paperBalance').innerText='Saldo: €'+p.balance.toFixed(2);document.getElementById('paperPNL').innerText=`P/L: €${{p.pnl.toFixed(4)}} (${{p.closed}} chiusi)`;document.getElementById('openCount').innerText=p.open.length+' aperti';}}
function resetPaper(){{if(confirm('Azzerare paper?')) savePaper({{"balance":10,"trades":[],"open":[],"pnl":0,"closed":0}});}}
function renderOpen(){{const p=getPaper();const cont=document.getElementById('openTradesList');if(p.open.length===0){{cont.innerHTML='';return;}}let html='';p.open.forEach((t,idx)=>{{let curPrice=lastData&&lastData.coins[t.coin]?lastData.coins[t.coin].price:t.entry;let pnl=t.side==='COMPRA'?(curPrice-t.entry)/t.entry*1:(t.entry-curPrice)/t.entry*1;let pnlColor=pnl>=0?'#16a34a':'#dc2626';html+=`<div class="open-trade"><div><b>${{t.coin}} ${{t.side}}</b> 1€ @ $${{t.entry.toFixed(0)}}<br><small>ora $${{curPrice.toFixed(0)}} • <span style="color:${{pnlColor}};font-weight:700">${{pnl>=0?'+':''}}€${{pnl.toFixed(4)}}</span></small></div><button onclick="closeTrade(${{idx}})" style="background:#0f172a;color:white;border:none;padding:6px 10px;border-radius:8px;font-size:11px">Chiudi</button></div>`;}});cont.innerHTML=html;}}
function paperTrade(side){{if(!currentDetail||!lastData)return;const info=lastData.coins[currentDetail];const p=getPaper();if(p.balance<1){{alert('Saldo finito');return;}}const trade={{id:Date.now(),coin:currentDetail,side:side==='buy'?'COMPRA':'VENDI',entry:info.price,time:new Date().toLocaleTimeString(),tf:curTF,conf:info.conf}};p.open.push(trade);p.trades.unshift(trade);p.balance-=1;savePaper(p);closeModal();}}
function closeTrade(idx){{const p=getPaper();if(idx<0||idx>=p.open.length)return;const t=p.open[idx];let curPrice=lastData&&lastData.coins[t.coin]?lastData.coins[t.coin].price:t.entry;let pnl=t.side==='COMPRA'?(curPrice-t.entry)/t.entry*1:(t.entry-curPrice)/t.entry*1;p.balance+=1+pnl;p.pnl+=pnl;p.closed+=1;p.open.splice(idx,1);savePaper(p);}}
async function subscribePush(){{try{{const reg=await navigator.serviceWorker.register('/sw.js');await new Promise(r=>setTimeout(r,400));let ex=await reg.pushManager.getSubscription();if(ex){{try{{await ex.unsubscribe();}}catch{{}}}}const perm=await Notification.requestPermission();if(perm!=='granted')return;const sub=await reg.pushManager.subscribe({{userVisibleOnly:true,applicationServerKey:urlBase64ToUint8Array(VAPID_PUBLIC_KEY)}});const res=await fetch('/api/push/subscribe',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(sub)}});const j=await res.json();document.getElementById('subStatus').innerText='Push: ATTIVO ✅ '+j.total;}}catch(e){{}}}}
async function testPush(){{const r=await fetch('/api/push/test',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{}})}});const j=await r.json();alert('Test '+j.result.sent);}}
function colorFor(s){{return s=='COMPRA'?'#16a34a':s=='VENDI'?'#dc2626':'#d97706'}}
function bgFor(s){{return s=='COMPRA'?'COMPRA-bg':s=='VENDI'?'VENDI-bg':'FERMO-bg'}}
function setSens(v){{curSens=v;document.querySelectorAll('.sens button').forEach(b=>b.classList.remove('active'));document.getElementById('s'+v).classList.add('active');loadTF(curTF);}}
async function loadTF(tf){{
  curTF=tf;
  document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active'));const el=document.getElementById('b'+tf);if(el)el.classList.add('active');
  document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center;color:#64748b">⏳ V9 '+curSens+'% '+tf+'...</div>';
  try{{
    const res=await fetch('/api/signals?tf='+tf+'&sens='+curSens);const d=await res.json();lastData=d;
    document.getElementById('globale').innerText=d.globale||'...';document.getElementById('globale').style.color=colorFor(d.globale);
    document.getElementById('globaleSub').innerText=(d.globale||'')+' • TF '+tf+' • V9 con Supertrend';document.getElementById('agg').innerText=d.updated||'--';document.getElementById('srcInfo').innerText=d.source||'';
    let html='';
    for(let [name,info] of Object.entries(d.coins)){{
      const icon=name=='BTC'?'btc':name=='ETH'?'eth':'oro';const ico=name=='BTC'?'₿':name=='ETH'?'Ξ':'Au';
      const stIcon = info.st_trend==1?'🟢':'🔴';
      html+=`<div class=coin-row onclick="openDetails('${{name}}')"><div style="display:flex;gap:8px;align-items:center"><div class="coin-icon ${{icon}}">${{ico}}</div><div><b>${{name}} <span style="font-size:9px">${{stIcon}} ST</span> <span style="font-size:9px;color:#64748b">Stoch ${{info.stoch_k.toFixed(0)}}</span></b><div style="font-size:10px;color:#64748b">RSI ${{info.rsi.toFixed(1)}} • ${{info.trend}} • VWAP ${{info.price>info.vwap?'↑':'↓'}}</div></div></div><div style="text-align:right"><span class="badge ${{bgFor(info.signal)}}">${{info.signal}} ${{info.conf}}%</span><div style="font-weight:800;margin-top:2px;font-size:12px">$${{info.price.toFixed(2)}}</div></div></div>`;
    }}
    document.getElementById('coins').innerHTML=html;renderOpen();
  }}catch(e){{document.getElementById('coins').innerHTML='Errore '+e.message;}}
}}
async function openDetails(coin){{
  if(!lastData)return;const info=lastData.coins[coin];if(!info)return;currentDetail=coin;
  document.getElementById('mCoin').innerText=coin+' • '+info.symbol+' • TF '+curTF+' • V9';
  document.getElementById('mPrice').innerText='$'+info.price.toFixed(2)+' • '+info.trend;
  document.getElementById('mSignal').innerText=info.signal;document.getElementById('mSignal').style.color=colorFor(info.signal);
  document.getElementById('mConf').innerText=info.signal+' '+info.conf+'%';
  document.getElementById('mRsi').innerText='RSI '+info.rsi;
  document.getElementById('mAdx').innerText='ADX '+info.adx.toFixed(0)+' Vol x'+info.vol_ratio.toFixed(2);
  document.getElementById('mEma').innerText='$'+info.ema50.toFixed(0)+' / $'+info.ema200.toFixed(0);
  document.getElementById('mEmaDetail').innerText=info.ema50>info.ema200?'Sopra rialzista':'Sotto ribassista';
  document.getElementById('mBb').innerText='BB '+info.bb_up.toFixed(0)+'/'+info.bb_low.toFixed(0);
  document.getElementById('mMacd').innerText='MACD '+info.macd.toFixed(2)+' vs '+info.macd_signal.toFixed(2);
  document.getElementById('mEntry').innerText='$'+info.price.toFixed(2);
  document.getElementById('mSL').innerText=info.sl?'$'+info.sl.toFixed(2):'-';
  document.getElementById('mTP').innerText=info.tp?'$'+info.tp.toFixed(2):'-';
  // NEW
  document.getElementById('mST').innerText=(info.st_trend==1?'🟢 Rialzista':'🔴 Ribassista')+' $'+info.st_val.toFixed(0);
  document.getElementById('mStoch').innerText='K '+info.stoch_k.toFixed(1)+' D '+info.stoch_d.toFixed(1)+(info.stoch_k<20?' ipervenduto':info.stoch_k>80?' ipercomprato':'');
  document.getElementById('mVwap').innerText='$'+info.vwap.toFixed(2)+(info.price>info.vwap?' sopra ↑':' sotto ↓');
  document.getElementById('mSR').innerText='Sup $'+info.support.toFixed(0)+' ('+info.dist_sup.toFixed(1)+'% sotto) Res $'+info.resistance.toFixed(0)+' ('+info.dist_res.toFixed(1)+'% sopra)';
  document.getElementById('mReasons').innerHTML=info.reasons.map(r=>`<span class=reason>${{r}}</span>`).join(' ');
  document.getElementById('modal').classList.add('show');
  loadChart(coin, curTF, info); loadBacktest(coin, curTF);
}}
async function loadChart(coin, tf, info){{
  try{{
    const r=await fetch('/api/chart?coin='+coin+'&tf='+tf);const j=await r.json();if(!j.ok)return;
    const chartEl=document.getElementById('chart');chartEl.innerHTML='';
    const c=LightweightCharts.createChart(chartEl,{{width:chartEl.clientWidth,height:200,layout:{{background:{{color:'#0f172a'}},textColor:'#94a3b8'}},grid:{{vertLines:{{color:'#1e293b'}},horzLines:{{color:'#1e293b'}}}},timeScale:{{timeVisible:true}}}});
    const series=c.addCandlestickSeries();series.setData(j.data.map(d=>({{time:d.time,open:d.open,high:d.high,low:d.low,close:d.close}})));
    if(info && info.st_val){{
      const stSeries=c.addLineSeries({{color: info.st_trend==1?'#22c55e':'#ef4444', lineWidth:2}});
      // linea supertrend piatta per semplicità (ultimo valore)
      const stData=j.data.map(d=>({{time:d.time, value: info.st_val}}));
      stSeries.setData(stData);
    }}
    c.timeScale().fitContent();
  }}catch(e){{}}
}}
async function loadBacktest(coin, tf){{
  try{{
    const elBig=document.getElementById('mWinRateBig');
    elBig.style.display='block';
    elBig.innerHTML='⏳ Calcolo WinRate V9 con nuovi filtri...';
    const r=await fetch('/api/backtest?coin='+coin+'&tf='+tf+'&sens='+curSens);
    const j=await r.json();
    const last20=j.last20_win||0;
    const wr=j.win_rate||0;
    const cls = last20>=60?'win-high':last20>=50?'win-mid':'win-low';
    const total=j.total_signals||0;
    const wins=j.wins||0;
    elBig.innerHTML=`<div style="display:flex;justify-content:space-between;align-items:center"><div style="text-align:left"><b style="font-size:14px">📊 WINRATE V9 ${{tf}}</b><br><small style="color:#64748b">${{wins}}/${{total}} vinti • ${{wr}}% storico • con Supertrend+Stoch+VWAP</small></div><span class="win-badge ${{cls}}" style="font-size:16px">${{last20}}%</span></div><div style="margin-top:8px;display:flex;gap:3px;justify-content:center">${{(j.last20||[]).slice(0,12).map(x=>`<span style="display:inline-block;width:14px;height:14px;border-radius:50%;background:${{x.win?'#22c55e':'#ef4444'}};border:1px solid white"></span>`).join('')}} </div><small style="color:#64748b">Ultimi 12 segnali V9: verde=win rosso=loss</small>`;
    document.getElementById('mWinRate').innerHTML=`<span class="win-badge ${{cls}}">${{last20}}% win V9</span>`;
  }}catch(e){{
    document.getElementById('mWinRateBig').innerHTML='Errore winrate: '+e.message;
  }}
}}
function closeModal(){{document.getElementById('modal').classList.remove('show')}}
function openChart(){{if(!currentDetail)return;const map={{BTC:'BINANCE:BTCUSDT',ETH:'BINANCE:ETHUSDT',ORO:'BINANCE:PAXGUSDT'}};window.open('https://www.tradingview.com/chart/?symbol='+map[currentDetail]+'&interval='+curTF,'_blank');}}
loadTF('1H'); setInterval(()=>{{loadTF(curTF);renderOpen();}},20000);
updatePaperBar();
if('serviceWorker' in navigator){{navigator.serviceWorker.register('/sw.js').then(()=>{{fetch('/api/ping').then(r=>r.json()).then(j=>{{document.getElementById('subStatus').innerText='Push: '+j.subs+' iscritti - V9';}})}});}}
</script>
</body></html>
"""
if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
