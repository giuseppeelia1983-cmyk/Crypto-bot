import requests
import time
import os
import re
from datetime import datetime

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    print("ERRORE: Variabili mancanti!")
    exit(1)

INTERVALLO_CONTROLLO = 300  # ogni 5 minuti

# Subreddit da monitorare
SUBREDDITS = [
    "wallstreetbets",
    "cryptocurrency", 
    "solana",
    "ethfinance",
    "pennystocks",
    "stocks",
    "investing",
    "CryptoMoonShots"
]

# Parole chiave per date importanti
PAROLE_DATE = [
    "launch date", "listing date", "release date", "launch on",
    "listing on", "going live", "mainnet launch", "airdrop date",
    "unlock date", "earnings date", "ipo date", "token launch",
    "data di lancio", "lancio il", "listing il"
]

# Parole chiave buzz
PAROLE_BUZZ = [
    "to the moon", "100x", "gem", "next gamestop", "short squeeze",
    "buy the dip", "undervalued", "hidden gem", "early", "presale",
    "just launched", "new listing", "massive potential", "ape in"
]

post_visti = set()

def invia_telegram(messaggio):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": messaggio, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
        print("Alert inviato!")
    except Exception as e:
        print(f"Errore Telegram: {e}")

def fetch_reddit_hot(subreddit):
    """Prende i post hot di un subreddit"""
    try:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=25"
        headers = {"User-Agent": "CryptoSentimentBot/1.0"}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return []
        posts = r.json().get("data", {}).get("children", [])
        return [p.get("data", {}) for p in posts]
    except Exception as e:
        print(f"Errore Reddit {subreddit}: {e}")
        return []

def fetch_reddit_rising(subreddit):
    """Prende i post in crescita rapida"""
    try:
        url = f"https://www.reddit.com/r/{subreddit}/rising.json?limit=25"
        headers = {"User-Agent": "CryptoSentimentBot/1.0"}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return []
        posts = r.json().get("data", {}).get("children", [])
        return [p.get("data", {}) for p in posts]
    except Exception as e:
        print(f"Errore Reddit rising {subreddit}: {e}")
        return []

def estrai_ticker(testo):
    """Estrae ticker tipo $GME $BTC $SOL dal testo"""
    ticker = re.findall(r'\$([A-Z]{2,6})', testo)
    return list(set(ticker))

def estrai_date(testo):
    """Cerca menzioni di date importanti nel testo"""
    testo_lower = testo.lower()
    date_trovate = []
    
    for parola in PAROLE_DATE:
        if parola.lower() in testo_lower:
            # Cerca la data vicino alla parola chiave
            pattern = r'\b(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\b(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)\b'
            date = re.findall(pattern, testo_lower)
            if date:
                date_trovate.extend(date)
            else:
                date_trovate.append(f"data menzionata: '{parola}'")
    
    return list(set(date_trovate))

def conta_buzz_words(testo):
    """Conta quante parole buzz ci sono nel testo"""
    testo_lower = testo.lower()
    count = 0
    trovate = []
    for parola in PAROLE_BUZZ:
        if parola.lower() in testo_lower:
            count += 1
            trovate.append(parola)
    return count, trovate

def calcola_score_post(post):
    """Calcola quanto è interessante un post"""
    score = 0
    
    upvotes = post.get("ups", 0)
    commenti = post.get("num_comments", 0)
    ratio = post.get("upvote_ratio", 0)
    created = post.get("created_utc", 0)
    
    # Età del post in ore
    eta_ore = (time.time() - created) / 3600 if created else 999
    
    # Post troppo vecchi non interessano
    if eta_ore > 12:
        return 0
    
    # Punteggio basato su velocità crescita
    if upvotes > 10000:
        score += 50
    elif upvotes > 5000:
        score += 35
    elif upvotes > 1000:
        score += 20
    elif upvotes > 500:
        score += 10
    elif upvotes > 100:
        score += 5
    
    # Commenti = engagement
    if commenti > 1000:
        score += 30
    elif commenti > 500:
        score += 20
    elif commenti > 100:
        score += 10
    elif commenti > 50:
        score += 5
    
    # Post recenti bonus
    if eta_ore < 1:
        score += 20
    elif eta_ore < 3:
        score += 10
    
    # Ratio alto = consenso
    if ratio > 0.95:
        score += 10
    
    return score

