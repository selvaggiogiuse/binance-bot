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
OHLC_CACHE = {}
CACHE_TTL = 45
PAIRS_KRAKEN = {"BTC": "XBTUSD","ETH": "ETHUSD","ORO": "PAXGUSD"}
PAIRS_BINANCE = {"BTC": "BTCUSDT","ETH": "ETHUSDT","ORO": "PAXGUSDT"}
TF_MAP = {"5m": 5,"15m": 15,"1H": 60,"4H": 240,"1D": 1440}
SUBS_FILE = "/tmp/subs.json"
LAST_SIGNALS_FILE = "/tmp/last_signals.json"

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
    vol_avg = sum(volumes[-20:])/20 if len(volumes)>=20 else volumes[-1] if volumes else 1
    vol_ratio = volumes[-1]/vol_avg if vol_avg else 1.0
    bullish = 50; bearish = 50; reasons = []
    if rsi < 30: bullish+=20; reasons.append(f"RSI ipervenduto {rsi:.0f}")
    elif rsi > 70: bearish+=20; reasons.append(f"RSI ipercomprato {rsi:.0f}")
    elif rsi > 55: bullish+=8; reasons.append(f"RSI {rsi:.0f} rialzista")
    elif rsi < 45: bearish+=8; reasons.append(f"RSI {rsi:.0f} ribassista")
    else: reasons.append(f"RSI neutro {rsi:.0f}")
    if ema50 > ema200: bullish+=12; reasons.append("EMA 50>200 rialzista")
    else: bearish+=12; reasons.append("EMA 50<200 ribassista")
    if close_price > ema50: bullish+=8
    else: bearish+=8
    if macd > macd_sig: bullish+=10; reasons.append("MACD ↑")
    else: bearish+=10; reasons.append("MACD ↓")
    if close_price > bb_up: bearish+=10; reasons.append("Sopra BB upper")
    elif close_price < bb_low: bullish+=10; reasons.append("Sotto BB lower")
    if vol_ratio > 1.2:
        if bullish>bearish: bullish+=5
        else: bearish+=5
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
    return {"price": close_price,"rsi": round(rsi,1),"signal": signal,"conf": conf,"trend": trend,"ema50": ema50,"ema200": ema200,"bb_up": bb_up,"bb_low": bb_low,"macd": macd,"macd_signal": macd_sig,"vol_ratio": round(vol_ratio,2),"adx": round(adx,0),"atr": round(atr,2),"sl": sl,"tp": tp,"reasons": reasons[:4],"bullish": int(bull_pct),"bearish": int(100-bull_pct)}

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

def send_push_to_all(title, body, url="/app?v=8"):
    subs = load_subs()
    if not subs: return {"sent":0, "error":"nessun iscritto"}
    try:
        from pywebpush import webpush
        sent=0; errors=[]
        for sub in subs:
            try:
                webpush(subscription_info=sub, data=json.dumps({"title": title, "body": body, "url": url}), vapid_private_key=VAPID_PRIVATE, vapid_claims={"sub": VAPID_SUBJECT})
                sent+=1
            except Exception as e:
                errors.append(str(e)[:200])
        return {"sent":sent, "errors": errors, "total": len(subs)}
    except ImportError as e:
        return {"sent":0, "error": f"pywebpush non installato: {e}", "total": len(subs)}
    except Exception as e:
        return {"sent":0, "error": str(e)[:500], "total": len(subs)}

@app.route("/api/ping")
def ping(): 
    subs = load_subs()
    return jsonify({"ok":True,"msg":"V8 WINRATE CHART PAPER","time":rome_now().isoformat(),"subs": len(subs)})

