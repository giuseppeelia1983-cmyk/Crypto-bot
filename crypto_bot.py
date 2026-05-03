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
MIN_SICUREZZA_SCORE = 70
INTERVALLO_CONTROLLO = 60

def invia_telegram(messaggio):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": messaggio, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
        print("Alert Telegram inviato!")
    except Exception as e:
        print(f"Errore Telegram: {e}")

def check_blockaid(address, chain):
    """Controlla Blockaid - il sistema usato da Uniswap/MetaMask"""
    try:
        chain_id = "1" if chain == "ETH" else "900"
        url = f"https://api.blockaid.io/v0/evm/token/scan"
        headers = {"X-API-Key": "free"}
        payload = {
            "chain_id": chain_id,
            "address": address
        }
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        if r.status_code == 200:
            dati = r.json()
            risultato = dati.get("result", {})
            verdict = risultato.get("verdict", "")
            if verdict in ["malicious", "spam"]:
                return False, f"🚨 BLOCKAID: {verdict.upper()}"
            return True, "✅ Blockaid OK"
    except:
        pass
    return True, "⚠️ Blockaid non disponibile"

def check_goplus(address, chain):
    """Controlla GoPlus Security - database malicious tokens"""
    try:
        chain_id = "1" if chain == "ETH" else "900"
        url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            dati = r.json()
            risultato = dati.get("result", {}).get(address.lower(), {})
            problemi = []
            score_penalty = 0

            if risultato.get("is_honeypot") == "1":
                return False, "🚨 HONEYPOT (GoPlus)"

            if risultato.get("is_blacklisted") == "1":
                return False, "🚨 BLACKLISTED (GoPlus)"

            if risultato.get("is_phishing_init") == "1":
                return False, "🚨 PHISHING (GoPlus)"

            buy_tax = float(risultato.get("buy_tax", 0) or 0)
            sell_tax = float(risultato.get("sell_tax", 0) or 0)

            if sell_tax > 50:
                return False, f"🚨 Sell tax {sell_tax}% (GoPlus)"
            if sell_tax > 10:
                problemi.append(f"⚠️ Sell tax {sell_tax}%")
                score_penalty += 20
            if buy_tax > 10:
                problemi.append(f"⚠️ Buy tax {buy_tax}%")
                score_penalty += 10

            if risultato.get("cannot_sell_all") == "1":
                return False, "🚨 Non puoi vendere (GoPlus)"

            if risultato.get("is_mintable") == "1":
                problemi.append("⚠️ Token mintable")
                score_penalty += 15

            owner_pct = float(risultato.get("owner_percent", 0) or 0)
            if owner_pct > 50:
                problemi.append(f"⚠️ Owner ha {owner_pct}% supply")
                score_penalty += 20

            testo = "\n".join(problemi) if problemi else "✅ GoPlus OK"
            return score_penalty < 40, testo
    except Exception as e:
        print(f"GoPlus error: {e}")
    return True, "⚠️ GoPlus non disponibile"

def analizza_sicurezza(address, chain):
    """Analisi combinata: Blockaid + GoPlus + Honeypot"""
    score = 100
    tutti_problemi = []

    # Check Blockaid
    ok, msg = check_blockaid(address, chain)
    if not ok:
        return 0, [msg]
    tutti_problemi.append(msg)

    # Check GoPlus
    ok, msg = check_goplus(address, chain)
    if not ok:
        return 0, [msg]
    tutti_problemi.append(msg)

    # Check Honeypot (solo ETH)
    if chain == "ETH":
        try:
            r = requests.get(f"https://api.honeypot.is/v2/IsHoneypot?address={address}", timeout=10)
            dati = r.json()
            if dati.get("isHoneypot"):
                return 0, ["🚨 HONEYPOT RILEVATO"]
            sim = dati.get("simulationResult", {})
            sell_tax = sim.get("sellTax", 0)
            buy_tax = sim.get("buyTax", 0)
            if sell_tax > 50:
                return 0, [f"🚨 Sell tax critica: {sell_tax}%"]
            if sell_tax > 10:
                score -= 25
                tutti_problemi.append(f"⚠️ Sell tax: {sell_tax}%")
            if buy_tax > 10:
                score -= 15
                tutti_problemi.append(f"⚠️ Buy tax: {buy_tax}%")
        except:
            tutti_problemi.append("⚠️ Honeypot check non disponibile")

    return max(0, score), tutti_problemi

token_visti = set()

def fetch_token(chain_id):
    try:
        url = "https://api.dexscreener.com/token-profiles/latest/v1"
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

def fetch_pair_info(token_address):
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

        pair = fetch_pair_info(address)
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
        score, problemi = analizza_sicurezza(address, chain)

        if score < MIN_SICUREZZA_SCORE:
            print(f"  Scartato - sicurezza: {score}/100")
            return False

        if chain == "ETH":
            link_dex = f"https://www.dextools.io/app/en/ether/pair-explorer/{pair_address}"
            link_scan = f"https://etherscan.io/token/{address}"
        else:
            link_dex = f"https://www.dextools.io/app/en/solana/pair-explorer/{pair_address}"
            link_scan = f"https://solscan.io/token/{address}"

        emoji = "🟢" if score >= 85 else "🟡"
        chain_emoji = "🔷" if chain == "ETH" else "🟣"
        problemi_testo = "\n".join(problemi)

        messaggio = f"""{chain_emoji} <b>NUOVO TOKEN {chain}</b>

🪙 <b>{nome} (${simbolo})</b>
💰 Prezzo: <b>${prezzo}</b>
💧 Liquidità: <b>${liquidita:,.0f}</b>
📊 Volume 24h: <b>${volume:,.0f}</b>
⏱ Età: <b>{eta_ore:.1f} ore</b>
🏦 DEX: <b>{dex}</b>

{emoji} <b>Score Sicurezza: {score}/100</b>
{problemi_testo}

📋 <code>{address}</code>
🔗 <a href="{link_dex}">DexTools</a> | <a href="{link_scan}">Scan</a>

⚠️ <i>Controlla sempre su Uniswap prima di comprare!</i>"""

        invia_telegram(messaggio)
        return True

    except Exception as e:
        print(f"Errore analisi: {e}")
        return False

def main():
    print("CRYPTO SCANNER BOT AVVIATO - v2 con Blockaid+GoPlus")
    invia_telegram("🤖 <b>Bot v2 avviato!</b>\n🛡 Controlli: Blockaid + GoPlus + Honeypot\nMonitoro Ethereum e Solana...")
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
