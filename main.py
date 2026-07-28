"""
CryptoAlertBot V9.1 - VOLUME + STORICO 14 GIORNI
- Mantiene TUTTE le statistiche della foto (prezzo, %, trend, VOL, RSI)
- Aggiunge riga storico su 1m e 5m
- 14 giorni = compromesso ideale tra casi e attualita
SOLO ALERT, NON FA TRADING
"""

import time
import requests
from statistics import mean
from datetime import datetime

# ================= CONFIG =================
TELEGRAM_TOKEN = "INSERISCI_QUI_IL_TUO_TOKEN"
CHAT_ID = "INSERISCI_QUI_CHAT_ID"

GIORNI_STORICO = 14  # <-- Cambia qui se vuoi 7 / 30

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
BINANCE_URL = "https://api.binance.com/api/v3/klines"
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

storico_cache = {}
CACHE_TTL = 3600  # aggiorna storico ogni ora

def get_klines(symbol, interval, limit=1000, end_time=None):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if end_time:
        params["endTime"] = end_time
    try:
        r = requests.get(BINANCE_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Errore klines {symbol} {interval}: {e}")
        return []

def fetch_storico(symbol, interval, giorni=GIORNI_STORICO):
    cache_key = f"{symbol}_{interval}_{giorni}"
    now = time.time()
    if cache_key in storico_cache:
        data, ts = storico_cache[cache_key]
        if now - ts < CACHE_TTL:
            return data
    
    print(f"Scarico {giorni}gg per {symbol} {interval}...")
    tutto = []
    end_time = int(now*1000)
    candele_giorno = 1440 if interval == "1m" else 288
    tot_candele = giorni * candele_giorno
    iterazioni = tot_candele // 1000 + 2
    
    for _ in range(iterazioni):
        batch = get_klines(symbol, interval, 1000, end_time)
        if not batch:
            break
        tutto = batch + tutto
        end_time = int(batch[0][0]) - 1
        time.sleep(0.3)
    
    storico_cache[cache_key] = (tutto, now)
    return tutto

def calc_rsi(klines, period=14):
    closes = [float(k[4]) for k in klines]
    if len(closes) < period+1:
        return 50.0
    gains, losses = [], []
    for i in range(1, period+1):
        diff = closes[-i] - closes[-i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains)/period
    avg_loss = sum(losses)/period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain/avg_loss
    return 100 - (100/(1+rs))

def get_rsi_label(rsi):
    if rsi < 30: return "IPERVENDUTO"
    if rsi > 70: return "IPERCOMPRATO"
    return "NEUTRO"

def get_trend(klines):
    closes = [float(k[4]) for k in klines[-10:]]
    if len(closes) < 2: return "FLAT / STABILE"
    var = (closes[-1]-closes[0])/closes[0]*100
    if var > 0.15: return "RIALZO DEBOLE" if var < 0.5 else "RIALZO"
    if var < -0.15: return "RIBASSO DEBOLE" if var > -0.5 else "RIBASSO"
    return "FLAT / STABILE"

def get_vol_label(klines):
    vols = [float(k[5]) for k in klines[-21:]]
    if len(vols) < 21: return "VOL NORMALE"
    curr = vols[-1]
    avg = mean(vols[:-1])
    if curr < avg*0.5: return "zZ VOL BASSO"
    if curr > avg*2.0: return "VOL ALTO"
    return "VOL NORMALE"

def get_storico_stats(klines_lunghi, rsi_now, vol_now, candele_dopo=5, giorni=GIORNI_STORICO, interval="1m"):
    if len(klines_lunghi) < 200:
        return f"Storico {giorni}gg: in caricamento..."
    simili = []
    for i in range(100, len(klines_lunghi)-candele_dopo-1):
        finestra = klines_lunghi[i-30:i]
        rsi_pass = calc_rsi(finestra)
        vol_pass = get_vol_label(finestra)
        if abs(rsi_pass - rsi_now) < 3.5 and vol_pass == vol_now:
            p_ora = float(klines_lunghi[i][4])
            p_dopo = float(klines_lunghi[i+candele_dopo][4])
            simili.append((p_dopo-p_ora)/p_ora*100)
    
    if len(simili) < 5:
        return f"Storico {giorni}gg ({len(simili)} casi): dati insufficienti"
    
    media = mean(simili)
    sopra = len([x for x in simili if x>0])
    minuti_dopo = candele_dopo if interval=="1m" else candele_dopo*5
    return f"Storico {giorni}gg ({len(simili)} casi simili): {media:+.2f}% medio dopo {minuti_dopo}m | {sopra/len(simili)*100:.0f}% sopra"

def genera_messaggio(interval):
    now_str = datetime.now().strftime("%H:%M:%S")
    msg = f"⏱️ AGGIORNAMENTO {interval} - {now_str}\n"
    for sym in SYMBOLS:
        klines_now = get_klines(sym, interval, 50)
        if len(klines_now) < 10: continue
        prezzo = float(klines_now[-1][4])
        var_pct = (prezzo - float(klines_now[-6][4]))/float(klines_now[-6][4])*100
        trend = get_trend(klines_now)
        rsi = calc_rsi(klines_now)
        rsi_lbl = get_rsi_label(rsi)
        vol = get_vol_label(klines_now)
        klines_lunghi = fetch_storico(sym, interval, GIORNI_STORICO)
        storico_txt = get_storico_stats(klines_lunghi, rsi, vol, 5, GIORNI_STORICO, interval)
        nome = sym.replace("USDT","")
        msg += f"{nome}: {prezzo:,.2f}E ({var_pct:+.2f}%) ➡️ {trend} | {vol} | RSI {rsi:.1f} {rsi_lbl}\n"
        msg += f"  └─ 📊 {storico_txt}\n\n"
    return msg

def send_telegram(text):
    if "INSERISCI" in TELEGRAM_TOKEN:
        print(text)
        print("\n--- TEST MODE ---\n")
        return
    try:
        requests.post(TELEGRAM_URL, json={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        print(f"Errore Telegram: {e}")

if __name__ == "__main__":
    print(f"CryptoAlertBot V9.1 avviato - STORICO {GIORNI_STORICO}gg per 1m e 5m")
    last_5m = 0
    while True:
        try:
            msg_1m = genera_messaggio("1m")
            send_telegram(msg_1m)
            if time.time() - last_5m >= 300:
                time.sleep(2)
                msg_5m = genera_messaggio("5m")
                send_telegram(msg_5m)
                last_5m = time.time()
            time.sleep(60)
        except Exception as e:
            print(f"Errore loop: {e}")
            time.sleep(10)
