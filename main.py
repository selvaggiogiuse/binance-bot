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
def compute_entry_quality(comp):
    signal = comp["signal"]
    score = 0
    checks = []
    if signal == "FERMO":
        return {"score": 20, "label": "⏳ ASPETTA", "color": "wait", "simple": "Nessun movimento chiaro. Meglio non fare nulla.", "checks": []}
    if comp["conf"] >= 70:
        score += 20; checks.append("Affidabilità alta")
    elif comp["conf"] >= 65:
        score += 12
    elif comp["conf"] >= 60:
        score += 5
    if comp["adx"] >= 25:
        score += 10
    elif comp["adx"] >= 18:
        score += 5
    if comp["vol_ratio"] >= 1.2:
        score += 10
    elif comp["vol_ratio"] >= 0.8:
        score += 5
    if signal == "COMPRA" and comp["st_trend"] == 1 and comp["price"] > comp["st_val"]:
        score += 15
    elif signal == "VENDI" and comp["st_trend"] == -1 and comp["price"] < comp["st_val"]:
        score += 15
    if signal == "COMPRA":
        if comp["stoch_k"] < 40 and comp["stoch_k"] > comp["stoch_d"]:
            score += 10
        elif comp["stoch_k"] < 25:
            score += 8
        elif comp["stoch_k"] < 60:
            score += 4
    else:
        if comp["stoch_k"] > 60 and comp["stoch_k"] < comp["stoch_d"]:
            score += 10
        elif comp["stoch_k"] > 75:
            score += 8
        elif comp["stoch_k"] > 40:
            score += 4
    if signal == "COMPRA" and comp["price"] > comp["vwap"]:
        score += 10
    elif signal == "VENDI" and comp["price"] < comp["vwap"]:
        score += 10
    if signal == "COMPRA":
        if comp["dist_sup"] < 1.0 and comp["dist_res"] > 0.8:
            score += 10
        elif comp["dist_sup"] < 2.0:
            score += 4
    else:
        if comp["dist_res"] < 1.0 and comp["dist_sup"] > 0.8:
            score += 10
        elif comp["dist_res"] < 2.0:
            score += 4
    if signal == "COMPRA" and comp["ema50"] > comp["ema200"]:
        score += 5
    elif signal == "VENDI" and comp["ema50"] < comp["ema200"]:
        score += 5
    if signal == "COMPRA" and comp["macd"] > comp["macd_signal"]:
        score += 5
    elif signal == "VENDI" and comp["macd"] < comp["macd_signal"]:
        score += 5

    # Messaggio semplice per principianti
    if signal == "COMPRA":
        if score >= 70:
            simple = f"Il prezzo sta salendo. È vicino al supporto (${comp['support']:.0f}) e ha spazio per salire fino a ${comp['resistance']:.0f}. Buon momento per COMPRARE con 1€."
        elif score >= 50:
            simple = f"Sta provando a salire, ma non è ancora fortissimo. Meglio aspettare la prossima candela."
        else:
            simple = f"Non è un buon momento per comprare. Il trend è debole, rischi di perdere l'1€ di fee."
    else: # VENDI
        if score >= 70:
            simple = f"Il prezzo sta scendendo. È vicino alla resistenza (${comp['resistance']:.0f}) e può scendere fino a ${comp['support']:.0f}. Buon momento per VENDERE con 1€."
        elif score >= 50:
            simple = f"Sta provando a scendere, ma non è ancora fortissimo. Meglio aspettare."
        else:
            simple = f"Non è un buon momento per vendere. Sei vicino al supporto, potrebbe rimbalzare."

    if score >= 70:
        label = "✅ ENTRA"; color = "entra"
    elif score >= 50:
        label = "⚠️ QUASI"; color = "quasi"
    else:
        label = "⏳ ASPETTA"; color = "wait"
        if signal != "FERMO":
            simple = "Meglio non fare nulla adesso. Aspetta un segnale con ✅ ENTRA."

    return {"score": score, "label": label, "color": color, "simple": simple, "checks": checks}