@app.route("/api/signals")
def signals():
    tf = request.args.get("tf","5m")
    sens = int(request.args.get("sens","55"))
    live_prices = binance_fast_price()
    if not live_prices: live_prices = kraken_fast_price_fallback()
    source_name = "Binance" if live_prices else "Kraken"
    coins_data = {}
    for coin in ["BTC","ETH","ORO"]:
        ohlc = get_ohlc(coin, tf); live = live_prices.get(coin)
        if ohlc:
            computed = compute_from_ohlc(ohlc, live_price=live, sens=sens)
            coins_data[coin] = {"symbol": f"{coin}USD","price": computed["price"],"rsi": computed["rsi"],"signal": computed["signal"],"conf": computed["conf"],"trend": computed["trend"],"tf": tf,"ema50": computed["ema50"],"ema200": computed["ema200"],"bb_up": computed["bb_up"],"bb_low": computed["bb_low"],"macd": computed["macd"],"macd_signal": computed["macd_signal"],"vol_ratio": computed["vol_ratio"],"adx": computed["adx"],"atr": computed["atr"],"sl": computed["sl"],"tp": computed["tp"],"reasons": computed["reasons"],"bullish": computed["bullish"],"bearish": computed["bearish"]}
        else:
            price = live if live else (63090 if coin=="BTC" else 1881 if coin=="ETH" else 4382)
            coins_data[coin] = {"symbol": f"{coin}USD","price": price,"rsi": 50.0,"signal": "FERMO","conf": 50,"trend": "Caricamento","tf": tf,"ema50": price*0.99,"ema200": price*0.98,"bb_up": price*1.02,"bb_low": price*0.98,"macd": 0,"macd_signal": 0,"vol_ratio": 1.0,"adx": 20,"atr": price*0.02,"sl": price*0.99,"tp": price*1.01,"reasons": ["OHLC in caricamento..."],"bullish": 50,"bearish": 50}
    max_conf=0; globale="FERMO"
    for v in coins_data.values():
        if v["signal"] in ("COMPRA","VENDI") and v["conf"]>max_conf: max_conf=v["conf"]; globale=v["signal"]
    if max_conf==0:
        for v in coins_data.values():
            if v["conf"]>max_conf: max_conf=v["conf"]; globale=v["signal"]
    btc_price = coins_data["BTC"]["price"]
    return jsonify({"coins": coins_data,"globale": globale,"tf": tf,"updated": rome_now().strftime("%H:%M:%S"),"source": f"{source_name} V8 TF {tf} BTC ${btc_price:.2f} • Roma {rome_now().strftime('%H:%M')}"})

@app.route("/api/history")
def history():
    sens = int(request.args.get("sens","55"))
    live = binance_fast_price()
    if not live: live = kraken_fast_price_fallback()
    all_signals = []
    tfs_to_check = ["5m","15m","1H","4H","1D"]
    for tf in tfs_to_check:
        for coin in ["BTC","ETH","ORO"]:
            ohlc = get_ohlc(coin, tf)
            if not ohlc: continue
            comp = compute_from_ohlc(ohlc, live.get(coin), sens=sens)
            if comp["signal"] in ("COMPRA","VENDI") and comp["conf"] >= sens:
                all_signals.append({"coin": coin,"tf": tf,"signal": comp["signal"],"conf": comp["conf"],"rsi": comp["rsi"],"price": comp["price"],"time": f"{tf} • {rome_now().strftime('%H:%M')}","adx": comp["adx"],"reasons": comp["reasons"]})
    all_signals.sort(key=lambda x: x["conf"], reverse=True)
    return jsonify(all_signals[:20])

@app.route("/api/backtest")
def backtest():
    coin = request.args.get("coin","BTC")
    tf = request.args.get("tf","5m")
    sens = int(request.args.get("sens","55"))
    ohlc = get_ohlc(coin, tf)
    if not ohlc or len(ohlc) < 100:
        return jsonify({"ok":False, "error":"OHLC insufficiente"})
    # usa ultimi 50 segnali
    results=[]
    wins=0; total=0
    # scorri storico
    for i in range(50, len(ohlc)-2):
        slice_ohlc = ohlc[:i+1]
        comp = compute_from_ohlc(slice_ohlc, sens=sens)
        if comp["signal"] not in ("COMPRA","VENDI"): continue
        if comp["conf"] < sens: continue
        entry = float(ohlc[i][4])
        next_close = float(ohlc[i+1][4])
        next_next = float(ohlc[i+2][4]) if i+2 < len(ohlc) else next_close
        # win se prezzo va nella direzione entro 2 candele
        if comp["signal"] == "COMPRA":
            win = next_next > entry
        else:
            win = next_next < entry
        total+=1
        if win: wins+=1
        results.append({"entry": entry, "next": next_close, "signal": comp["signal"], "win": win, "conf": comp["conf"]})
        if len(results) >= 20: 
            # prendi ultimi 20 ma scorri da fine
            pass
    # prendi ultimi 20 risultati (più recenti)
    last20 = results[-20:] if len(results)>=20 else results
    win_rate = (wins/total*100) if total else 0
    last20_win = (sum(1 for r in last20 if r["win"])/len(last20)*100) if last20 else 0
    return jsonify({"ok":True, "coin":coin, "tf":tf, "sens":sens, "total_signals": total, "wins": wins, "win_rate": round(win_rate,1), "last20_win": round(last20_win,1), "last20": last20[::-1][:10]})

