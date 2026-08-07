import os, json, base64, time, threading, math
try:
    import requests
    HAS_REQUESTS=True
except:
    HAS_REQUESTS=False
    import urllib.request as _urllib
    import urllib.error as _uerror
from flask import Flask, Response, request, jsonify
from datetime import datetime

app = Flask(__name__)

# --- ICONS (same as before) ---
ICON_192_B64 = "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"
ICON_512_B64 = "iVBORw0KGgoAAAANSUhEUgAAAgAAAAIACAYAAAD0eNT6AAAko0lEQVR4nO3dd5RcZ5nn8d+tuhW6JVnRVrIl2YqWWlayQrdkG9vYOBJsbMYGk1kYDrPMzB6YZWCBBZaBZYblzNk9A8PGIQeHY4NlsMFWd6tbOScrB1vBtrI6VNWtuvuHMNhGkrtbVfXeW8/38w//AH27VXXv733u+zyv94Wmo6EAAIApPk9/AADsSbi+AAAAUH0EAAAADCIAAABgEAEAAACDCAAAABhEAAAAwCA/9FxfAgAAqDYqAAAAGEQAAADAIAIAAAAGEQAAADCIAAAAgEEEAAAADPJFGyAAAOZwHDAAAAbxCgAAAIMIAAAAGEQAAADAIAIAAAAGEQAAADCINkAAAAyiAgAAgEHMAQAAwCAqAAAAGEQAAADAIAIAAAAGEQAAADCINkAAAAyiAgAAgEEEAAAADGIOAAAABlEBAADAIAIAAAAGEQAAADCINkAAAAyiAgAAgEEEAAAADCIAAABgEHMAAAAwiAoAAAAGEQAAADCINkAAAAyiAgAAgEEEAAAADCIAAABgEAEAAACDmAMAAIBBVAAAADCINkAAAAyiAgAAgEEEAAAADCIAAABgEAEAAACDCAAAABjEHAAAAAzy5dEHCACANbwCAADAIAIAAAAGEQAAADCIAAAAgEEEAAAADCIAAABgkB/SBQgAgDlUAAAAMIgAAACAQQQAAAAMIgAAAGAQAQAAAIMIAAAAGMRxwAAAGOSLOQAAAJjDKwAAAAwiAAAAYBABAAAAgwgAAAAYRAAAAMAgAgAAAAZxHDAAAAZRAQAAwCACAAAABhEAAAAwiAAAAIBBBAAAAAwiAAAAYBCnAQIAYJAfur4CAABQdbwCAADAIAIAAAAGEQAAADCIAAAAgEEEAAAADKINEAAAg6gAAABgEHMAAAAwiAoAAAAGEQAAADCIAAAAgEEEAAAADKINEAAAg6gAAABgEAEAAACDmAMAAIBBVAAAADCIAAAAgEEEAAAADOI0QAAADKICAACAQQQAAAAMIgAAAGAQcwAAADCICgAAAAYRAAAAMIg2QAAADKICAACAQQQAAAAMIgAAAGAQAQAAAIOYAwAAgEFUAAAAMIg2QAAADKICAACAQQQAAAAMIgAAAGAQAQAAAIOYAwAAgEFUAAAAMIg2QAAADKICAACAQQQAAAAMIgAAAGAQAQAAAIP8kDZAAADMoQIAAIBBBAAAAAwiAAAAYBABAAAAgwgAAAAYRAAAAMCg/w9rlW5bFORsxQAAAABJRU5ErkJggg=="

# --- VAPID KEYS ---
VAPID_PUBLIC_KEY = "BC2EkkzHG1EPz_akF0s-Fy8CIHFE0Wl6TGWsexqRojEyEh0rjDfKRSqev2HY86U1PBMK2KGnSItpJ_69oKFCshA"
VAPID_PRIVATE_B64 = "DCxSVC_1bZciFroQkmmL6nejqkjSM_cxtPf4CXKN8V8"
VAPID_SUBJECT = "mailto:vendieuro@example.com"

SUBS_FILE = "/tmp/subs.json"
latest_signals = []
prev_signals = {}
subscriptions = []

def load_subs():
    global subscriptions
    try:
        if os.path.exists(SUBS_FILE):
            with open(SUBS_FILE, 'r') as f:
                subscriptions = json.load(f)
    except: subscriptions = []

def save_subs():
    try:
        with open(SUBS_FILE, 'w') as f:
            json.dump(subscriptions, f)
    except: pass

load_subs()

# --- VAPID JWT ---
try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    HAS_CRYPTO=True
    print('crypto ok')
except Exception as e:
    HAS_CRYPTO=False
    print(f'crypto missing {e}')
    hashes=None; ec=None; utils=None

def b64url_encode(b): return base64.urlsafe_b64encode(b).decode().rstrip("=")
def b64url_decode(s):
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)

if HAS_CRYPTO:
    priv_bytes = b64url_decode(VAPID_PRIVATE_B64)
    priv_int = int.from_bytes(priv_bytes, 'big')
    private_key_obj = ec.derive_private_key(priv_int, ec.SECP256R1())
else:
    private_key_obj=None

def create_vapid_token(aud):
    if not HAS_CRYPTO:
        return 'dummy'

    import json as js
    header = {"typ":"JWT","alg":"ES256"}
    payload = {"aud": aud, "exp": int(time.time())+86400, "sub": VAPID_SUBJECT}
    hb = b64url_encode(js.dumps(header, separators=(',',':')).encode())
    pb = b64url_encode(js.dumps(payload, separators=(',',':')).encode())
    signing_input = f"{hb}.{pb}".encode()
    der_sig = private_key_obj.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der_sig)
    raw = r.to_bytes(32,'big') + s.to_bytes(32,'big')
    sb = b64url_encode(raw)
    return f"{hb}.{pb}.{sb}"

