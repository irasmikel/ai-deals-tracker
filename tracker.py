import os
import re
import time
import requests
import feedparser

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SEND_SUMMARY = os.environ.get("SEND_SUMMARY") == "1"  # heartbeat opcional por Telegram
HISTORY_FILE = "sent_links.txt"
DELAY_BETWEEN_FEEDS = 2  # segundos entre peticiones a feeds, para evitar 429 (esp. Reddit)

# Cada feed es (url, nº de entradas recientes a revisar). Los feeds generales
# (todo el sitio) rotan más rápido, así que se revisan más entradas.
FEEDS = [
    # Chollometro (España) — la red Pepper (Chollometro/HotUKDeals/Dealabs)
    # bloquea la búsqueda por palabra clave a bots (robots.txt) y no existe
    # endpoint /rss/search. Usamos el feed general y filtramos aquí por
    # keywords (KEYWORD_PATTERN más abajo).
    ("https://www.chollometro.com/rss", 20),

    # HotUKDeals (UK / Global) — mismo motivo que arriba, feed general.
    ("https://www.hotukdeals.com/rss", 20),

    # Slickdeals (EE.UU.) — SÍ soporta búsqueda real por RSS.
    ("https://slickdeals.net/newsearch.php?rss=1&q=chatgpt&searcharea=deals&searchin=first", 8),
    ("https://slickdeals.net/newsearch.php?rss=1&q=gemini+ai&searcharea=deals&searchin=first", 8),
    ("https://slickdeals.net/newsearch.php?rss=1&q=claude+ai&searcharea=deals&searchin=first", 8),
    ("https://slickdeals.net/newsearch.php?rss=1&q=perplexity&searcharea=deals&searchin=first", 8),
    ("https://slickdeals.net/newsearch.php?rss=1&q=copilot&searcharea=deals&searchin=first", 8),

    # Hacker News (vía hnrss.org, usa la API de Algolia por debajo — estable,
    # sin bloqueo anti-bot).
    ("https://hnrss.org/newest?q=free%20chatgpt", 8),
    ("https://hnrss.org/newest?q=free%20claude", 8),
    ("https://hnrss.org/newest?q=free%20credits%20AI", 8),

    # OpenAI News oficial — bajo volumen, pero fuente de calidad para
    # anuncios oficiales de créditos/promos.
    ("https://openai.com/news/rss.xml", 6),

    # Reddit
    # NOTA: desde mayo de 2026 Reddit devuelve 403/429 con más facilidad a
    # peticiones anónimas desde IPs de datacenter (como las de GitHub
    # Actions). Con la pausa entre feeds (DELAY_BETWEEN_FEEDS) debería
    # reducirse el 429, pero si sigue fallando de forma sistemática, es ese
    # bloqueo y no un bug local.
    ("https://www.reddit.com/r/ChatGPT/search.rss?q=free+OR+discount+OR+promo+OR+credits&sort=new&restrict_sr=1", 6),
    ("https://www.reddit.com/r/OpenAI/search.rss?q=free+OR+discount+OR+promo+OR+credits&sort=new&restrict_sr=1", 6),
    ("https://www.reddit.com/r/ClaudeAI/search.rss?q=free+OR+discount+OR+promo+OR+credits&sort=new&restrict_sr=1", 6),
    ("https://www.reddit.com/r/PerplexityAI/search.rss?q=free+OR+discount+OR+promo+OR+pro&sort=new&restrict_sr=1", 6),
    ("https://www.reddit.com/r/cursor/search.rss?q=free+OR+discount+OR+credits+OR+pro&sort=new&restrict_sr=1", 6),
    ("https://www.reddit.com/r/ArtificialInteligence/search.rss?q=free+OR+discount+OR+promo&sort=new&restrict_sr=1", 6),
]

# Palabras completas (con límites de palabra) para evitar falsos positivos
# tipo "off" -> "office", "coffee", "official"...
KEYWORDS = {
    "free", "gratis", "discount", "descuento", "promo", "code", "código",
    "coupon", "cupón", "credit", "crédito", "credits", "trial", "off",
    "oferta", "chollo", "chatgpt", "claude", "gemini", "perplexity",
    "copilot", "cursor"
}
KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in KEYWORDS) + r")\b",
    re.IGNORECASE
)

