import requests
import time
import os
from datetime import datetime

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    print("ERRORE: Variabili mancanti!")
    exit(1)

MIN_LIQUIDITA_USD = 10000
MIN_VOLUME_24H_USD = 5000
MAX_ETA_ORE = 24
MIN_SICUREZZA_SCORE = 80
INTERVALLO_CONTROLLO = 60

def invia_telegram(messaggio):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": messaggio, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
        print("Alert inviato!")
    except Exception as e:
        print(f"Errore Telegram: {e}")

def check_goplus_eth(address):
    """GoPlus check per Ethereum - molto dettagliato"""
    try:
        url = f"https://api.gopluslabs.io/api/v1/token_security/1?contract_addresses={address}"
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return 0, ["❌ GoPlus non raggiungibile"]
        
        dati = r.json().get("result", {}).get(address.lower(), {})
        if not dati:
            return 0, ["❌ Token non trovato su GoPlus"]

        score = 100
        problemi = []
        
        # Check bloccanti - se uno di questi è positivo scarta subito
        if dati.get("is_honeypot") == "1":
            return 0, ["🚨 HONEYPOT"]
        if dati.get("is_blacklisted") == "1":
            return 0, ["🚨 BLACKLISTED"]
        if dati.get("is_phishing_init") == "1":
            return 0, ["🚨 PHISHING"]
        if dati.get("cannot_sell_all") == "1":
            return 0, ["🚨 NON VENDIBILE"]
        if dati.get("transfer_pausable") == "1":
            return 0, ["🚨 TRANSFER PAUSABLE"]
        if dati.get("is_anti_whale") == "1" and dati.get("anti_whale_modifiable") == "1":
            return 0, ["🚨 ANTI-WHALE MODIFICABILE"]

        # Tax
        sell_tax = float(dati.get("sell_tax", 0) or 0)
        buy_tax = float(dati.get("buy_tax", 0) or 0)
        if sell_tax > 20:
            return 0, [f"🚨 Sell tax {sell_tax}%"]
        if sell_tax > 5:
            score -= 20
            problemi.append(f"⚠️ Sell tax {sell_tax}%")
        if buy_tax > 5:
            score -= 10
            problemi.append(f"⚠️ Buy tax {buy_tax}%")

        # Owner concentration
        owner_pct = float(dati.get("owner_percent", 0) or 0)
        creator_pct = float(dati.get("creator_percent", 0) or 0)
        if owner_pct > 30 or creator_pct > 30:
            return 0, [f"🚨 Owner/Creator ha {max(owner_pct, creator_pct):.0f}% supply"]
        if owner_pct > 10:
            score -= 15
            problemi.append(f"⚠️ Owner ha {owner_pct:.0f}% supply")

        # Mintable
        if dati.get("is_mintable") == "1":
            score -= 20
            problemi.append("⚠️ Token mintable")

        # Proxy
        if dati.get("is_proxy") == "1":
            score -= 10
            problemi.append("⚠️ Contratto proxy")

        # Holders
        holder_count = int(dati.get("holder_count", 0) or 0)
        if holder_count < 50:
            score -= 15
            problemi.append(f"⚠️ Pochi holder: {holder_count}")
        elif holder_count > 200:
            problemi.append(f"✅ Holder: {holder_count}")

        if not problemi:
            problemi.append("✅ GoPlus: nessun problema")

        return max(0, score), problemi

    except Exception as e:
        print(f"GoPlus ETH error: {e}")
        return 50, ["⚠️ GoPlus non disponibile"]

def check_goplus_sol(address):
    """GoPlus check per Solana"""
    try:
        url = f"https://api.gopluslabs.io/api/v1/token_security/900?contract_addresses={address}"
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return 50, ["⚠️ GoPlus SOL non disponibile"]
        
        dati = r.json().get("result", {}).get(address.lower(), {})
        if not dati:
            return 50, ["⚠️ Token SOL non su GoPlus"]

        score = 100
        problemi = []

        if dati.get("is_honeypot") == "1":
            return 0, ["🚨 HONEYPOT SOL"]

        # Mintable authority
        if dati.get("mintable") == "1":
            score -= 25
            problemi.append("⚠️ Mint authority attiva")

        # Freeze authority
        if dati.get("freezeable") == "1":
            score -= 30
            problemi.append("⚠️ Freeze authority attiva")

        # Top holder concentration
        top10 = float(dati.get("top_10_holder_rate", 0) or 0) * 100
        if top10 > 80:
            return 0, [f"🚨 Top 10 holder hanno {top10:.0f}% supply"]
        if top10 > 50:
            score -= 20
            problemi.append(f"⚠️ Top 10 holder: {top10:.0f}%")
        else:
            problemi.append(f"✅ Top 10 holder: {top10:.0f}%")

        if not problemi:
            problemi.append("✅ GoPlus SOL: ok")

        return max(0, score), problemi

    except Exception as e:
        print(f"GoPlus SOL error: {e}")
        return 50, ["⚠️ GoPlus SOL non disponibile"]

def check_duplicati(nome, chain_id):
    """Controlla se esistono molti token con lo stesso nome - segnale di scam"""
    try:
        url = f"https://api.dexscreener.com/latest/dex/search?q={nome}"
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return False
        pairs = r.json().get("pairs", [])
        # Filtra per chain
        stessa_chain = [p for p in pairs if p.get("chainId") == chain_id]
        # Se ci sono più di 3 token con lo stesso nome è sospetto
        if len(stessa_chain) > 3:
            print(f"  ⚠️ Trovati {len(stessa_chain)} token con nome '{nome}' - possibile scam")
            return True
        return False
    except:
        return False

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
        pairs = r.json().get("pairs")
        if not pairs:
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

        # Filtri base
        if liquidita < MIN_LIQUIDITA_USD:
            return False
        if volume < MIN_VOLUME_24H_USD:
            return False
        if eta_ore > MAX_ETA_ORE:
            return False

        # Check duplicati nome
        chain_id = "ethereum" if chain == "ETH" else "solana"
        if check_duplicati(nome, chain_id):
            print(f"  ❌ {simbolo} scartato - nome duplicato (possibile scam)")
            return False

        # Check sicurezza
        print(f"  🔍 Analizzo {simbolo} ({chain})...")
        if chain == "ETH":
            score, problemi = check_goplus_eth(address)
            link_dex = f"https://www.dextools.io/app/en/ether/pair-explorer/{pair_address}"
            link_scan = f"https://etherscan.io/token/{address}"
        else:
            score, problemi = check_goplus_sol(address)
            link_dex = f"https://www.dextools.io/app/en/solana/pair-explorer/{pair_address}"
            link_scan = f"https://solscan.io/token/{address}"

        if score < MIN_SICUREZZA_SCORE:
            print(f"  ❌ {simbolo} scartato - score {score}/100")
            return False

        # Token passato tutti i filtri!
        emoji = "🟢" if score >= 90 else "🟡"
        chain_emoji = "🔷" if chain == "ETH" else "🟣"
        problemi_testo = "\n".join(problemi)

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

⚠️ <i>DYOR - Verifica sempre prima di comprare!</i>"""

        invia_telegram(messaggio)
        return True

    except Exception as e:
        print(f"Errore analisi: {e}")
        return False

def main():
    print("CRYPTO SCANNER BOT v3 AVVIATO")
    invia_telegram("🤖 <b>Bot v3 avviato!</b>\n🛡 GoPlus + Anti-duplicati\n⚙️ Filtri più severi attivi\nMonitoro ETH e SOL...")
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