def send_push_no_payload(sub):
    if not HAS_CRYPTO:
        print('push skipped no crypto')
        return True
    try:
        from urllib.parse import urlparse
        endpoint = sub.get('endpoint','')
        if not endpoint: return False
        parsed = urlparse(endpoint)
        aud = f"{parsed.scheme}://{parsed.netloc}"
        token = create_vapid_token(aud)
        headers = {
            "Authorization": f"vapid t={token}, k={VAPID_PUBLIC_KEY}",
            "TTL": "60",
            "Content-Length": "0"
        }
        if HAS_REQUESTS:
            r = requests.post(endpoint, headers=headers, timeout=8)
            status = r.status_code
            text = r.text[:200] if hasattr(r,'text') else ''
        else:
            # fallback urllib
            req = _urllib.Request(endpoint, data=b'', headers=headers, method='POST')
            try:
                with _urllib.urlopen(req, timeout=8) as resp:
                    status = resp.getcode()
                    text = ''
            except _uerror.HTTPError as he:
                status = he.code
                text = ''
            except Exception as e:
                print(f'push urllib error {e}')
                return True
        # print(f"push status {status}")
        r_status = status
        if False:
            r = None
        
        if r_status in [404,410]:
            return False
        return r_status in [200,201,202,204]
    except Exception as e:
        print(f"push error {e}")
        return True

def send_push_to_all():
    global subscriptions
    to_keep=[]
    for sub in subscriptions:
        ok = send_push_no_payload(sub)
        if ok is not False:
            to_keep.append(sub)
    if len(to_keep)!=len(subscriptions):
        subscriptions=to_keep
        save_subs()

# --- TRADING LOGIC (python replica of JS) ---
def fetch_klines(symbol, interval='1h', limit=150):
    urls=[
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}",
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    ]
    for u in urls:
        try:
            if HAS_REQUESTS:
                r=requests.get(u, timeout=6)
                if r.status_code==200:
                    j=r.json()
                    if j and isinstance(j,list) and len(j)>0 and not (isinstance(j,dict) and 'code' in j):
                        return j
            else:
                with _urllib.urlopen(u, timeout=6) as resp:
                    data=resp.read().decode()
                    j=json.loads(data)
                    if j and isinstance(j,list) and len(j)>0:
                        return j
        except Exception as e:
            # print(f"fetch fail {u} {e}")
            pass
    return []

def calc_rsi(prices, period=14):
    if len(prices)<period+1: return 50
    gains=0; losses=0
    for i in range(1, period+1):
        d=prices[i]-prices[i-1]
        if d>=0: gains+=d
        else: losses-=d
    ag=gains/period; al=losses/period
    if al==0: return 85
    for i in range(period+1, len(prices)):
        d=prices[i]-prices[i-1]
        gg=d if d>0 else 0
        ll=-d if d<0 else 0
        ag=(ag*(period-1)+gg)/period
        al=(al*(period-1)+ll)/period
    if al==0: return 85
    rs=ag/al
    return 100-100/(1+rs)

def calc_ema(prices, period):
    k=2/(period+1)
    ema=prices[0]
    for p in prices[1:]:
        ema=p*k+ema*(1-k)
    return ema

def calc_conf(stato, rsi, ema20, ema50, volLabel):
    c=50; reasons=[]
    if stato=='COMPRA':
        if rsi<25: c+=28; reasons.append('Ipervenduto')
        elif rsi<35: c+=18; reasons.append('RSI basso')
        elif rsi>60: c-=12; reasons.append('RSI alto')
        if ema20>ema50: c+=14; reasons.append('Rialzista')
        else: c-=14; reasons.append('Contro-trend')
        if volLabel=='VOL ALTO': c+=14; reasons.append('Vol alto')
        elif volLabel=='VOL BASSO': c-=16; reasons.append('Vol basso')
    elif stato=='VENDI':
        if rsi>75: c+=28; reasons.append('Ipercomprato')
        elif rsi>65: c+=18; reasons.append('RSI alto')
        elif rsi<40: c-=12; reasons.append('RSI basso')
        if ema20<ema50: c+=14; reasons.append('Ribassista')
        else: c-=14; reasons.append('Contro-trend')
        if volLabel=='VOL ALTO': c+=14; reasons.append('Vol alto')
        elif volLabel=='VOL BASSO': c-=16; reasons.append('Vol debole')
    else:
        c=45+abs(rsi-50)/2; reasons.append('Laterale')
    conf=max(12,min(94, round(c)))
    return conf, reasons

