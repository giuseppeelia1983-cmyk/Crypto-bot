import requests
import time
import os
from datetime import datetime

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    print("ERRORE: Variabili mancanti!")
    exit(1)

MIN_LIQUIDITA_USD = 5000
MIN_VOLUME_24H_USD = 1000
MAX_ETA_ORE = 48
MIN_SICUREZZA_SCORE = 60
INTERVALLO_CONTROLLO = 60

def invia_telegram(messaggio):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": messaggio, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
        print("Alert Telegram inviato!")
    except Exception as e:
        print(f"Errore Telegram: {e}")

def analizza_sicurezza_eth(address):
    score = 100
    problemi = []
    try:
        r = requests.get(f"https://api.honeypot.is/v2/IsHoneypot?address={address}", timeout=10)
        dati = r.json()
        if dati.get("isHoneypot"):
            score -= 80
            problemi.append("HONEYPOT RILEVATO")
        sim = dati.get("simulationResult", {})
        if sim.get("buyTax", 0) > 10:
            score -= 20
            problemi.append(f"Buy tax alta: {sim.get('buyTax')}%")
        if sim.get("sellTax", 0) > 10:
            score -= 30
            problemi.append(f"Sell tax alta: {sim.get('sellTax')}%")
    except:
        score = 50
        problemi.append("Check sicurezza non disponibile")
    return max(0, min(100, score)), problemi

def analizza_sicurezza_sol(address):
    score = 50
    problemi = ["Analisi base Solana"]
    try:
        r = requests.get(f"https://api.rugcheck.xyz/v1/tokens/{address}/report/summary", timeout=10)
        if r.status_code == 200:
            rischio = r.json().get("score", 0)
            if rischio > 8000:
                score = 10
                problemi = ["ALTO RISCHIO RugCheck"]
            elif rischio > 5000:
                score = 40
                problemi = ["Rischio medio RugCheck"]
            else:
                score = 90
                problemi = ["Rischio basso RugCheck"]
    except:
        pass
    return score, problemi

token_visti = set()

def fetch_token(chain_id):
    try:
        url = f"https://api.dexscreener.com/token-profiles/latest/v1"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []
        dati = r.json()
        if not isinstance(dati, list):
            return []
        return [d for d in dati if d.get("chainId") == chain_id]
    except Exception as e:
        print(f"Errore fetch {chain_id}: {e}")
        return []

def fetch_pair_info(token_address, chain_id):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return None
        dati = r.json()
        pairs = dati.get("pairs")
        if not pairs or len(pairs) == 0:
            return None
        return pairs[0]
    except:
        return None

def analizza_token(token, chain):
    try:
        address = token.get("tokenAddress", "")
        if not address or address in token_visti:
            return False
        token_visti.add(address)

        pair = fetch_pair_info(address, chain.lower())
        if not pair:
            return False

        nome = pair.get("baseToken", {}).get("name", "Sconosciuto")
        simbolo = pair.get("baseToken", {}).get("symbol", "???")
        liquidita = float(pair.get("liquidity", {}).get("usd", 0) or 0)
        volume = float(pair.get("volume", {}).get("h24", 0) or 0)
        prezzo = pair.get("priceUsd", "N/A")
        dex = pair.get("dexId", "Unknown")
        pair_address = pair.get("pairAddress", "")
        created_at = pair.get("pairCreatedAt", 0)

        eta_ore = (time.time() * 1000 - created_at) / (1000 * 3600) if created_at else 999

        if liquidita < MIN_LIQUIDITA_USD or volume < MIN_VOLUME_24H_USD or eta_ore > MAX_ETA_ORE:
            return False

        print(f"Analizzo {simbolo} ({chain})...")
        if chain == "ETH":
            score, problemi = analizza_sicurezza_eth(address)
            link_dex = f"https://www.dextools.io/app/en/ether/pair-explorer/{pair_address}"
            link_scan = f"https://etherscan.io/token/{address}"
        else:
            score, problemi = analizza_sicurezza_sol(address)
            link_dex = f"https://www.dextools.io/app/en/solana/pair-explorer/{pair_address}"
            link_scan = f"https://solscan.io/token/{address}"

        if score < MIN_SICUREZZA_SCORE:
            print(f"  Scartato - sicurezza: {score}/100")
            return False

        emoji = "🟢" if score >= 80 else "🟡"
        chain_emoji = "🔷" if chain == "ETH" else "🟣"
        problemi_testo = "\n".join(problemi) if problemi else "Nessun problema"

        messaggio = f"""{chain_emoji} <b>NUOVO TOKEN {chain}</b>

🪙 <b>{nome} (${simbolo})</b>
💰 Prezzo: <b>${prezzo}</b>
💧 Liquidità: <b>${liquidita:,.0f}</b>
📊 Volume 24h: <b>${volume:,.0f}</b>
⏱ Età: <b>{eta_ore:.1f} ore</b>
🏦 DEX: <b>{dex}</b>

{emoji} <b>Score: {score}/100</b>
{problemi_testo}

📋 <code>{address}</code>
🔗 <a href="{link_dex}">DexTools</a> | <a href="{link_scan}">Scan</a>

⚠️ <i>DYOR!</i>"""

        invia_telegram(messaggio)
        return True

    except Exception as e:
        print(f"Errore analisi: {e}")
        return False

def main():
    print("CRYPTO SCANNER BOT AVVIATO")
    invia_telegram("🤖 <b>Bot avviato!</b>\nMonitoro Ethereum e Solana...")
    ciclo = 0
    while True:
        ciclo += 1
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Ciclo #{ciclo}")
        for token in fetch_token("ethereum")[:20]:
            analizza_token(token, "ETH")
        time.sleep(3)
        for token in fetch_token("solana")[:20]:
            analizza_token(token, "SOL")
        print(f"Prossimo controllo tra {INTERVALLO_CONTROLLO}s...")
        time.sleep(INTERVALLO_CONTROLLO)

if __name__ == "__main__":
    main()