def compute_from_ohlc(ohlc, live_price=None, sens=55):
    closes = [float(x[4]) for x in ohlc]; highs = [float(x[2]) for x in ohlc]; lows = [float(x[3]) for x in ohlc]; volumes = [float(x[6]) for x in ohlc]
    close_price = live_price if live_price else closes[-1]; closes[-1] = close_price
    rsi = rsi_calc(closes); ema50 = ema_calc(closes, 50); ema200 = ema_calc(closes, 200)
    bb_up, bb_low, bb_mid = bollinger_calc(closes); macd, macd_sig = macd_calc(closes)
    adx = adx_calc(highs, lows, closes); atr = atr_calc(highs, lows, closes)
    st_val, st_trend = supertrend_calc(highs, lows, closes, 10, 3.0)
    stoch_k, stoch_d = stoch_calc(highs, lows, closes, 14, 3)
    vwap = vwap_calc(highs, lows, closes, volumes, 20)
    support, resistance = sr_calc(highs, lows, closes, 20)
    vol_avg = sum(volumes[-20:])/20 if len(volumes)>=20 else volumes[-1] if volumes else 1
    vol_ratio = volumes[-1]/vol_avg if vol_avg else 1.0
    bullish = 50; bearish = 50; reasons = []
    if rsi < 30: bullish+=20
    elif rsi > 70: bearish+=20
    elif rsi > 55: bullish+=8
    elif rsi < 45: bearish+=8
    if ema50 > ema200: bullish+=10
    else: bearish+=10
    if close_price > ema50: bullish+=6
    else: bearish+=6
    if macd > macd_sig: bullish+=8
    else: bearish+=8
    if close_price > bb_up: bearish+=8
    elif close_price < bb_low: bullish+=8
    if st_trend == 1 and close_price > st_val: bullish+=12
    elif st_trend == -1 and close_price < st_val: bearish+=12
    if stoch_k < 20 and stoch_k > stoch_d: bullish+=10
    elif stoch_k > 80 and stoch_k < stoch_d: bearish+=10
    elif stoch_k > stoch_d: bullish+=5
    else: bearish+=5
    if close_price > vwap: bullish+=6
    else: bearish+=6
    dist_sup = (close_price - support)/close_price*100 if close_price else 0
    dist_res = (resistance - close_price)/close_price*100 if close_price else 0
    if dist_sup < 1.0: bullish+=6
    if dist_res < 1.0: bearish+=6
    if vol_ratio > 1.2:
        if bullish>bearish: bullish+=4
        else: bearish+=4
    total = bullish+bearish; bull_pct = bullish/total*100
    buy_thr = sens; sell_thr = 100 - sens
    if bull_pct >= buy_thr: signal = "COMPRA"; conf = int(bull_pct)
    elif bull_pct <= sell_thr: signal = "VENDI"; conf = int(100-bull_pct)
    else: signal = "FERMO"; conf = int(50 + abs(bull_pct-50)*0.8); conf = max(conf,50)
    trend = "Rialzista" if bullish>bearish else "Ribassista" if bearish>bullish else "Laterale"
    if signal == "COMPRA": sl = close_price - atr*1.5; tp = close_price + atr*2.5
    elif signal == "VENDI": sl = close_price + atr*1.5; tp = close_price - atr*2.5
    else: sl = close_price - atr; tp = close_price + atr
    comp = {"price": close_price,"rsi": round(rsi,1),"signal": signal,"conf": conf,"trend": trend,"ema50": ema50,"ema200": ema200,"bb_up": bb_up,"bb_low": bb_low,"macd": macd,"macd_signal": macd_sig,"vol_ratio": round(vol_ratio,2),"adx": round(adx,0),"atr": round(atr,2),"sl": sl,"tp": tp,"reasons": reasons[:6],"bullish": int(bull_pct),"bearish": int(100-bull_pct),
            "st_val": st_val, "st_trend": st_trend, "stoch_k": round(stoch_k,1), "stoch_d": round(stoch_d,1), "vwap": vwap, "support": support, "resistance": resistance, "dist_sup": round(dist_sup,2), "dist_res": round(dist_res,2)}
    quality = compute_entry_quality(comp)
    comp["quality_score"] = quality["score"]
    comp["quality_label"] = quality["label"]
    comp["quality_color"] = quality["color"]
    comp["quality_simple"] = quality["simple"]
    comp["quality_checks"] = quality["checks"]
    return comp

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
def send_push_to_all(title, body, url="/app?v=10"):
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
def ping(): return jsonify({"ok":True,"msg":"V10 LITE BEGINNER","time":rome_now().isoformat(),"subs": len(load_subs())})
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
            coins_data[coin] = {"symbol": f"{coin}USD","price": 0,"rsi": 50.0,"signal": "FERMO","conf": 50,"trend": "Caricamento","tf": tf,"ema50": 0,"ema200": 0,"bb_up": 0,"bb_low": 0,"macd": 0,"macd_signal": 0,"vol_ratio": 1.0,"adx": 20,"atr": 0,"sl": 0,"tp": 0,"reasons": [],"bullish": 50,"bearish": 50,"st_val": 0,"st_trend":1,"stoch_k":50,"stoch_d":50,"vwap":0,"support":0,"resistance":0,"dist_sup":2,"dist_res":2,"quality_score":0,"quality_label":"⏳ ASPETTA","quality_color":"wait","quality_simple":"Caricamento...","quality_checks":[]}
    max_conf=0; globale="FERMO"
    for v in coins_data.values():
        if v["signal"] in ("COMPRA","VENDI") and v["conf"]>max_conf: max_conf=v["conf"]; globale=v["signal"]
    if max_conf==0:
        for v in coins_data.values():
            if v["conf"]>max_conf: max_conf=v["conf"]; globale=v["signal"]
    btc_price = coins_data["BTC"]["price"]
    return jsonify({"coins": coins_data,"globale": globale,"tf": tf,"updated": rome_now().strftime("%H:%M:%S"),"source": f"{source_name} V10 LITE TF {tf}"})
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
    for c in ohlc[-80:]:
        data.append({"time": int(c[0]), "open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4])})
    live = binance_fast_price()
    if live.get(coin) and data:
        data[-1]["close"] = live[coin]
    return jsonify({"ok":True, "data": data})
@app.route("/api/push/subscribe", methods=["POST"])
def sub():
    try:
        data = request.get_json(force=True); subs = load_subs()
        ep = data.get("endpoint",""); subs = [s for s in subs if s.get("endpoint")!=ep]
        subs.append(data); save_subs(subs)
        return jsonify({"ok":True,"total":len(subs)})
    except Exception as e:
        return jsonify({"ok":False,"error": str(e)}), 500
@app.route("/sw.js")
def sw():
    return Response("self.addEventListener('push',function(e){let d={};try{d=e.data.json()}catch{d={title:'Vendi PRO',body:e.data.text()}}const t=d.title||'Vendi PRO V10';const o={body:d.body||'Segnale!',icon:'https://cdn-icons-png.flaticon.com/512/6001/6001527.png',badge:'https://cdn-icons-png.flaticon.com/512/6001/6001527.png',data:{url:d.url||'/app?v=10'},vibrate:[200,100,200]};e.waitUntil(self.registration.showNotification(t,o))});self.addEventListener('notificationclick',function(e){e.notification.close();e.waitUntil(clients.openWindow(e.notification.data.url||'/app?v=10'))});", mimetype="application/javascript")
@app.route("/")
@app.route("/app")
def app_page():
    return f"""
<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>V10 LITE per Principianti</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{{font-family:'Inter',sans-serif;box-sizing:border-box;margin:0;padding:0}}
body{{background:#f8fafc;min-height:100vh;padding:12px 12px 120px}}
.header{{background:linear-gradient(135deg,#0f172a 0%,#3b82f6 100%);border-radius:20px;padding:16px;color:white}}
.tfs{{display:flex;gap:6px;margin:12px 0}}
.tfs button{{border:none;background:white;padding:10px 14px;border-radius:999px;font-weight:700;font-size:13px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.tfs button.active{{background:#0f172a;color:white}}
.coin-card{{background:white;border-radius:20px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.05);border:1px solid #f1f5f9;margin-top:12px}}
.coin-row{{display:flex;justify-content:space-between;align-items:center;padding:16px;border-bottom:1px solid #f8fafc;cursor:pointer}}
.coin-icon{{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:700;color:white;font-size:16px}}
.btc{{background:linear-gradient(135deg,#f59e0b,#f97316)}}.eth{{background:linear-gradient(135deg,#6366f1,#8b5cf6)}}.oro{{background:linear-gradient(135deg,#eab308,#ca8a04)}}
.badge{{padding:6px 10px;border-radius:999px;font-weight:800;font-size:12px}}
.badge-entra{{background:#dcfce7;color:#166534;border:2px solid #16a34a}}.badge-quasi{{background:#fef3c7;color:#92400e;border:2px solid #d97706}}.badge-wait{{background:#f1f5f9;color:#64748b;border:1px solid #e2e8f0}}
.paper-bar{{background:#0f172a;color:white;border-radius:14px;padding:12px;margin-top:12px;display:flex;justify-content:space-between;align-items:center}}
#modal{{position:fixed;inset:0;background:rgba(15,23,42,.75);backdrop-filter:blur(12px);display:none;align-items:end;justify-content:center;z-index:50;padding:10px}}
#modal.show{{display:flex}}
.modal-box{{background:white;width:100%;max-width:560px;border-radius:24px;padding:18px;max-height:96vh;overflow:auto}}
.big-box{{border-radius:16px;padding:18px;margin:12px 0;text-align:center}}
.entra-big{{background:linear-gradient(135deg,#dcfce7 0%,#bbf7d0 100%);border:3px solid #16a34a}}
.wait-big{{background:linear-gradient(135deg,#f1f5f9 0%,#e2e8f0 100%);border:2px solid #94a3b8}}
.quasi-big{{background:linear-gradient(135deg,#fef3c7 0%,#fde68a 100%);border:2px solid #d97706}}
.simple-text{{font-size:14px;line-height:1.5;color:#334155;margin:10px 0}}
.chart-wrap{{background:#0f172a;border-radius:12px;padding:8px;margin:10px 0}}
</style>
</head><body>
<div class="header">
<div style="display:flex;justify-content:space-between;align-items:center"><div><b style="font-size:18px">V10 LITE 😊</b><br><small>Modalità Principiante - Solo 3 cose da guardare</small></div><div style="font-size:24px">👋</div></div>
<div style="margin-top:10px;background:rgba(255,255,255,.15);border-radius:12px;padding:10px;font-size:12px">
👉 <b>Come funziona?</b><br>
🟢 <b>✅ ENTRA</b> = Puoi comprare/vendere con 1€<br>
🟡 <b>⚠️ QUASI</b> = Aspetta ancora un po'<br>
⚪ <b>⏳ ASPETTA</b> = Non fare nulla, rischi di perdere
</div>
</div>

<div class="paper-bar">
<div><b>💰 Il tuo saldo finto</b><br><span id=paperBalance>€10.00</span> • <span id=paperPNL style="color:#94a3b8">P/L €0</span></div>
<div style="text-align:right"><span id=openCount style="font-size:12px">0 aperti</span></div>
</div>
<div id=openTradesList></div>

<div class="tfs">
<button onclick="loadTF('1H')" id=b1H class=active>1H (consigliato)</button>
<button onclick="loadTF('4H')" id=b4H>4H</button>
<button onclick="loadTF('1D')" id=b1D>1D</button>
<button onclick="loadTF('5m')" id=b5m>5m (rischioso)</button>
</div>

<div class="coin-card" id=coins>Caricamento...</div>

<div id=modal><div class="modal-box">
<div style="display:flex;justify-content:space-between;align-items:center"><b id=mCoin style="font-size:18px">ETH</b><span onclick="closeModal()" style="font-size:24px;cursor:pointer">✕</span></div>
<small id=mPrice style="color:#64748b"></small>

<div id=mQualityBig class="big-box wait-big"></div>

<div class="chart-wrap"><div id=chart style="height:180px"></div></div>

<div style="background:#f8fafc;border-radius:12px;padding:12px;margin:8px 0">
<small style="font-weight:700">📊 Quanto è affidabile?</small>
<div id=mWinRateBig style="margin-top:6px;font-size:13px"></div>
</div>

<div id=mSimpleBox style="background:#eff6ff;border-radius:12px;padding:14px;margin:8px 0;border-left:4px solid #3b82f6">
<b style="font-size:13px">💬 In parole semplici:</b>
<div id=mSimpleText class="simple-text"></div>
</div>

<div style="display:flex;gap:8px;margin-top:12px">
<button onclick="paperTrade('buy')" id=btnBuy style="flex:1;padding:16px;border-radius:14px;border:none;background:#dcfce7;color:#166534;font-weight:800;font-size:15px">💰 Compra 1€</button>
<button onclick="paperTrade('sell')" id=btnSell style="flex:1;padding:16px;border-radius:14px;border:none;background:#fee2e2;color:#991b1b;font-weight:800;font-size:15px">💰 Vendi 1€</button>
</div>

<details style="margin-top:14px"><summary style="font-size:12px;color:#64748b;cursor:pointer">🔧 Vuoi vedere i dettagli da esperto? (RSI, EMA...)</summary>
<div id=mExpert style="font-size:11px;color:#64748b;margin-top:8px;background:#f8fafc;padding:10px;border-radius:10px"></div>
</details>

</div></div>

<script>
let curTF='1H', curSens=55, lastData=null, currentDetail=null;
function getPaper(){{try{{return JSON.parse(localStorage.getItem('paper_v10')||'{{"balance":10,"trades":[],"open":[],"pnl":0,"closed":0}}')}}catch{{return {{"balance":10,"trades":[],"open":[],"pnl":0,"closed":0}}}}}}
function savePaper(p){{localStorage.setItem('paper_v10', JSON.stringify(p)); updatePaperBar(); renderOpen();}}
function updatePaperBar(){{const p=getPaper();document.getElementById('paperBalance').innerText='€'+p.balance.toFixed(2);document.getElementById('paperPNL').innerText=`P/L €${{p.pnl.toFixed(3)}}`;document.getElementById('openCount').innerText=p.open.length+' aperti';}}
function renderOpen(){{const p=getPaper();const cont=document.getElementById('openTradesList');if(p.open.length===0){{cont.innerHTML='';return;}}let html='';p.open.forEach((t,idx)=>{{let curPrice=lastData&&lastData.coins[t.coin]?lastData.coins[t.coin].price:t.entry;let pnl=t.side==='COMPRA'?(curPrice-t.entry)/t.entry*1:(t.entry-curPrice)/t.entry*1;html+=`<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:10px;margin:6px 0;font-size:12px;display:flex;justify-content:space-between"><div><b>${{t.coin}} ${{t.side}}</b> @ $${{t.entry.toFixed(0)}} • ${{pnl>=0?'+':''}}€${{pnl.toFixed(4)}}</div><button onclick="closeTrade(${{idx}})" style="background:#0f172a;color:white;border:none;padding:6px 10px;border-radius:8px">Chiudi</button></div>`;}});cont.innerHTML=html;}}
function paperTrade(side){{if(!currentDetail||!lastData)return;const info=lastData.coins[currentDetail];const p=getPaper();if(info.quality_color!='entra' && !confirm(`⚠️ Il sistema dice ${{info.quality_label}}. Sicuro di voler entrare con 1€ finto lo stesso?`))return;if(p.balance<1){{alert('Saldo finito, resetta');return;}}const trade={{id:Date.now(),coin:currentDetail,side:side==='buy'?'COMPRA':'VENDI',entry:info.price}};p.open.push(trade);p.balance-=1;savePaper(p);closeModal();}}
function closeTrade(idx){{const p=getPaper();const t=p.open[idx];let curPrice=lastData&&lastData.coins[t.coin]?lastData.coins[t.coin].price:t.entry;let pnl=t.side==='COMPRA'?(curPrice-t.entry)/t.entry*1:(t.entry-curPrice)/t.entry*1;p.balance+=1+pnl;p.pnl+=pnl;p.closed+=1;p.open.splice(idx,1);savePaper(p);}}
function qualityBadge(q){{if(q.color=='entra')return `<span class="badge badge-entra">${{q.label}}</span>`; if(q.color=='quasi')return `<span class="badge badge-quasi">${{q.label}}</span>`; return `<span class="badge badge-wait">${{q.label}}</span>`;}}
async function loadTF(tf){{
  curTF=tf;
  document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active'));const el=document.getElementById('b'+tf);if(el)el.classList.add('active');
  document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center">⏳ Carico...</div>';
  try{{
    const res=await fetch('/api/signals?tf='+tf+'&sens='+curSens);const d=await res.json();lastData=d;
    let html='';
    for(let [name,info] of Object.entries(d.coins)){{
      const icon=name=='BTC'?'btc':name=='ETH'?'eth':'oro';const ico=name=='BTC'?'₿':name=='ETH'?'Ξ':'Au';
      const qBadge = qualityBadge(info);
      const price = `$${{info.price.toFixed(2)}}`;
      let actionText = info.quality_color=='entra' ? (info.signal=='COMPRA'?'Compra ora':'Vendi ora') : info.quality_color=='quasi' ? 'Quasi pronto' : 'Non fare nulla';
      html+=`<div class=coin-row onclick="openDetails('${{name}}')"><div style="display:flex;gap:10px;align-items:center"><div class="coin-icon ${{icon}}">${{ico}}</div><div><b style="font-size:16px">${{name}}</b> • ${{price}}<div style="font-size:12px;color:#64748b;margin-top:2px">${{actionText}}</div></div></div><div style="text-align:right">${{qBadge}}<div style="font-size:11px;color:#64748b;margin-top:4px">${{info.signal}} ${{info.conf}}%</div></div></div>`;
    }}
    document.getElementById('coins').innerHTML=html;renderOpen();
  }}catch(e){{document.getElementById('coins').innerHTML='Errore '+e.message;}}
}}
async function openDetails(coin){{
  if(!lastData)return;const info=lastData.coins[coin];if(!info)return;currentDetail=coin;
  document.getElementById('mCoin').innerText=coin+' • $'+info.price.toFixed(2);
  document.getElementById('mPrice').innerText=info.signal+' '+info.conf+'% • TF '+curTF;
  const big=document.getElementById('mQualityBig');
  big.className='big-box '+(info.quality_color=='entra'?'entra-big':info.quality_color=='quasi'?'quasi-big':'wait-big');
  if(info.quality_color=='entra'){{
    big.innerHTML=`<div style="font-size:22px;font-weight:800;color:${{info.signal=='COMPRA'?'#166534':'#991b1b'}}">${{info.quality_label}} - ${{info.signal}}</div><div style="font-size:14px;margin-top:6px">Puoi entrare con 1€ finto</div><div style="font-size:12px;color:#64748b;margin-top:4px">Affidabilità ${{info.quality_score}}% • SL $${{info.sl.toFixed(0)}} TP $${{info.tp.toFixed(0)}}</div>`;
  }} else if(info.quality_color=='quasi'){{
    big.innerHTML=`<div style="font-size:20px;font-weight:800;color:#92400e">⚠️ QUASI PRONTO</div><div style="font-size:13px;margin-top:6px">Manca poco, aspetta 15-30 min</div><div style="font-size:11px;color:#64748b">Score ${{info.quality_score}}%</div>`;
  }} else {{
    big.innerHTML=`<div style="font-size:20px;font-weight:800;color:#475569">⏳ ASPETTA</div><div style="font-size:13px;margin-top:6px">Non è il momento giusto, rischi di perdere</div><div style="font-size:11px;color:#64748b">Meglio aspettare ✅ ENTRA</div>`;
  }}
  document.getElementById('mSimpleText').innerText=info.quality_simple;
  document.getElementById('mExpert').innerHTML=`RSI ${{info.rsi}} • EMA ${{info.ema50.toFixed(0)}}/${{info.ema200.toFixed(0)}} • Supertrend ${{info.st_trend==1?'🟢':'🔴'}} $${{info.st_val.toFixed(0)}} • Stoch K${{info.stoch_k}} • VWAP $${{info.vwap.toFixed(0)}} • Sup $${{info.support.toFixed(0)}} Res $${{info.resistance.toFixed(0)}} • ADX ${{info.adx}} Vol x${{info.vol_ratio}}`;
  document.getElementById('modal').classList.add('show');
  loadChart(coin, curTF); loadBacktest(coin, curTF);
}}
async function loadChart(coin, tf){{
  try{{
    const r=await fetch('/api/chart?coin='+coin+'&tf='+tf);const j=await r.json();if(!j.ok)return;
    const chartEl=document.getElementById('chart');chartEl.innerHTML='';
    const c=LightweightCharts.createChart(chartEl,{{width:chartEl.clientWidth,height:180,layout:{{background:{{color:'#0f172a'}},textColor:'#94a3b8'}},grid:{{vertLines:{{color:'#1e293b'}},horzLines:{{color:'#1e293b'}}}},timeScale:{{timeVisible:true}}}});
    const series=c.addCandlestickSeries();series.setData(j.data.map(d=>({{time:d.time,open:d.open,high:d.high,low:d.low,close:d.close}})));c.timeScale().fitContent();
  }}catch(e){{}}
}}
async function loadBacktest(coin, tf){{
  try{{
    const r=await fetch('/api/backtest?coin='+coin+'&tf='+tf);const j=await r.json();
    const last20=j.last20_win||0;
    const cls = last20>=60?'🟢 Buono':'🟡 Medio';
    document.getElementById('mWinRateBig').innerHTML=`Ultimi 12 trade: ${{(j.last20||[]).map(x=>x.win?'🟢':'🔴').join('')}}<br>Negli ultimi test ha vinto il <b>${{last20}}%</b> delle volte ${{cls}}<br><small style="color:#64748b">${{j.wins}} vinti su ${{j.total_signals}} totali</small>`;
  }}catch(e){{}}
}}
function closeModal(){{document.getElementById('modal').classList.remove('show')}}
loadTF('1H'); setInterval(()=>loadTF(curTF),30000);
updatePaperBar();
</script>
</body></html>
"""
if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