def check_coins():
    global latest_signals, prev_signals
    configs=[
        ('BTCEUR',['BTCEUR']),
        ('ETHEUR',['ETHEUR']),
        ('PAXGEUR',['PAXGEUR','PAXGUSDT'])
    ]
    new_signals=[]
    for label, fallbacks in configs:
        kl=None; used=None
        for sym in fallbacks:
            kl=fetch_klines(sym,'1h',150)
            if kl and len(kl)>30:
                used=sym; break
        if not kl: continue
        closes=[float(c[4]) for c in kl]
        vols=[float(c[5]) for c in kl]
        # EUR/USDT conversion if needed
        if used and used.endswith('USDT'):
            try:
                eur_kl=fetch_klines('EURUSDT','1h',2)
                if eur_kl:
                    rate=float(eur_kl[-1][4])
                    closes=[p/rate for p in closes]
            except: pass
        price=closes[-1]
        rsi=calc_rsi(closes,14)
        ema20=calc_ema(closes,20)
        ema50=calc_ema(closes,50)
        vol_now=vols[-1]; vol_avg=sum(vols[-21:-1])/20 if len(vols)>21 else vol_now
        if vol_now < vol_avg*0.7: volLabel='VOL BASSO'
        elif vol_now > vol_avg*1.9: volLabel='VOL ALTO'
        else: volLabel='VOL NORMALE'
        trend='Rialzista' if ema20>ema50 else 'Ribassista'
        stato='FERMO'
        if rsi>70: stato='VENDI'
        elif rsi<30: stato='COMPRA'
        elif ema20>ema50 and rsi>55: stato='COMPRA'
        elif ema20<ema50 and rsi<45: stato='VENDI'
        conf, reasons = calc_conf(stato, rsi, ema20, ema50, volLabel)
        if conf>=60 and stato in ('COMPRA','VENDI'):
            key=f"{label}_1h"
            if prev_signals.get(key)!=stato:
                new_signals.append({
                    'sym': label,
                    'stato': stato,
                    'conf': conf,
                    'price': price,
                    'reason': reasons[0] if reasons else '',
                    'rsi': round(rsi,1),
                    'time': int(time.time()*1000)
                })
                prev_signals[key]=stato
    if new_signals:
        latest_signals = new_signals + latest_signals
        latest_signals = latest_signals[:20]
        print(f"NEW SIGNALS {new_signals} -> pushing to {len(subscriptions)} subs")
        send_push_to_all()
    else:
        print(f"check {datetime.now()} no new signal")

def checker_loop():
    while True:
        try:
            check_coins()
        except Exception as e:
            print(f"checker error {e}")
        time.sleep(60)

threading.Thread(target=checker_loop, daemon=True).start()

