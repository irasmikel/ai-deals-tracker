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
    # NOTA: desde mayo de 2026 Reddit bloquea con 403 el acceso anónimo a
    # .json/.rss desde IPs de datacenter (incluidas las de GitHub Actions),
    # incluso con headers de navegador. Si estos feeds fallan sistemáticamente
    # en el log ("bloqueado/HTTP != 200"), es ese bloqueo y no un bug local.
    "https://www.reddit.com/r/ChatGPT/search.rss?q=free+OR+discount+OR+promo+OR+credits&sort=new&restrict_sr=1",
    "https://www.reddit.com/r/OpenAI/search.rss?q=free+OR+discount+OR+promo+OR+credits&sort=new&restrict_sr=1",
    "https://www.reddit.com/r/ClaudeAI/search.rss?q=free+OR+discount+OR+promo+OR+credits&sort=new&restrict_sr=1",
    "https://www.reddit.com/r/PerplexityAI/search.rss?q=free+OR+discount+OR+promo+OR+pro&sort=new&restrict_sr=1",
    "https://www.reddit.com/r/cursor/search.rss?q=free+OR+discount+OR+credits+OR+pro&sort=new&restrict_sr=1",
    "https://www.reddit.com/r/ArtificialInteligence/search.rss?q=free+OR+discount+OR+promo&sort=new&restrict_sr=1",
]

# Palabras completas (con límites de palabra) para evitar falsos positivos
# tipo "off" -> "office", "coffee", "official"...
KEYWORDS = {
    "free", "gratis", "discount", "descuento", "promo", "code", "código",
    "coupon", "cupón", "credit", "crédito", "trial", "off", "oferta", "chollo"
}
KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in KEYWORDS) + r")\b",
    re.IGNORECASE
)


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

    if resp.status_code == 429 or "RESOURCE_EXHAUSTED" in str(data):
        return "QUOTA_EXCEEDED"

    if "candidates" in data and len(data["candidates"]) > 0:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    print(f"⚠️ Respuesta inesperada de Gemini ({model_path}): {str(data)[:300]}")
    return "ERROR"


def analyze_deal_with_fallback(models, title, summary):
    for model in list(models):
        res = query_gemini(model, title, summary)
        if res == "QUOTA_EXCEEDED":
            print(f"⚠️ Cuota agotada en {model}. Descartando este modelo...")
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

    for feed_url in FEEDS:
        try:
            resp = requests.get(feed_url, headers=headers, timeout=12)
            feed = feedparser.parse(resp.content)

            if resp.status_code != 200 or not feed.entries:
                stats["feeds_error"] += 1
                print(f"⚠️ [{feed_url}] status={resp.status_code} entradas={len(feed.entries)} "
                      f"→ posible bloqueo (403/anti-bot) o feed vacío")
                continue

            stats["feeds_ok"] += 1
            new_in_feed = 0

            for entry in feed.entries[:6]:
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
                time.sleep(3)  # Pausa entre llamadas para no superar 5 peticiones/min

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
