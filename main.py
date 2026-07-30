"""
CryptoAlertBot V9.2 KRAKEN - EURO REALI = TradingView
- Fonte: Kraken (stessi valori TradingView)
- Coppie: BTCEUR / ETHEUR / SOLEUR in euro veri
- Storico 14gg, VOL, RSI, 1m e 5m
- FIX: Allineamento orologio 00,05,10 per candele perfette
- NESSUN errore 451 su Render
"""

import os
import threading
from flask import Flask

# Mini server per tenere vivo Render (fix 503)
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot Kraken EUR 14gg is running - OK"

@app.route('/health')
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

import time
import requests
from statistics import mean
from datetime import datetime, timedelta

# ================= CONFIG =================
TELEGRAM_TOKEN = "8929501488:AAHOiVk16EjOVefpLRLVYRQgxdeBgzctxkY"
CHAT_ID = "423945798"

GIORNI_STORICO = 14
SYMBOLS = ["BTCEUR", "ETHEUR", "SOLEUR"]  # Euro veri Kraken
KRAKEN_URL = "https://api.kraken.com/0/public/OHLC"
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

storico_cache = {}
CACHE_TTL = 3600

# Mappatura nomi Kraken (accetta sia XXBTZEUR che BTCEUR)
KRAKEN_PAIRS = {
    "BTCEUR": "XXBTZEUR",
    "ETHEUR": "XETHZEUR",
    "SOLEUR": "SOLEUR"
}