# --- HTML APP ---
HTML = """<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#7c3aed">
<link rel="manifest" href="/manifest.json"><link rel="icon" href="/icon-192.png">
<script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
<style>:root{--bg:#070b18;--card:#131a2e;--card2:#0a1020;--border:#1e2a4a;--text:#e2e8f0;--muted:#94a3b8}.light{--bg:#f1f5f9;--card:#fff;--card2:#f8fafc;--border:#e2e8f0;--text:#0f172a;--muted:#64748b}*{margin:0;padding:0;box-sizing:border-box}body{background:var(--bg);color:var(--text);font-family:system-ui;padding:12px;padding-bottom:90px} .header{position:sticky;top:0;z-index:20;background:var(--bg);padding:10px 0;margin:-12px -12px 14px;padding-left:12px;padding-right:12px;border-bottom:1px solid var(--border)}.h-row{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.logo{width:42px;height:42px;background:linear-gradient(135deg,#7c3aed,#3b82f6);border-radius:14px;display:flex;align-items:center;justify-content:center;font-weight:900;color:#fff}.btn{border:none;padding:7px 11px;border-radius:20px;font-weight:700;cursor:pointer;font-size:12px}.btn-install{background:var(--text);color:var(--bg)}.btn-icon{background:var(--card);color:var(--text);border:1px solid var(--border)}.btn-icon.on{background:#10b981;color:#000}.tf-bar{display:flex;gap:6px;overflow-x:auto;margin-top:10px}.tf{padding:6px 14px;border-radius:20px;background:var(--card);border:1px solid var(--border);color:var(--muted);font-weight:700;font-size:13px;cursor:pointer}.tf.active{background:var(--text);color:var(--bg)}.card{background:var(--card);border:1px solid var(--border);border-radius:18px;padding:14px;margin-bottom:12px}.price{font-size:26px;font-weight:900}.badge{padding:5px 10px;border-radius:20px;font-weight:900;font-size:11px}.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:10px 0}.mini{font-size:10px;opacity:.6;text-transform:uppercase;color:var(--muted)}.val{font-size:13px;font-weight:800;display:block;margin-top:2px}.conf-bar{height:6px;background:var(--card2);border-radius:10px;overflow:hidden;margin-top:6px}.conf-fill{height:100%;border-radius:10px}.chart-wrap{margin-top:12px;background:var(--card2);border-radius:14px;padding:8px;display:none;border:1px solid var(--border)}.chart-wrap.open{display:block}.chart-box{width:100%;height:300px}.btn-chart{background:var(--card2);border:1px solid var(--border);color:var(--muted);width:100%;margin-top:8px;padding:8px;border-radius:20px}.toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:var(--text);color:var(--bg);padding:12px 20px;border-radius:30px;font-weight:800;z-index:99;display:none;max-width:90%;text-align:center}.hist-table{width:100%;font-size:12px;border-collapse:collapse}.hist-table th{font-size:10px;opacity:.5;text-align:left;padding:6px}.hist-table td{padding:8px 6px;border-top:1px solid var(--border)}.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px}
#installBanner{display:none;position:fixed;bottom:80px;left:12px;right:12px;background:var(--card);border:1px solid var(--border);border-radius:16px;padding:14px;z-index:50;box-shadow:0 10px 30px #0005}
</style></head><body>
<div class="header"><div class="h-row"><div class="logo">V€</div><div style="flex:1"><div style="font-weight:900;font-size:14px">Vendi STABILE PUSH</div><div style="font-size:10px;opacity:.6">BTC • ETH • ORO | PUSH VERO | CLICK APRE APP</div></div><button class="btn btn-icon" id="themeBtn">🌙</button><button class="btn btn-icon" id="notifBtn">🔔</button><button class="btn btn-icon" id="soundBtn">🔊</button><button class="btn btn-icon" id="histBtn">📜</button><button class="btn btn-install" id="installBtn" style="display:none">📲 Installa</button></div>
<div class="tf-bar"><div class="tf" data-tf="5m">5m</div><div class="tf" data-tf="15m">15m</div><div class="tf active" data-tf="1h">1H</div><div class="tf" data-tf="4h">4H</div><div class="tf" data-tf="1d">1D</div></div></div>
<div id="installBanner"><div style="display:flex;justify-content:space-between;align-items:center"><div><div style="font-weight:900">📲 Installa come App</div><div style="font-size:11px;opacity:.7">Push vero - notifiche anche ad app chiusa</div></div><div style="display:flex;gap:8px"><button class="btn btn-icon" onclick="document.getElementById('installBanner').style.display='none'">✕</button><button class="btn btn-install" id="bannerInstall">Installa</button></div></div></div>
<div class="card" style="display:flex;align-items:center;gap:12px"><div style="width:44px;height:44px;background:var(--card2);border-radius:50%;display:flex;align-items:center;justify-content:center;border:1px solid var(--border)">📊</div><div style="flex:1"><div style="font-size:10px;letter-spacing:2px;opacity:.6">GLOBALE</div><div id="globale" style="font-size:17px;font-weight:900;color:#fbbf24">CARICAMENTO...</div><div id="globaleSub" style="font-size:11px;opacity:.6"></div></div><div style="text-align:right"><div style="font-size:9px;opacity:.5">TF</div><div id="tfLabel" style="font-weight:900">1H</div></div></div>
<div id="coins"></div>
<div class="card" id="historyCard" style="display:none"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><div style="font-weight:900">📜 Storico con TF</div><div style="display:flex;gap:6px"><button class="btn btn-icon" onclick="clearHistory()">🗑️</button><button class="btn btn-icon" onclick="document.getElementById('historyCard').style.display='none'">✕</button></div></div><div style="max-height:400px;overflow-y:auto"><table class="hist-table"><thead><tr><th>ORA</th><th>COIN</th><th>SEGNALE</th><th>%</th><th>PREZZO</th><th>TF</th></tr></thead><tbody id="histBody"></tbody></table></div></div>
<div style="text-align:center;margin-top:10px;font-size:11px;opacity:.4" id="upd"></div><div class="toast" id="toast"></div>
<script>
const VAPID_PUBLIC_KEY="BC2EkkzHG1EPz_akF0s-Fy8CIHFE0Wl6TGWsexqRojEyEh0rjDfKRSqev2HY86U1PBMK2KGnSItpJ_69oKFCshA";
function urlBase64ToUint8Array(base64String){const padding='='.repeat((4-base64String.length%4)%4);const base64=(base64String+padding).replace(/-/g,'+').replace(/_/g,'/');const rawData=window.atob(base64);const outputArray=new Uint8Array(rawData.length);for(let i=0;i<rawData.length;++i){outputArray[i]=rawData.charCodeAt(i);}return outputArray;}
async function subscribePush(){try{if(!('serviceWorker' in navigator) || !('PushManager' in window))return;const reg=await navigator.serviceWorker.ready;let sub=await reg.pushManager.getSubscription();if(!sub){sub=await reg.pushManager.subscribe({userVisibleOnly:true, applicationServerKey:urlBase64ToUint8Array(VAPID_PUBLIC_KEY)});}await fetch('/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(sub)});console.log('Push subscribed OK');showToast('✅ Push vero attivo - anche ad app chiusa');}catch(e){console.error('Push fail',e);showToast('❌ Push non riuscito: '+e.message);}}
let deferredPrompt=null;
window.addEventListener('beforeinstallprompt',(e)=>{e.preventDefault();deferredPrompt=e;document.getElementById('installBtn').style.display='inline-block';document.getElementById('installBanner').style.display='block';});
document.getElementById('installBtn').onclick=async()=>{if(deferredPrompt){deferredPrompt.prompt();let {outcome}=await deferredPrompt.userChoice;if(outcome==='accepted')showToast('✅ App installata!');deferredPrompt=null;document.getElementById('installBtn').style.display='none';document.getElementById('installBanner').style.display='none';}};
document.getElementById('bannerInstall').onclick=()=>document.getElementById('installBtn').click();
if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').then(()=>{console.log('SW ok');}).catch(()=>{});}
let soundOn=false,notifOn=false,currentTF='1h',prevSignals={},charts={};
const COIN_CONFIG=[
  {id:'BTCEUR', label:'BTCEUR', name:'BTC', fallbacks:['BTCEUR']},
  {id:'ETHEUR', label:'ETHEUR', name:'ETH', fallbacks:['ETHEUR']},
  {id:'PAXGEUR', label:'PAXGEUR', name:'ORO', fallbacks:['PAXGEUR','PAXGUSDT','PAXGUSDC','XAUTUSDT']}
];
const SCAN_TFS=['5m','15m','1h','4h','1d'];
let audioCtx, historyData=JSON.parse(localStorage.getItem('vendi-history-stabile')||'[]');
let savedTheme=localStorage.getItem('vendi-theme')||'dark';
if(savedTheme==='light'){document.body.classList.add('light');}
document.getElementById('themeBtn').onclick=()=>{if(document.body.classList.contains('light')){document.body.classList.remove('light');localStorage.setItem('vendi-theme','dark');} else {document.body.classList.add('light');localStorage.setItem('vendi-theme','light');}};
function showToast(m){const t=document.getElementById('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',3500);}
function pushNotif(title,body){if(!notifOn)return;try{if('serviceWorker' in navigator){navigator.serviceWorker.ready.then(reg=>{reg.showNotification(title,{body,icon:'/icon-192.png',vibrate:[200,100,200],tag:title,data:{url:'/app'}})});} else {new Notification(title,{body});}}catch(e){try{new Notification(title,{body})}catch{}}}
async function enableNotif(){let p=await Notification.requestPermission();if(p==='granted'){notifOn=true;localStorage.setItem('vendi-notif','on');document.getElementById('notifBtn').classList.add('on');showToast('🔔 Notifiche attive');await subscribePush();}}
document.getElementById('notifBtn').onclick=()=>{if(notifOn){notifOn=false;localStorage.setItem('vendi-notif','off');document.getElementById('notifBtn').classList.remove('on');} else enableNotif();};
if(localStorage.getItem('vendi-notif')==='on'){notifOn=true;document.getElementById('notifBtn').classList.add('on');setTimeout(()=>{subscribePush();},2000);}
function playSound(t){if(!soundOn)return;try{if(!audioCtx)audioCtx=new (window.AudioContext||window.webkitAudioContext)();const o=audioCtx.createOscillator(),g=audioCtx.createGain();o.connect(g);g.connect(audioCtx.destination);if(t==='COMPRA'){o.frequency.value=880;g.gain.value=0.15;o.start();g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.6);o.stop(audioCtx.currentTime+0.6);} else {o.frequency.value=220;g.gain.value=0.2;o.type='sawtooth';o.start();g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.8);o.stop(audioCtx.currentTime+0.8);}}catch{}}
document.getElementById('soundBtn').onclick=()=>{soundOn=!soundOn;const b=document.getElementById('soundBtn');if(soundOn){b.classList.add('on');if(!audioCtx)audioCtx=new (window.AudioContext||window.webkitAudioContext)();audioCtx.resume();localStorage.setItem('vendi-sound','on');} else {b.classList.remove('on');localStorage.setItem('vendi-sound','off');}};
if(localStorage.getItem('vendi-sound')==='on'){soundOn=true;document.getElementById('soundBtn').classList.add('on');}
document.getElementById('histBtn').onclick=()=>{const c=document.getElementById('historyCard');c.style.display=c.style.display==='none'?'block':'none';renderHistory();};
function clearHistory(){if(confirm('Pulire?')){historyData=[];localStorage.setItem('vendi-history-stabile','[]');renderHistory();}}
function addHistory(sym,stato,conf,price,reasons,tf){
 if(conf<60) return;
 const last = historyData[0];
 if(last && last.sym===sym && last.stato===stato && last.tf===tf && Date.now()-last.time<300000) return;
 historyData.unshift({time:Date.now(),sym,stato,conf,price,reasons:reasons[0]||'',tf:tf||currentTF});
 if(historyData.length>200)historyData.pop();
 localStorage.setItem('vendi-history-stabile',JSON.stringify(historyData));renderHistory();
}
function renderHistory(){
 const tb=document.getElementById('histBody');
 let filtered=historyData.filter(h=>h.conf>=60);
 if(!filtered.length){tb.innerHTML='<tr><td colspan=6 style="text-align:center;opacity:.5;padding:20px">Nessun segnale</td></tr>';return;}
 tb.innerHTML=filtered.slice(0,80).map(h=>{
  const d=new Date(h.time);const t=d.toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'});
  const col=h.stato==='COMPRA'?'#10b981':h.stato==='VENDI'?'#ef4444':'#fbbf24';
  const tfLabel=(h.tf||'').toUpperCase();
  return `<tr><td>${t}</td><td><b>${h.sym}</b></td><td><span class="dot" style="background:${col}"></span>${h.stato}</td><td>${h.conf}%</td><td>€${h.price.toFixed(2)}</td><td><b>${tfLabel}</b></td></tr>`;
 }).join('');
}
document.querySelectorAll('.tf').forEach(el=>{el.onclick=()=>{document.querySelectorAll('.tf').forEach(x=>x.classList.remove('active'));el.classList.add('active');currentTF=el.dataset.tf;document.getElementById('tfLabel').textContent=currentTF.toUpperCase();refresh();};});
function calcRSI(p,period=14){if(p.length<period+1)return 50;let g=0,l=0;for(let i=1;i<=period;i++){let d=p[i]-p[i-1];if(d>=0)g+=d;else l-=d;}let ag=g/period,al=l/period;if(al===0)return 85;for(let i=period+1;i<p.length;i++){let d=p[i]-p[i-1];let gg=d>0?d:0,ll=d<0?-d:0;ag=(ag*(period-1)+gg)/period;al=(al*(period-1)+ll)/period;}return 100-100/(1+ag/al);}
function calcEMA(p,period){let k=2/(period+1);let ema=p[0];for(let i=1;i<p.length;i++)ema=p[i]*k+ema*(1-k);return ema;}
function calcEMAArray(p,period){let k=2/(period+1);let ema=p[0];let arr=[ema];for(let i=1;i<p.length;i++){ema=p[i]*k+ema*(1-k);arr.push(ema);}return arr;}
function calcConfidence(o){let c=50,r=[];if(o.stato==='COMPRA'){if(o.rsi<25){c+=28;r.push('Ipervenduto');} else if(o.rsi<35){c+=18;r.push('RSI basso');} else if(o.rsi>60){c-=12;r.push('RSI alto');}if(o.ema20>o.ema50){c+=14;r.push('Rialzista');} else {c-=14;r.push('Contro-trend');}if(o.volLabel==='VOL ALTO'){c+=14;r.push('Vol alto');} else if(o.volLabel==='VOL BASSO'){c-=16;r.push('Vol basso');}} else if(o.stato==='VENDI'){if(o.rsi>75){c+=28;r.push('Ipercomprato');} else if(o.rsi>65){c+=18;r.push('RSI alto');} else if(o.rsi<40){c-=12;r.push('RSI basso');}if(o.ema20<o.ema50){c+=14;r.push('Ribassista');} else {c-=14;r.push('Contro-trend');}if(o.volLabel==='VOL ALTO'){c+=14;r.push('Vol alto');} else if(o.volLabel==='VOL BASSO'){c-=16;r.push('Vol debole');}} else {c=45+(Math.abs(o.rsi-50)/2);r.push('Laterale');}return {conf:Math.max(12,Math.min(94,Math.round(c))),reasons:r};}
async function fetchKlines(sym,interval,limit=150){const urls=[`https://api.binance.com/api/v3/klines?symbol=${sym}&interval=${interval}&limit=${limit}`,`https://data-api.binance.vision/api/v3/klines?symbol=${sym}&interval=${interval}&limit=${limit}`];for(let u of urls){try{let r=await fetch(u);if(!r.ok)continue;let j=await r.json();if(j && j.length && !j.code)return j;}catch{} }return [];}
async function getEurUsdtRate(){try{let kl=await fetchKlines('EURUSDT','1h',2);if(kl.length) return parseFloat(kl[kl.length-1][4]);}catch{} return 1.08;}
async function loadCoinForTF(cfg, tf){
 try{
  let kl=null, usedSymbol=null;
  for(let sym of cfg.fallbacks){kl=await fetchKlines(sym,tf,150);if(kl && kl.length){usedSymbol=sym;break;}}
  if(!kl || !kl.length) return null;
  let closes=kl.map(c=>parseFloat(c[4]));let volumes=kl.map(c=>parseFloat(c[5]));
  if(usedSymbol && usedSymbol.endsWith('USDT')){let rate=await getEurUsdtRate();closes=closes.map(p=>p/rate);kl=kl.map(c=>{let nc=[...c]; nc[1]=(parseFloat(c[1])/rate).toString(); nc[2]=(parseFloat(c[2])/rate).toString(); nc[3]=(parseFloat(c[3])/rate).toString(); nc[4]=(parseFloat(c[4])/rate).toString(); return nc;});}
  let price=closes[closes.length-1]; let rsi=calcRSI(closes,14);let ema20=calcEMA(closes,20);let ema50=calcEMA(closes,50);
  let volNow=volumes[volumes.length-1];let volAvg=volumes.slice(-21,-1).reduce((a,b)=>a+b,0)/20;
  let volLabel=volNow < volAvg*0.7 ? 'VOL BASSO' : volNow > volAvg*1.9 ? 'VOL ALTO' : 'VOL NORMALE';
  let trend=ema20>ema50?'Rialzista':'Ribassista';let stato='FERMO',col='#fbbf24',tc='#000';
  if(rsi>70){stato='VENDI';col='#ef4444';tc='#fff';} else if(rsi<30){stato='COMPRA';col='#10b981';} else if(ema20>ema50 && rsi>55){stato='COMPRA';col='#10b981';} else if(ema20<ema50 && rsi<45){stato='VENDI';col='#ef4444';tc='#fff';}
  let cr=calcConfidence({stato,rsi,ema20,ema50,volLabel,price});
  if(cr.conf>=60 && (stato==='COMPRA'||stato==='VENDI')){
    const key=cfg.id+'_'+tf;
    if(!prevSignals[key] || prevSignals[key]!==stato){
      const lastSame=historyData.find(h=>h.sym===cfg.label && h.tf===tf && h.stato===stato);
      const canNotify=!lastSame || (Date.now()-lastSame.time>600000);
      if(canNotify){addHistory(cfg.label,stato,cr.conf,price,cr.reasons,tf); playSound(stato); pushNotif(`${cfg.label}: ${stato} ${cr.conf}% [${tf.toUpperCase()}]`,`€${price.toFixed(2)} - ${cr.reasons[0]||''}`); showToast(`${cfg.label} ${stato} ${cr.conf}% su ${tf.toUpperCase()}`);}
    }
    prevSignals[key]=stato;
  }
  return {sym:cfg.label,displayName:cfg.name,price,rsi,ema20,ema50,trend,stato,col,tc,volLabel,conf:cr.conf,reasons:cr.reasons,kl,usedSymbol};
 }catch(e){return null;}
}
async function loadCoin(cfg){return await loadCoinForTF(cfg,currentTF);}
function renderCandle(id,kl){
 const container=document.getElementById('chart-'+id);if(!container)return;container.innerHTML='';const chart=LightweightCharts.createChart(container,{width:container.clientWidth,height:300,layout:{background:{type:'solid',color:'transparent'},textColor:getComputedStyle(document.body).getPropertyValue('--muted')},grid:{vertLines:{color:getComputedStyle(document.body).getPropertyValue('--border')},horzLines:{color:getComputedStyle(document.body).getPropertyValue('--border')}},rightPriceScale:{borderColor:getComputedStyle(document.body).getPropertyValue('--border')},timeScale:{borderColor:getComputedStyle(document.body).getPropertyValue('--border')}});
 const candleSeries=chart.addCandlestickSeries({upColor:'#10b981',downColor:'#ef4444',borderVisible:false,wickUpColor:'#10b981',wickDownColor:'#ef4444'});
 const data=kl.map(k=>({time:Math.floor(k[0]/1000),open:parseFloat(k[1]),high:parseFloat(k[2]),low:parseFloat(k[3]),close:parseFloat(k[4])}));candleSeries.setData(data);
 const closes=kl.map(k=>parseFloat(k[4]));const ema20Arr=calcEMAArray(closes,20);const ema50Arr=calcEMAArray(closes,50);
 const ema20Line=chart.addLineSeries({color:'#3b82f6',lineWidth:1});ema20Line.setData(data.map((d,i)=>({time:d.time,value:ema20Arr[i]})).filter((_,i)=>i>=20));
 const ema50Line=chart.addLineSeries({color:'#f59e0b',lineWidth:1});ema50Line.setData(data.map((d,i)=>({time:d.time,value:ema50Arr[i]})).filter((_,i)=>i>=50));
 chart.timeScale().fitContent();charts[id]={chart};
}
async function refresh(){
 let html='',segnali=[];let results=await Promise.all(COIN_CONFIG.map(c=>loadCoin(c)));results=results.filter(Boolean);
 results.sort((a,b)=>{let order={'BTCEUR':0,'ETHEUR':1,'PAXGEUR':2};return (order[a.sym]??99)-(order[b.sym]??99);});
 for(let d of results){
  segnali.push(d.stato); let name=d.displayName; let confColor=d.conf>=75?'#10b981':d.conf>=55?'#fbbf24':'#ef4444';
  let badgeExtra=d.usedSymbol && d.usedSymbol!==d.sym ? ` <span style="font-size:9px;opacity:.6">(${d.usedSymbol}→€)</span>` : '';
  html+=`<div class="card"><div style="display:flex;justify-content:space-between;align-items:center"><div style="display:flex;gap:10px;align-items:center"><div style="width:42px;height:42px;background:var(--card2);border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:900;border:1px solid var(--border)">${name[0]}</div><div><div style="font-weight:900">${d.sym}${badgeExtra}</div><div style="font-size:11px;opacity:.6">${name} • ${d.volLabel}</div></div></div><div style="text-align:right"><div class="badge" style="background:${d.col};color:${d.tc}">${d.stato}</div><div style="font-size:11px;margin-top:4px;font-weight:800;color:${confColor}">${d.conf}%</div></div></div><div class="price" style="margin:10px 0">€${d.price.toLocaleString('it-IT',{minimumFractionDigits:2,maximumFractionDigits:2})}</div><div style="display:flex;justify-content:space-between;font-size:11px"><span style="opacity:.6">${d.reasons.slice(0,2).join(' • ')}</span><span style="font-weight:800;color:${confColor}">${d.conf}% affidabile</span></div><div class="conf-bar"><div class="conf-fill" style="width:${d.conf}%;background:${confColor}"></div></div><div class="grid3"><div class="card" style="margin:0;background:var(--card2)"><div class="mini">RSI</div><span class="val">${d.rsi.toFixed(1)}</span></div><div class="card" style="margin:0;background:var(--card2)"><div class="mini">EMA</div><span class="val" style="color:${d.trend==='Rialzista'?'#10b981':'#ef4444'}">${d.trend}</span></div><div class="card" style="margin:0;background:var(--card2)"><div class="mini">Vol</div><span class="val">${d.volLabel.replace('VOL ','')}</span></div></div><div style="display:flex;gap:6px"><button class="btn btn-chart" style="flex:1" onclick="toggleChart('${d.sym}')">🕯️ Candele</button></div><div class="chart-wrap" id="wrap-${d.sym}"><div class="chart-box" id="chart-${d.sym}"></div></div></div>`;
 }
 document.getElementById('coins').innerHTML=html || '<div class="card" style="text-align:center;opacity:.5">Caricamento...</div>';
 let comp=segnali.filter(s=>s==='COMPRA').length,vend=segnali.filter(s=>s==='VENDI').length;
 let glob=document.getElementById('globale'),sub=document.getElementById('globaleSub');
 let total=COIN_CONFIG.length;
 if(comp>=2){glob.textContent='COMPRA';glob.style.color='#10b981';sub.textContent=comp+'/'+total+' COMPRA';}
 else if(vend>=2){glob.textContent='VENDI';glob.style.color='#ef4444';sub.textContent=vend+'/'+total+' VENDI';}
 else {glob.textContent='FERMO';glob.style.color='#fbbf24';sub.textContent='Laterale';}
 document.getElementById('upd').textContent='Agg: '+new Date().toLocaleTimeString('it-IT')+' • TF:'+currentTF.toUpperCase()+' • PUSH VERO';
 setTimeout(async ()=>{for(let tf of SCAN_TFS){if(tf===currentTF) continue; for(let cfg of COIN_CONFIG){await loadCoinForTF(cfg,tf); await new Promise(r=>setTimeout(r,300));}} },2000);
}
function toggleChart(sym){
  const wrap=document.getElementById('wrap-'+sym); if(!wrap) return;
  const isOpen=wrap.classList.contains('open');
  document.querySelectorAll('.chart-wrap').forEach(w=>w.classList.remove('open'));
  if(!isOpen){
    wrap.classList.add('open');
    const cfg=COIN_CONFIG.find(c=>c.label===sym);
    if(cfg){loadCoinForTF(cfg,currentTF).then(d=>{if(d && d.kl) renderCandle(sym,d.kl);});}
  }
}
refresh();setInterval(refresh,60000);renderHistory();
// handle ?sym param to highlight
const urlParams=new URLSearchParams(window.location.search);
const symParam=urlParams.get('sym');
if(symParam){setTimeout(()=>{document.getElementById('coins')?.scrollIntoView();},1000);}
</script></body></html>
"""