@app.route("/api/chart")
def chart_data():
    coin = request.args.get("coin","BTC")
    tf = request.args.get("tf","5m")
    ohlc = get_ohlc(coin, tf)
    if not ohlc:
        return jsonify({"ok":False})
    # ultimi 100 candele per grafico
    data=[]
    for c in ohlc[-100:]:
        data.append({"time": int(c[0]), "open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4])})
    live = binance_fast_price()
    if live.get(coin):
        # aggiorna ultima
        if data:
            data[-1]["close"] = live[coin]
    return jsonify({"ok":True, "data": data})

@app.route("/api/push/subscribe", methods=["POST"])
def sub():
    try:
        data = request.get_json(force=True)
        subs = load_subs()
        ep = data.get("endpoint","")
        subs = [s for s in subs if s.get("endpoint")!=ep]
        subs.append(data)
        save_subs(subs)
        return jsonify({"ok":True,"total":len(subs)})
    except Exception as e:
        return jsonify({"ok":False,"error": str(e)}), 500

@app.route("/api/push/clear", methods=["POST"])
def clear_subs():
    save_subs([])
    if os.path.exists(LAST_SIGNALS_FILE):
        try: os.remove(LAST_SIGNALS_FILE)
        except: pass
    return jsonify({"ok":True,"total":0})

@app.route("/api/push/test", methods=["POST"])
def testp():
    subs = load_subs()
    title = f"🔔 Test FIX V8"
    body = f"PUSH OK! {len(subs)} iscritti - Roma {rome_now().strftime('%H:%M')}"
    result = send_push_to_all(title, body)
    return jsonify({"ok": True, "result": result, "subs": len(subs)})

@app.route("/api/cron/check", methods=["GET","POST"])
def cron_check():
    sens = int(request.args.get("sens","55"))
    live = binance_fast_price()
    if not live: live = kraken_fast_price_fallback()
    last = load_last()
    new_signals = []
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
    save_last(last)
    sent_total = 0
    for sig in new_signals:
        title = f"{'🟢' if sig['signal']=='COMPRA' else '🔴'} {sig['coin']} {sig['signal']} {sig['conf']}% {sig['tf']}"
        body = f"{sig['coin']} ${sig['price']:.2f} Roma {rome_now().strftime('%H:%M')}"
        r = send_push_to_all(title, body, url=f"/app?v=8&tf={sig['tf']}&coin={sig['coin']}")
        sent_total+=r.get("sent",0)
    return jsonify({"ok": True, "new_signals": new_signals, "sent": sent_total, "subs": len(load_subs()), "time": rome_now().isoformat()})

@app.route("/sw.js")
def sw():
    return Response("""
self.addEventListener('push', function(e) {
  let data = {};
  try { data = e.data.json(); } catch { data = {title: 'Vendi PRO', body: e.data.text()} }
  const title = data.title || 'Vendi PRO V8';
  const options = {
    body: data.body || 'Nuovo segnale!',
    icon: 'https://cdn-icons-png.flaticon.com/512/6001/6001527.png',
    badge: 'https://cdn-icons-png.flaticon.com/512/6001/6001527.png',
    data: {url: data.url || '/app?v=8'},
    vibrate: [200,100,200]
  };
  e.waitUntil(self.registration.showNotification(title, options));
});
self.addEventListener('notificationclick', function(e) {
  e.notification.close();
  const url = e.notification.data.url || '/app?v=8';
  e.waitUntil(clients.openWindow(url));
});
""", mimetype="application/javascript")

@app.route("/")
@app.route("/app")
def app_page():
    return f"""
<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Vendi PRO V8 WINRATE+CHART+PAPER</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{{font-family:'Inter',sans-serif;box-sizing:border-box;margin:0;padding:0}}
body{{background:#f8fafc;min-height:100vh;padding:12px 12px 120px}}
.header{{background:linear-gradient(135deg,#0f172a 0%,#3b82f6 100%);border-radius:20px;padding:14px;color:white;display:flex;justify-content:space-between;align-items:center}}
.logo{{width:40px;height:40px;background:rgba(255,255,255,.15);border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800}}
.tfs{{display:flex;gap:5px;margin:10px 0;overflow-x:auto}}
.tfs button{{border:none;background:white;padding:8px 12px;border-radius:999px;font-weight:700;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.tfs button.active{{background:#0f172a;color:white}}
.sens{{display:flex;gap:6px;margin:8px 0}}
.sens button{{border:1px solid #e2e8f0;background:white;padding:6px 10px;border-radius:999px;font-weight:700;font-size:11px}}
.sens button.active{{background:#3b82f6;color:white;border-color:#3b82f6}}
.coin-card{{background:white;border-radius:18px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.05);border:1px solid #f1f5f9;margin-top:10px}}
.coin-row{{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-bottom:1px solid #f8fafc;cursor:pointer}}
.coin-icon{{width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:700;color:white;font-size:13px}}
.btc{{background:linear-gradient(135deg,#f59e0b,#f97316)}}.eth{{background:linear-gradient(135deg,#6366f1,#8b5cf6)}}.oro{{background:linear-gradient(135deg,#eab308,#ca8a04)}}
.badge{{padding:4px 8px;border-radius:999px;font-weight:800;font-size:10px}}
.FERMO-bg{{background:#fef3c7;color:#92400e}}.COMPRA-bg{{background:#dcfce7;color:#166534}}.VENDI-bg{{background:#fee2e2;color:#991b1b}}
.paper-bar{{background:#0f172a;color:white;border-radius:14px;padding:10px 12px;margin-top:10px;display:flex;justify-content:space-between;align-items:center;font-size:12px}}
.fab{{position:fixed;bottom:12px;left:10px;right:10px;display:flex;gap:6px;z-index:20}}
.fab button{{flex:1;padding:10px;border-radius:14px;border:none;font-weight:700;box-shadow:0 8px 20px rgba(0,0,0,.15);font-size:11px}}
.btn-dark{{background:#0f172a;color:white}}.btn-light{{background:white;color:#0f172a;border:1px solid #e2e8f0!important}}.btn-blue{{background:#3b82f6;color:white}}
#modal{{position:fixed;inset:0;background:rgba(15,23,42,.75);backdrop-filter:blur(12px);display:none;align-items:end;justify-content:center;z-index:50;padding:8px}}
#modal.show{{display:flex}}
.modal-box{{background:white;width:100%;max-width:560px;border-radius:20px;padding:14px;max-height:94vh;overflow:auto}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:8px 0}}
.reason{{display:inline-block;background:#f1f5f9;padding:3px 6px;border-radius:6px;font-size:9px;margin:2px}}
.hist-item{{display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid #f1f5f9;font-size:12px}}
.empty-hist{{padding:16px;text-align:center;color:#64748b;font-size:12px}}
.chart-wrap{{background:#0f172a;border-radius:12px;padding:8px;margin:8px 0}}
.win-badge{{display:inline-block;padding:4px 8px;border-radius:999px;font-weight:800;font-size:11px;margin-left:6px}}
.win-high{{background:#dcfce7;color:#166534}}.win-mid{{background:#fef3c7;color:#92400e}}.win-low{{background:#fee2e2;color:#991b1b}}
</style>
</head><body>
<div class="header"><div style="display:flex;gap:10px;align-items:center"><div class="logo">V8</div><div><b>Vendi PRO V8</b><br><small>WinRate + Grafico + Paper 1€</small><br><small id=subStatus>Push: verifica...</small></div></div><div>📊</div></div>

<div class="paper-bar" id=paperBar>
<div><b>💰 Paper Trading</b><br><span id=paperBalance>Saldo: €10.00 virtuale</span><br><span id=paperPNL style="font-size:10px;color:#94a3b8">P/L: €0.00 (0 trade)</span></div>
<div style="text-align:right"><button onclick="resetPaper()" style="background:rgba(255,255,255,.15);border:none;color:white;padding:6px 10px;border-radius:8px;font-size:10px">Reset</button><br><small style="font-size:9px;color:#94a3b8">Simula con 1€</small></div>
</div>

<div class="tfs">
<button onclick="loadTF('5m')" id=b5m class=active>5m ⚡</button>
<button onclick="loadTF('15m')" id=b15m>15m ⚡</button>
<button onclick="loadTF('1H')" id=b1H>1H</button>
<button onclick="loadTF('4H')" id=b4H>4H</button>
<button onclick="loadTF('1D')" id=b1D>1D</button>
</div>
<div class="sens">
<button onclick="setSens(55)" id=s55 class=active>SCALPER 55%</button>
<button onclick="setSens(60)" id=s60>PRO 60%</button>
<button onclick="setSens(65)" id=s65>ULTRA 65%</button>
</div>
<div class="coin-card"><div style="display:flex;justify-content:space-between;padding:12px"><div><small style="color:#64748b">GLOBALE</small><div id=globale style="font-weight:800;color:#dc2626;font-size:18px">...</div><small id=globaleSub style="color:#64748b"></small></div><div style="text-align:right"><small style="color:#64748b">AGGIORNATO</small><div id=agg style="font-weight:800">--</div><small id=srcInfo style="color:#3b82f6;font-size:10px"></small></div></div></div>
<div class="coin-card" id=coins>Caricamento V8...</div>
<div class="coin-card" style="padding:12px;margin-top:12px"><div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer" onclick="toggleHist()"><div><b>📜 Storico REAL >55%</b><br><small style="color:#64748b" id=histSub>TAP per aprire</small></div><div id=histArrow>▼</div></div><div id=histList style="display:none;margin-top:8px"></div></div>

<div class="coin-card" style="padding:10px;margin-top:10px;background:#eff6ff;border:1px solid #bfdbfe"><b>ℹ️ Novità V8</b><br><small style="color:#1e40af">• WinRate: vedi se il segnale funziona davvero<br>• Grafico live dentro l'app<br>• Paper trading: prova con €1 finto senza perdere nulla</small><br><small id=cronInfo style="color:#64748b"></small></div>

<div class="fab"><button class="btn-light" onclick="testPush()">🔔 Test</button><button class="btn-blue" onclick="subscribePush()">📢 Push</button><button class="btn-dark" onclick="openPaperModal()">💰 Paper</button></div>

<div id=modal><div class="modal-box">
<div style="display:flex;justify-content:space-between;align-items:center"><div><b id=mCoin>BTC</b> <span id=mWinRate></span></div><span onclick="closeModal()" style="cursor:pointer;font-size:20px">✕</span></div>
<small id=mPrice style="color:#64748b"></small>

<div class="chart-wrap"><div id=chart style="height:180px"></div><small id=chartInfo style="color:#94a3b8;font-size:10px">Grafico live Kraken + Binance price</small></div>

<div class="grid2" style="margin-top:8px">
<div style="background:#f8fafc;padding:8px;border-radius:10px;text-align:center"><small>SEGNALE</small><div id=mSignal style="font-weight:800"></div></div>
<div style="background:#f8fafc;padding:8px;border-radius:10px;text-align:center"><small>AFFID.</small><div id=mConf style="font-weight:800"></div></div>
<div style="background:#f8fafc;padding:8px;border-radius:10px;text-align:center"><small>RSI</small><div id=mRsi></div></div>
<div style="background:#f8fafc;padding:8px;border-radius:10px;text-align:center"><small>ADX / VOL</small><div id=mAdx></div></div>
</div>
<div class="grid2">
<div style="background:#f8fafc;padding:8px;border-radius:10px"><small>EMA 50/200</small><div id=mEma style="font-size:11px"></div><small id=mEmaDetail style="color:#64748b"></small></div>
<div style="background:#f8fafc;padding:8px;border-radius:10px"><small>BB / MACD</small><div id=mBb style="font-size:11px"></div><div id=mMacd style="font-size:10px;color:#64748b"></div></div>
</div>
<div class="grid2">
<div style="background:#f8fafc;padding:8px;border-radius:10px"><small>ENTRY</small><div id=mEntry style="font-weight:700"></div></div>
<div style="background:#f8fafc;padding:8px;border-radius:10px"><small>SL / TP</small><div style="font-size:11px"><span id=mSL></span> / <span id=mTP></span></div></div>
</div>
<div><small style="font-weight:700;font-size:11px">Perché:</small><div id=mReasons style="margin-top:4px"></div></div>

<div id=mBacktest style="margin-top:8px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:8px;font-size:11px"></div>

<div style="display:flex;gap:6px;margin-top:10px">
<button onclick="paperTrade('buy')" style="flex:1;padding:10px;border-radius:10px;border:none;background:#dcfce7;color:#166534;font-weight:700">💰 Compra 1€ finto</button>
<button onclick="paperTrade('sell')" style="flex:1;padding:10px;border-radius:10px;border:none;background:#fee2e2;color:#991b1b;font-weight:700">💰 Vendi 1€ finto</button>
</div>
<button onclick="openChart()" style="margin-top:8px;width:100%;padding:9px;border-radius:10px;border:none;background:#0f172a;color:white;font-weight:700;font-size:12px">📈 Apri su TradingView</button>
</div></div>

<script>
let curTF='5m', curSens=55, lastData=null, currentDetail=null, chart=null, candleSeries=null;
const VAPID_PUBLIC_KEY="{VAPID_PUBLIC}";
function urlBase64ToUint8Array(b64){{const p='='.repeat((4-b64.length%4)%4);const base64=(b64+p).replace(/-/g,'+').replace(/_/g,'/');const raw=atob(base64);return Uint8Array.from([...raw].map(c=>c.charCodeAt(0)));}}

function getPaper(){{
  try{{ return JSON.parse(localStorage.getItem('paper_v8')||'{{"balance":10,"trades":[],"pnl":0}}'); }}catch{{ return {{"balance":10,"trades":[],"pnl":0}}; }}
}}
function savePaper(p){{ localStorage.setItem('paper_v8', JSON.stringify(p)); updatePaperBar(); }}
function updatePaperBar(){{
  const p=getPaper();
  document.getElementById('paperBalance').innerText='Saldo: €'+p.balance.toFixed(2)+' virtuale';
  const total=p.trades.length;
  document.getElementById('paperPNL').innerText=`P/L: €${{p.pnl.toFixed(2)}} (${{total}} trade)`;
}}
function resetPaper(){{
  if(confirm('Azzerare paper trading?')){{ savePaper({{"balance":10,"trades":[],"pnl":0}}); alert('Azzerato a €10'); }}
}}
function paperTrade(side){{
  if(!currentDetail||!lastData) return;
  const info=lastData.coins[currentDetail];
  const p=getPaper();
  if(p.balance < 1){{ alert('Saldo finito! Resetta'); return; }}
  const trade={{coin:currentDetail, side: side==='buy'?'COMPRA':'VENDI', entry: info.price, time: new Date().toLocaleTimeString(), tf: curTF, conf: info.conf}};
  p.trades.unshift(trade);
  // simula chiusura dopo 2 candele - per ora tiene aperto, PnL finto 0 fino a chiusura manuale futura
  // per semplicità aggiungiamo trade e basta, PnL lo calcoliamo dopo se vuoi
  p.balance -= 1;
  // aggiungi trade log
  savePaper(p);
  alert(`✅ Paper ${{trade.side}} ${{currentDetail}} a $${{info.price.toFixed(2)}} con 1€ finto. Ti restano €${{p.balance.toFixed(2)}}`);
}}
function openPaperModal(){{
  const p=getPaper();
  let html=p.trades.slice(0,10).map(t=>`<div style="display:flex;justify-content:space-between;font-size:11px;padding:6px;border-bottom:1px solid #f1f5f9"><span><b>${{t.coin}}</b> ${{t.side}} ${{t.conf}}% ${{t.tf}}</span><span>$${{t.entry.toFixed(0)}} ${{t.time}}</span></div>`).join('');
  if(!html) html='<div style="padding:10px;color:#64748b;font-size:12px">Nessun trade finto ancora - apri un dettaglio e clicca Compra 1€ finto</div>';
  document.getElementById('histList').innerHTML='<b>💰 Paper Trading (ultimi 10)</b>'+html;
  document.getElementById('histList').style.display='block';
  document.getElementById('histArrow').innerText='▲';
}}

async function subscribePush(){{
  try{{
    const reg=await navigator.serviceWorker.register('/sw.js');
    await new Promise(r=>setTimeout(r,400));
    let ex=await reg.pushManager.getSubscription(); if(ex){{try{{await ex.unsubscribe();}}catch{{}}}}
    const perm=await Notification.requestPermission(); if(perm!=='granted'){{alert('Permesso negato');return;}}
    const sub=await reg.pushManager.subscribe({{userVisibleOnly:true, applicationServerKey:urlBase64ToUint8Array(VAPID_PUBLIC_KEY)}});
    const res=await fetch('/api/push/subscribe',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(sub)}});
    const j=await res.json();
    document.getElementById('subStatus').innerText='Push: ATTIVO ✅ '+j.total;
    alert('✅ Push attive');
  }}catch(e){{alert(e.message);}}
}}
async function testPush(){{
  const r=await fetch('/api/push/test',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{}})}});
  const j=await r.json();
  alert('Test inviato a '+j.result.sent+' - '+JSON.stringify(j.result).slice(0,200));
}}

function colorFor(s){{return s=='COMPRA'?'#16a34a':s=='VENDI'?'#dc2626':'#d97706'}}
function bgFor(s){{return s=='COMPRA'?'COMPRA-bg':s=='VENDI'?'VENDI-bg':'FERMO-bg'}}

function setSens(v){{
  curSens=v;
  document.querySelectorAll('.sens button').forEach(b=>b.classList.remove('active'));
  document.getElementById('s'+v).classList.add('active');
  loadTF(curTF);
}}

async function loadTF(tf){{
  curTF=tf;
  document.querySelectorAll('.tfs button').forEach(b=>b.classList.remove('active')); const el=document.getElementById('b'+tf); if(el) el.classList.add('active');
  document.getElementById('coins').innerHTML='<div style="padding:20px;text-align:center;color:#64748b">⏳ Carico V8 '+curSens+'% '+tf+'...</div>';
  try{{
    const res=await fetch('/api/signals?tf='+tf+'&sens='+curSens); const d=await res.json(); lastData=d;
    document.getElementById('globale').innerText=d.globale||'...'; document.getElementById('globale').style.color=colorFor(d.globale);
    document.getElementById('globaleSub').innerText=(d.globale||'')+' • TF '+tf+' • V8 '+curSens+'%'; document.getElementById('agg').innerText=d.updated||'--'; document.getElementById('srcInfo').innerText=d.source||'';
    let html='';
    for(let [name,info] of Object.entries(d.coins)){{
      const icon=name=='BTC'?'btc':name=='ETH'?'eth':'oro'; const ico=name=='BTC'?'₿':name=='ETH'?'Ξ':'Au';
      html+=`<div class=coin-row onclick="openDetails('${{name}}')"><div style="display:flex;gap:8px;align-items:center"><div class="coin-icon ${{icon}}">${{ico}}</div><div><b>${{name}} <span style="font-size:9px;color:#64748b">ADX ${{info.adx.toFixed(0)}}</span></b><div style="font-size:10px;color:#64748b">RSI ${{info.rsi.toFixed(1)}} • ${{info.trend}} • TF ${{tf}}</div><div style="font-size:9px;color:#94a3b8">${{info.reasons.slice(0,2).join(' • ')}}</div></div></div><div style="text-align:right"><span class="badge ${{bgFor(info.signal)}}">${{info.signal}} ${{info.conf}}%</span><div style="font-weight:800;margin-top:2px;font-size:12px">$${{info.price.toFixed(2)}}</div><div style="font-size:9px;color:#94a3b8">TAP grafico</div></div></div>`;
    }}
    document.getElementById('coins').innerHTML=html;
    loadHistGlobal();
  }}catch(e){{document.getElementById('coins').innerHTML='<div style="padding:20px;color:#dc2626">Errore: '+e.message+'</div>';}}
}}
async function loadHistGlobal(){{
  try{{
    const r=await fetch('/api/history?sens='+curSens); const list=await r.json(); const c=document.getElementById('histList');
    if(list.length===0){{c.innerHTML='<div class=empty-hist>😴 Nessun segnale >'+curSens+'% ora</div>';}}
    else {{c.innerHTML=list.map(h=>`<div class=hist-item><div><b>${{h.coin}}</b> <span style="padding:2px 5px;border-radius:999px;font-size:9px;font-weight:700;background:${{h.signal=='COMPRA'?'#dcfce7':'#fee2e2'}};color:${{h.signal=='COMPRA'?'#16a34a':'#dc2626'}}">${{h.signal}} ${{h.conf}}%</span> <small>${{h.tf}}</small> RSI ${{h.rsi}}</div><div style="text-align:right"><div>$${{h.price.toFixed(0)}}</div><div style="font-size:9px;color:#94a3b8">${{h.time}}</div></div></div>`).join('');}}
  }}catch(e){{}}
}}
function toggleHist(){{const l=document.getElementById('histList');const a=document.getElementById('histArrow'); if(l.style.display=='none'||l.style.display==''){{l.style.display='block';a.innerText='▲';loadHistGlobal();}}else{{l.style.display='none';a.innerText='▼';}}}}

async function openDetails(coin){{
  try{{
    if(!lastData) return; const info=lastData.coins[coin]; if(!info) return; currentDetail=coin;
    document.getElementById('mCoin').innerText=coin+' • '+info.symbol+' • TF '+curTF+' V8';
    document.getElementById('mPrice').innerText='$'+info.price.toFixed(2)+' • '+info.trend;
    document.getElementById('mSignal').innerText=info.signal; document.getElementById('mSignal').style.color=colorFor(info.signal);
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
    document.getElementById('mReasons').innerHTML=info.reasons.map(r=>`<span class=reason>${{r}}</span>`).join(' ');
    document.getElementById('modal').classList.add('show');
    loadChart(coin, curTF);
    loadBacktest(coin, curTF);
  }}catch(e){{alert('Errore: '+e.message);}}
}}

async function loadChart(coin, tf){{
  try{{
    const r=await fetch('/api/chart?coin='+coin+'&tf='+tf);
    const j=await r.json();
    if(!j.ok) return;
    const chartEl=document.getElementById('chart');
    chartEl.innerHTML='';
    const c=LightweightCharts.createChart(chartEl, {{width: chartEl.clientWidth, height:180, layout:{{background:{{color:'#0f172a'}}, textColor:'#94a3b8'}}, grid:{{vertLines:{{color:'#1e293b'}}, horzLines:{{color:'#1e293b'}}}}, timeScale:{{timeVisible:true}} }});
    const series=c.addCandlestickSeries();
    const data=j.data.map(d=>({{time: d.time, open:d.open, high:d.high, low:d.low, close:d.close}}));
    series.setData(data);
    c.timeScale().fitContent();
    chart=c; candleSeries=series;
  }}catch(e){{}}
}}
async function loadBacktest(coin, tf){{
  try{{
    const r=await fetch('/api/backtest?coin='+coin+'&tf='+tf+'&sens='+curSens);
    const j=await r.json();
    const el=document.getElementById('mBacktest');
    const wr=j.win_rate||0;
    const last20=j.last20_win||0;
    const cls = last20>=60?'win-high':last20>=50?'win-mid':'win-low';
    el.innerHTML=`<b>📊 WinRate Backtest</b> <span class="win-badge ${{cls}}">${{last20}}% ultimi 20</span><br><small>Totale: ${{j.wins||0}}/${{j.total_signals||0}} vinti (${{wr}}%) su ${{tf}} • Ultimi segnali verificati su candele reali Kraken</small><div style="margin-top:4px">${{(j.last20||[]).slice(0,5).map(x=>`<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${{x.win?'#22c55e':'#ef4444'}};margin-right:3px"></span>`).join('')}} <small style="color:#64748b">verde=win rosso=loss</small></div>`;
    document.getElementById('mWinRate').innerHTML=`<span class="win-badge ${{cls}}">${{last20}}% win ultimi 20</span>`;
  }}catch(e){{}}
}}

function closeModal(){{document.getElementById('modal').classList.remove('show')}}
function openChart(){{if(!currentDetail)return;const map={{BTC:'BINANCE:BTCUSDT',ETH:'BINANCE:ETHUSDT',ORO:'BINANCE:PAXGUSDT'}};window.open('https://www.tradingview.com/chart/?symbol='+map[currentDetail]+'&interval='+curTF,'_blank');}}
loadTF('5m'); setInterval(()=>loadTF(curTF),30000);
updatePaperBar();
if('serviceWorker' in navigator){{navigator.serviceWorker.register('/sw.js').then(()=>{{fetch('/api/ping').then(r=>r.json()).then(j=>{{document.getElementById('subStatus').innerText='Push: '+j.subs+' iscritti - V8 '+j.time.slice(11,16)}})}});}}
</script>
</body></html>
"""
if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
