import os
import time
import requests
import feedparser

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
HISTORY_FILE = "sent_links.txt"

FEEDS = [
    # Chollometro (España)
    "https://www.chollometro.com/rss/search?q=chatgpt",
    "https://www.chollometro.com/rss/search?q=claude",
    "https://www.chollometro.com/rss/search?q=gemini",
    "https://www.chollometro.com/rss/search?q=grok",
    "https://www.chollometro.com/rss/search?q=perplexity",
    "https://www.chollometro.com/rss/search?q=copilot",

    # HotUKDeals (UK / Global)
    "https://www.hotukdeals.com/rss/search?q=chatgpt",
    "https://www.hotukdeals.com/rss/search?q=gemini",
    "https://www.hotukdeals.com/rss/search?q=perplexity",

    # Reddit
    "https://www.reddit.com/r/ChatGPT/search.rss?q=free+OR+discount+OR+promo+OR+credits&sort=new&restrict_sr=1",
    "https://www.reddit.com/r/OpenAI/search.rss?q=free+OR+discount+OR+promo+OR+credits&sort=new&restrict_sr=1",
    "https://www.reddit.com/r/ClaudeAI/search.rss?q=free+OR+discount+OR+promo+OR+credits&sort=new&restrict_sr=1",
    "https://www.reddit.com/r/PerplexityAI/search.rss?q=free+OR+discount+OR+promo+OR+pro&sort=new&restrict_sr=1",
    "https://www.reddit.com/r/cursor/search.rss?q=free+OR+discount+OR+credits+OR+pro&sort=new&restrict_sr=1",
    "https://www.reddit.com/r/ArtificialInteligence/search.rss?q=free+OR+discount+OR+promo&sort=new&restrict_sr=1",
]

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_link(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(link + "\n")

def analyze_deal_with_gemini(title, summary):
    # Modelo oficial estable
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    Eres un detector de ofertas de Inteligencia Artificial (ChatGPT, Claude, Gemini, Grok, Perplexity, Cursor, Copilot, etc.).
    Analiza este post y determina si es una oferta/descuento/crédito real o solo una pregunta/duda/problema/spam.

    Título: {title}
    Contenido: {summary[:600]}

    REGLAS:
    1. Si es una duda de usuario, consulta técnica, debate o reventa ilegal: responde ÚNICAMENTE con la palabra NO_OFERTA.
    2. Si es una OFERTA REAL, DESCUENTO o CRÉDITO GRATIS, responde EXACTAMENTE con este formato:

    🚨 *CHOLLO IA: [Título breve y directo]*

    • *Servicio:* [Nombre de la plataforma]
    • *Beneficio:* [Meses gratis, descuento o saldo de crédito]
    • *Requisitos:* [Condiciones, país o cupón]
    • *Instrucciones:* [Paso a paso para canjearlo]
    """

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1}
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        data = resp.json()
        
        if "error" in data:
            print(f"Error API Gemini ({resp.status_code}): {data['error'].get('message', data['error'])}")
            return "NO_OFERTA"

        if "candidates" in data and len(data["candidates"]) > 0:
            candidate = data["candidates"][0]
            if "content" in candidate and "parts" in candidate["content"]:
                return candidate["content"]["parts"][0]["text"].strip()

        print(f"Respuesta inesperada de Gemini: {data}")
        return "NO_OFERTA"

    except Exception as e:
        print(f"Error con Gemini: {e}")
        return "NO_OFERTA"

def send_telegram(formatted_text, link):
    message = f"{formatted_text}\n\n🔗 [Ver publicación original]({link})"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    
    resp = requests.post(url, json=payload, timeout=10)
    # Fallback si Telegram rechaza el formato Markdown por caracteres especiales
    if resp.status_code != 200:
        plain_text = f"{formatted_text}\n\nEnlace: {link}".replace("*", "")
        payload["text"] = plain_text
        payload.pop("parse_mode", None)
        requests.post(url, json=payload, timeout=10)

def main():
    if not BOT_TOKEN or not CHAT_ID or not GEMINI_API_KEY:
        print("Faltan variables de entorno necesarias.")
        return

    seen_links = load_history()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AIDealsTracker/1.0"}

    for feed_url in FEEDS:
        try:
            resp = requests.get(feed_url, headers=headers, timeout=12)
            feed = feedparser.parse(resp.content)

            for entry in feed.entries[:8]:
                link = getattr(entry, "link", "")
                if not link or link in seen_links:
                    continue

                title = getattr(entry, "title", "")
                summary = getattr(entry, "summary", "")

                analysis = analyze_deal_with_gemini(title, summary)

                if "NO_OFERTA" not in analysis:
                    send_telegram(analysis, link)
                    time.sleep(1)

                save_link(link)
                seen_links.add(link)

        except Exception as e:
            print(f"Error procesando {feed_url}: {e}")

if __name__ == "__main__":
    main()