@app.route("/")
def home():
    return '<a href="/app">Vai alla versione PUSH VERO</a>'

@app.route("/app")
def app_route():
    return Response(HTML, mimetype="text/html")

@app.route("/manifest.json")
def manifest():
    data={
        "name":"Vendi STABILE PUSH VERO",
        "short_name":"Vendi€ PUSH",
        "id":"/app",
        "scope":"/",
        "start_url":"/app",
        "display":"standalone",
        "display_override":["window-controls-overlay","standalone"],
        "launch_handler":{"client_mode":["focus-existing","auto"]},
        "background_color":"#070b18",
        "theme_color":"#7c3aed",
        "icons":[
            {"src":"/icon-192.png","sizes":"192x192","type":"image/png"},
            {"src":"/icon-512.png","sizes":"512x512","type":"image/png"}
        ]
    }
    return Response(json.dumps(data), mimetype="application/json")

@app.route("/sw.js")
def sw():
    js="""
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>{
  e.waitUntil(self.clients.claim());
});
self.addEventListener('push', event=>{
  event.waitUntil(
    fetch('/api/latest').then(r=>r.json()).then(d=>{
      if(!d.signals || !d.signals.length){
        return self.registration.showNotification('Vendi€ PUSH', {body:'Controllo completato - nessun segnale forte', icon:'/icon-192.png', badge:'/icon-192.png', data:{url:'/app'}, vibrate:[200,100,200]});
      }
      const s=d.signals[0];
      const title=`${s.sym}: ${s.stato} ${s.conf}%`;
      const body=`€${s.price.toFixed(2)} - ${s.reason} - RSI ${s.rsi} - TAP PER APRIRE APP`;
      return self.registration.showNotification(title, {body, icon:'/icon-192.png', badge:'/icon-192.png', data:{url:`/app?sym=${s.sym}`}, tag:s.sym, renotify:true, vibrate:[200,100,200], requireInteraction:true});
    }).catch(()=>self.registration.showNotification('Vendi€ PUSH', {body:'Nuovo segnale! Tap per aprire APP', icon:'/icon-192.png', badge:'/icon-192.png', data:{url:'/app'}}))
  );
});
self.addEventListener('notificationclick', event=>{
  event.notification.close();
  const rawUrl = event.notification.data && event.notification.data.url || '/app';
  const fullUrl = new URL(rawUrl, self.location.origin).href;
  event.waitUntil(
    clients.matchAll({type:'window', includeUncontrolled:true}).then(clientList=>{
      for(let client of clientList){
        // se c'è già una finestra dell'app, portala in primo piano e naviga lì
        if(client.url.includes(self.location.origin)){
          if('focus' in client){
            if('navigate' in client){
              client.navigate(fullUrl);
            }
            return client.focus();
          }
        }
      }
      // altrimenti apri l'app installata (se installata apre come app, non chrome)
      if(clients.openWindow){
        return clients.openWindow(fullUrl);
      }
    })
  );
});
self.addEventListener('fetch', e=>{});
"""
    return Response(js, mimetype="application/javascript")