def analizza_post(post, subreddit):
    """Analizza un singolo post e decide se mandare alert"""
    post_id = post.get("id", "")
    if not post_id or post_id in post_visti:
        return False
    
    titolo = post.get("title", "")
    testo = post.get("selftext", "")
    testo_completo = f"{titolo} {testo}"
    upvotes = post.get("ups", 0)
    commenti = post.get("num_comments", 0)
    url_post = f"https://reddit.com{post.get('permalink', '')}"
    created = post.get("created_utc", 0)
    eta_ore = (time.time() - created) / 3600 if created else 999

    # Calcola score
    score = calcola_score_post(post)
    if score < 15:
        return False

    post_visti.add(post_id)

    # Estrai info
    ticker = estrai_ticker(testo_completo)
    date_trovate = estrai_date(testo_completo)
    buzz_count, buzz_words = conta_buzz_words(testo_completo)

    # Deve avere almeno qualcosa di interessante
    if not ticker and not date_trovate and buzz_count < 2:
        return False

    # Componi messaggio
    emoji_score = "🔥" if score >= 50 else "📈" if score >= 30 else "👀"
    
    ticker_testo = " ".join([f"<b>${t}</b>" for t in ticker[:5]]) if ticker else "N/A"
    
    date_testo = ""
    if date_trovate:
        date_testo = f"\n📅 <b>DATE IMPORTANTI:</b>\n" + "\n".join([f"  • {d}" for d in date_trovate[:3]])
    
    buzz_testo = ""
    if buzz_words:
        buzz_testo = f"\n💬 <b>Buzz:</b> {', '.join(buzz_words[:3])}"

    messaggio = f"""{emoji_score} <b>BUZZ ALERT - r/{subreddit}</b>

📌 <b>{titolo[:100]}...</b>

🎯 Ticker: {ticker_testo}
⬆️ Upvotes: <b>{upvotes:,}</b>
💬 Commenti: <b>{commenti:,}</b>
⏱ Età: <b>{eta_ore:.1f} ore</b>
📊 Score: <b>{score}/100</b>{date_testo}{buzz_testo}

🔗 <a href="{url_post}">Apri su Reddit</a>

⚠️ <i>DYOR - Fai sempre le tue ricerche!</i>"""

    invia_telegram(messaggio)
    return True

def controlla_subreddit(subreddit):
    """Controlla hot e rising di un subreddit"""
    trovati = 0
    
    # Post hot
    for post in fetch_reddit_hot(subreddit):
        if analizza_post(post, subreddit):
            trovati += 1
            time.sleep(1)
    
    # Post in crescita
    for post in fetch_reddit_rising(subreddit):
        if analizza_post(post, subreddit):
            trovati += 1
            time.sleep(1)
    
    return trovati

def main():
    print("SENTIMENT BOT AVVIATO")
    invia_telegram("🤖 <b>Sentiment Bot avviato!</b>\n📊 Monitoro Reddit per buzz su crypto e titoli in borsa\n📅 Cerco date di lancio e listing\n🔥 Alert su post virali!")
    
    ciclo = 0
    while True:
        ciclo += 1
        ora = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{ora}] Ciclo #{ciclo} - Scansione Reddit...")
        
        trovati = 0
        for subreddit in SUBREDDITS:
            print(f"  📡 Scansiono r/{subreddit}...")
            trovati += controlla_subreddit(subreddit)
            time.sleep(2)
        
        print(f"  ✅ Trovati {trovati} post interessanti")
        print(f"  ⏳ Prossima scansione tra {INTERVALLO_CONTROLLO}s...")
        time.sleep(INTERVALLO_CONTROLLO)

if __name__ == "__main__":
    main()