def get_klines_kraken(symbol, interval_str, limit=720):
    """Prende candele da Kraken. interval_str = '1m' o '5m' """
    pair = KRAKEN_PAIRS.get(symbol, symbol)
    interval = 1 if interval_str == "1m" else 5

    params = {"pair": pair, "interval": interval}
    try:
        r = requests.get(KRAKEN_URL, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("error") and len(data["error"]) > 0:
            print(f"Errore Kraken {symbol}: {data['error']}")
            return []
        # Kraken ritorna dict con chiave nome pair
        result = data.get("result", {})
        # la prima chiave che non e' 'last'
        klines = []
        for k, v in result.items():
            if k != "last":
                klines = v
                break
        # Formato Kraken: [time, open, high, low, close, vwap, volume, count]
        # Convertiamo in formato simile Binance: [time, open, high, low, close, volume]
        converted = []
        for c in klines:
            # [0]=time, [1]=open, [2]=high, [3]=low, [4]=close, [6]=volume
            converted.append([c[0]*1000, c[1], c[2], c[3], c[4], c[6]])
        return converted[-limit:]
    except Exception as e:
        print(f"Errore klines {symbol} {interval_str}: {e}")
        return []

def fetch_storico_kraken(symbol, interval_str, giorni=GIORNI_STORICO):
    cache_key = f"{symbol}_{interval_str}_{giorni}"
    now = time.time()
    if cache_key in storico_cache:
        data, ts = storico_cache[cache_key]
        if now - ts < CACHE_TTL:
            return data

    print(f"Scarico {giorni}gg Kraken per {symbol} {interval_str}...")
    tutto = []
    pair = KRAKEN_PAIRS.get(symbol, symbol)
    interval = 1 if interval_str == "1m" else 5
    candele_giorno = 1440 if interval_str == "1m" else 288
    tot_candele = giorni * candele_giorno

    since = int(now - giorni*24*3600)

    while len(tutto) < tot_candele:
        params = {"pair": pair, "interval": interval, "since": since}
        try:
            r = requests.get(KRAKEN_URL, params=params, timeout=15)
            data = r.json()
            if data.get("error") and len(data["error"]) > 0:
                break
            result = data.get("result", {})
            klines = []
            last_ts = None
            for k, v in result.items():
                if k == "last":
                    last_ts = v
                else:
                    klines = v
            if not klines:
                break
            conv = [[c[0]*1000, c[1], c[2], c[3], c[4], c[6]] for c in klines]
            tutto.extend(conv)
            if last_ts is None:
                break
            since = int(last_ts)
            if len(klines) < 100:
                break
            time.sleep(0.5)
        except Exception as e:
            print(f"Errore storico {symbol}: {e}")
            break

    tutto = sorted(tutto, key=lambda x: x[0])[-tot_candele:]
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

    up = len([x for x in simili if x > 0.05])
    down = len([x for x in simili if x < -0.05])
    flat = len(simili) - up - down
    pct_up = up/len(simili)*100
    pct_down = down/len(simili)*100
    pct_flat = flat/len(simili)*100

    if pct_up >= 60:
        segnale = "🟢 SALE"
    elif pct_down >= 60:
        segnale = "🔻 SCENDE"
    elif pct_flat >= 50:
        segnale = "➡️ FLAT"
    else:
        segnale = "🔀 INCERTO"

    base = f"Storico {giorni}gg ({len(simili)} casi simili): {media:+.2f}% medio dopo {minuti_dopo}m | {sopra/len(simili)*100:.0f}% sopra | "
    extra = f"{segnale} {pct_up:.0f}%↑ {pct_down:.0f}%↓ {pct_flat:.0f}%→"
    return base + extra

def genera_messaggio(interval):
    now_str = datetime.now().strftime("%H:%M:%S")
    msg = f"⏱️ AGGIORNAMENTO {interval} - {now_str} (Kraken EUR)\n"
    for sym in SYMBOLS:
        klines_now = get_klines_kraken(sym, interval, 50)
        if len(klines_now) < 10:
            continue
        prezzo = float(klines_now[-1][4])
        var_pct = (prezzo - float(klines_now[-6][4]))/float(klines_now[-6][4])*100
        trend = get_trend(klines_now)
        rsi = calc_rsi(klines_now)
        rsi_lbl = get_rsi_label(rsi)
        vol = get_vol_label(klines_now)
        klines_lunghi = fetch_storico_kraken(sym, interval, GIORNI_STORICO)
        storico_txt = get_storico_stats(klines_lunghi, rsi, vol, 5, GIORNI_STORICO, interval)
        nome = sym.replace("EUR", "")
        msg += f"\n{nome}: {prezzo:,.2f}€ ({var_pct:+.2f}%) ➡️ {trend} | {vol} | RSI {rsi:.1f} {rsi_lbl}\n"
        msg += f"  └─ 📊 {storico_txt}\n\n"
    return msg

def send_telegram(text):
    if "INSERT" in TELEGRAM_TOKEN:
        print(text)
        print("\n--- TEST MODE ---\n")
        return
    try:
        requests.post(TELEGRAM_URL, json={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        print(f"Errore Telegram: {e}")

if __name__ == "__main__":
    print(f"CryptoAlertBot V9.2 KRAKEN EUR avviato - STORICO {GIORNI_STORICO}gg")
    print("Allineamento orologio attivo: 1m ogni minuto :05, 5m ogni 5 minuti")

    def aspetta_prossimo_allineamento():
        ora = datetime.now()
        prossimo = (ora + timedelta(minutes=1)).replace(second=5, microsecond=0)
        attesa = (prossimo - ora).total_seconds()
        if attesa > 0:
            time.sleep(attesa)

    ultimo_5m_inviato = -1

    while True:
        try:
            aspetta_prossimo_allineamento()
            ora = datetime.now()

            msg_1m = genera_messaggio("1m")
            send_telegram(msg_1m)
            print(f"[1m] Inviato alle {ora.strftime('%H:%M:%S')}")

            if ora.minute % 5 == 0 and ora.minute != ultimo_5m_inviato:
                time.sleep(1)
                msg_5m = genera_messaggio("5m")
                send_telegram(msg_5m)
                ultimo_5m_inviato = ora.minute
                print(f"[5m] Inviato alle {ora.strftime('%H:%M:%S')} - 5m")

        except Exception as e:
            print(f"Errore loop: {e}")
            time.sleep(10)