@app.route("/vapidPublicKey")
def vapid_key():
    return jsonify({"publicKey": VAPID_PUBLIC_KEY})

@app.route("/subscribe", methods=["POST"])
def subscribe():
    try:
        data=request.get_json()
        if not data or 'endpoint' not in data:
            return jsonify({"error":"no endpoint"}), 400
        # avoid duplicates
        exists=False
        for s in subscriptions:
            if s.get('endpoint')==data.get('endpoint'):
                exists=True; break
        if not exists:
            subscriptions.append(data)
            save_subs()
        print(f"New sub, total {len(subscriptions)}")
        return jsonify({"ok":True, "total": len(subscriptions)})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/latest")
def api_latest():
    return jsonify({"signals": latest_signals, "time": int(time.time()*1000)})

@app.route("/test-push")
def test_push():
    # forza un segnale finto per test
    global latest_signals
    latest_signals=[{"sym":"BTCEUR","stato":"COMPRA","conf":88,"price":56222.37,"reason":"Test PUSH VERO","rsi":58.5,"time":int(time.time()*1000)}] + latest_signals
    latest_signals=latest_signals[:10]
    send_push_to_all()
    return jsonify({"ok":True, "sent_to": len(subscriptions), "signals": latest_signals})

@app.route("/icon-192.png")
def icon192():
    return Response(base64.b64decode(ICON_192_B64), mimetype="image/png")

@app.route("/icon-512.png")
def icon512():
    return Response(base64.b64decode(ICON_512_B64), mimetype="image/png")

@app.route("/icon.png")
def icon():
    return icon192()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