# Errores de Gemini que merece la pena tratar cambiando de modelo
# (cuota agotada o modelo saturado/caído temporalmente).
RETRYABLE_MARKERS = ("RESOURCE_EXHAUSTED", "UNAVAILABLE", "INTERNAL")


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def save_link(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(link + "\n")


def is_potential_deal(title, summary):
    text = f"{title} {summary}"
    return bool(KEYWORD_PATTERN.search(text))


def get_available_models():
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        available = [
            m["name"] for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
        priority = [
            "models/gemini-3.7-flash",
            "models/gemini-3.5-flash",
            "models/gemini-3.5-flash-lite",
            "models/gemini-flash-latest",
            "models/gemini-3.6-flash"
        ]
        models = [m for m in priority if m in available]
        return models if models else available
    except Exception as e:
        print(f"Error listando modelos: {e}")
        return ["models/gemini-3.5-flash"]


def query_gemini(model_path, title, summary):
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_path}:generateContent?key={GEMINI_API_KEY}"
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

    resp = requests.post(url, json=payload, timeout=30)
    data = resp.json()

    if resp.status_code == 429 or any(m in str(data) for m in RETRYABLE_MARKERS):
        return "RETRYABLE_ERROR"

    if "candidates" in data and len(data["candidates"]) > 0:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    print(f"⚠️ Respuesta inesperada de Gemini ({model_path}): {str(data)[:300]}")
    return "ERROR"


def analyze_deal_with_fallback(models, title, summary):
    for model in list(models):
        res = query_gemini(model, title, summary)
        if res == "RETRYABLE_ERROR":
            print(f"⚠️ {model} no disponible ahora mismo (cuota/saturación). Probando siguiente modelo...")
            models.remove(model)
            continue
        return res
    return "ERROR"


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
    if resp.status_code != 200:
        payload["text"] = f"{formatted_text}\n\nEnlace: {link}".replace("*", "")
        payload.pop("parse_mode", None)
        requests.post(url, json=payload, timeout=10)


def send_summary(stats):
    if not (SEND_SUMMARY and BOT_TOKEN and CHAT_ID):
        return
    text = (
        "📊 *Resumen del rastreo*\n\n"
        f"• Feeds OK: {stats['feeds_ok']}/{stats['feeds_total']}\n"
        f"• Feeds con error/bloqueo: {stats['feeds_error']}\n"
        f"• Entradas nuevas revisadas: {stats['new_entries']}\n"
        f"• Candidatos analizados con IA: {stats['candidates']}\n"
        f"• Fallos de análisis (IA): {stats['ai_errors']}\n"
        f"• Chollos enviados: {stats['deals_sent']}"
    )
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)


def main():
    if not BOT_TOKEN or not CHAT_ID or not GEMINI_API_KEY:
        print("❌ Faltan variables de entorno.")
        return

    models = get_available_models()
    print(f"🚀 Modelos en cola de uso: {models}")

    seen_links = load_history()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AIDealsTracker/1.0"}

    stats = {
        "feeds_total": len(FEEDS),
        "feeds_ok": 0,
        "feeds_error": 0,
        "new_entries": 0,
        "candidates": 0,
        "ai_errors": 0,
        "deals_sent": 0,
    }

    for feed_url, entry_limit in FEEDS:
        time.sleep(DELAY_BETWEEN_FEEDS)  # evita ráfagas -> menos 429
        try:
            resp = requests.get(feed_url, headers=headers, timeout=12)
            feed = feedparser.parse(resp.content)

            if resp.status_code != 200 or not feed.entries:
                stats["feeds_error"] += 1
                print(f"⚠️ [{feed_url}] status={resp.status_code} entradas={len(feed.entries)} "
                      f"→ posible bloqueo (403/429/anti-bot), endpoint incorrecto o feed vacío")
                continue

            stats["feeds_ok"] += 1
            new_in_feed = 0

            for entry in feed.entries[:entry_limit]:
                link = getattr(entry, "link", "")
                if not link or link in seen_links:
                    continue

                new_in_feed += 1
                stats["new_entries"] += 1

                title = getattr(entry, "title", "")
                summary = getattr(entry, "summary", "")

                # 1. Filtro previo sin gastar llamadas de IA
                if not is_potential_deal(title, summary):
                    save_link(link)
                    seen_links.add(link)
                    continue

                # 2. Análisis con IA solo si tiene indicios de oferta
                print(f"🔍 Analizando candidato: {title[:45]}...")
                stats["candidates"] += 1
                result = analyze_deal_with_fallback(models, title, summary)

                if result == "ERROR":
                    # No se marca como visto: se reintentará en la próxima
                    # ejecución (podría ser un fallo temporal de la API).
                    stats["ai_errors"] += 1
                    print(f"❌ Fallo de análisis IA para: {title[:45]} (se reintentará)")
                    continue

                if "NO_OFERTA" not in result:
                    send_telegram(result, link)
                    stats["deals_sent"] += 1
                    time.sleep(2)

                save_link(link)
                seen_links.add(link)
                time.sleep(3)  # Pausa entre llamadas para no superar el rate limit de Gemini

            print(f"   → [{feed_url}] {len(feed.entries)} entradas, {new_in_feed} nuevas")

        except Exception as e:
            stats["feeds_error"] += 1
            print(f"❌ Error en feed {feed_url}: {e}")

    print(
        "\n📊 Resumen: "
        f"feeds_ok={stats['feeds_ok']}/{stats['feeds_total']}, "
        f"feeds_error={stats['feeds_error']}, "
        f"nuevas={stats['new_entries']}, "
        f"candidatos={stats['candidates']}, "
        f"errores_ia={stats['ai_errors']}, "
        f"chollos_enviados={stats['deals_sent']}"
    )

    send_summary(stats)


if __name__ == "__main__":
    main()
