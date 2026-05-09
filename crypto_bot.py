import requests
import time
import os
from datetime import datetime

# --- CONFIGURAZIONI ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MIN_HOLDERS_KILLER = 20      # Sotto i 20 holder scarta SEMPRE
MIN_LIQUIDITA_USD = 10000
MIN_VOLUME_24H_USD = 5000
MAX_ETA_ORE = 24
MIN_SICUREZZA_SCORE = 80
INTERVALLO_CONTROLLO = 60

# ... (funzione invia_telegram e check_duplicati rimangono uguali) ...

def check_goplus_eth(address):
    try:
        url = f"https://api.gopluslabs.io/api/v1/token_security/1?contract_addresses={address}"
        r = requests.get(url, timeout=10)
        dati = r.json().get("result", {}).get(address.lower(), {})
        
        if not dati: return 0, ["❌ Token non trovato"]

        score = 100
        problemi = []
        
        # 1. CONTROLLI BLOCCANTI (Scarta subito)
        holder_count = int(dati.get("holder_count", 0) or 0)
        if holder_count < MIN_HOLDERS_KILLER:
            return 0, [f"🚨 TROPPO RISCHIOSO: Solo {holder_count} holders"]

        if dati.get("is_honeypot") == "1": return 0, ["🚨 HONEYPOT"]
        
        # NUOVO: Controllo Liquidità Bloccata
        lp_holders = dati.get("lp_holders", [])
        is_lp_locked = any(float(lp.get("percent", 0)) > 50 for lp in lp_holders if lp.get("is_locked") == 1)
        # Se vuoi essere severo:
        # if not is_lp_locked: return 0, ["🚨 LIQUIDITÀ NON BLOCCATA"]

        # 2. CONTROLLI PENALIZZANTI (Abbassano lo score)
        if dati.get("is_blacklisted") == "1": return 0, ["🚨 BLACKLISTED"]
        
        sell_tax = float(dati.get("sell_tax", 0) or 0)
        if sell_tax > 15: return 0, [f"🚨 Sell tax folle: {sell_tax}%"]
        
        # ... (restante logica delle tasse e owner_pct come prima) ...

        # Aggiornamento messaggi holder
        if holder_count < 100:
            score -= 10
            problemi.append(f"⚠️ Holders ancora bassi: {holder_count}")
        else:
            problemi.append(f"✅ Holders: {holder_count}")

        return max(0, score), problemi
    except Exception as e:
        return 50, [f"⚠️ Errore GoPlus: {e}"]

# ... (restante codice main e analizza_token rimane uguale) ...
