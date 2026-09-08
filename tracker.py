import os
import re
import json
import html
import time
import calendar
import requests
import feedparser
from datetime import datetime, timedelta
from urllib.parse import urlparse

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SEND_SUMMARY = os.environ.get("SEND_SUMMARY") == "1"

# Confianza mínima (0-1) para enviar una oferta.
MIN_CONFIDENCE = float(os.environ.get("MIN_CONFIDENCE", "0.7"))

# Regiones de interés separadas por coma (ej. "españa,spain,europa,eu,global").
# Vacío = no filtrar por región.
MY_REGIONS = {
    r.strip().lower()
    for r in os.environ.get("MY_REGIONS", "").split(",")
    if r.strip()
}

# Modelos preferidos en orden. Sobreescribible con GEMINI_MODELS="models/a,models/b".
DEFAULT_MODEL_PRIORITY = [
    "models/gemini-3.7-flash",
    "models/gemini-3.5-flash",
    "models/gemini-3.5-flash-lite",
    "models/gemini-flash-latest",
    "models/gemini-3.6-flash",
]

HISTORY_FILE = "sent_links.txt"          # enlaces ya procesados
RECENT_DEALS_FILE = "recent_deals.json"  # ofertas recientes -> dedup semántica
FAILED_FILE = "failed_links.json"        # enlaces fallidos en IA y nº intentos

DELAY_BETWEEN_FEEDS = 2      # seg entre feeds (evita 429)
GEMINI_PAUSE = 3             # seg entre llamadas a Gemini
MAX_ENTRY_AGE_HOURS = 72     # descarta entradas más viejas
DEDUP_DAYS = 14              # memoria de ofertas enviadas
MAX_ATTEMPTS = 3             # intentos de IA por enlace
SUMMARY_CHARS = 800          # caracteres de contenido enviados a Gemini

# (url, nº de entradas recientes a revisar)
FEEDS = [
    # Chollometro / HotUKDeals: feed general (Pepper bloquea /rss/search a bots)
    ("https://www.chollometro.com/rss", 30),
    ("https://www.hotukdeals.com/rss", 30),

    # Slickdeals (EE.UU.)
    ("https://slickdeals.net/newsearch.php?rss=1&q=chatgpt&searcharea=deals&searchin=first", 8),
    ("https://slickdeals.net/newsearch.php?rss=1&q=gemini+ai&searcharea=deals&searchin=first", 8),
    ("https://slickdeals.net/newsearch.php?rss=1&q=claude+ai&searcharea=deals&searchin=first", 8),
    ("https://slickdeals.net/newsearch.php?rss=1&q=perplexity&searcharea=deals&searchin=first", 8),
    ("https://slickdeals.net/newsearch.php?rss=1&q=copilot&searcharea=deals&searchin=first", 8),

    # Hacker News
    ("https://hnrss.org/newest?q=free%20chatgpt", 8),
    ("https://hnrss.org/newest?q=free%20claude", 8),
    ("https://hnrss.org/newest?q=free%20credits%20AI", 8),

    # OpenAI News oficial
    ("https://openai.com/news/rss.xml", 10),

    # Reddit (puede dar 403/429 desde IPs de datacenter)
    ("https://www.reddit.com/r/ChatGPT/search.rss?q=free+OR+discount+OR+promo+OR+credits&sort=new&restrict_sr=1", 6),
    ("https://www.reddit.com/r/OpenAI/search.rss?q=free+OR+discount+OR+promo+OR+credits&sort=new&restrict_sr=1", 6),
    ("https://www.reddit.com/r/ClaudeAI/search.rss?q=free+OR+discount+OR+promo+OR+credits&sort=new&restrict_sr=1", 6),
    ("https://www.reddit.com/r/PerplexityAI/search.rss?q=free+OR+discount+OR+promo+OR+pro&sort=new&restrict_sr=1", 6),
    ("https://www.reddit.com/r/cursor/search.rss?q=free+OR+discount+OR+credits+OR+pro&sort=new&restrict_sr=1", 6),
    ("https://www.reddit.com/r/ArtificialInteligence/search.rss?q=free+OR+discount+OR+promo&sort=new&restrict_sr=1", 6),
]

AI_BRANDS = {
    "chatgpt", "chat gpt", "gpt-4", "gpt-5", "gpt4", "gpt5", "openai",
    "claude", "anthropic", "gemini", "perplexity", "copilot", "cursor",
    "grok", "midjourney", "deepseek", "chatbot", "mistral", "le chat",
}
BRAND_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in AI_BRANDS) + r")\b", re.IGNORECASE
)

EXCLUDE_TERMS = {
    "laptop", "portátil", "portatil", "ordenador", "pc", "tablet",
    "chromebook", "tv", "televisor", "monitor", "auriculares",
    "headphones", "earbuds", "earphone", "gafas", "glasses", "smartwatch",
    "reloj", "watch", "dron", "drone", "aspirador", "vacuum", "batidora",
    "blender", "cámara", "camara", "camera", "smartphone", "teléfono",
    "telefono", "phone", "altavoz", "speaker", "ratón", "raton", "mouse",
    "teclado", "keyboard", "zapatillas", "sneaker", "chocolate"
}
EXCLUDE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in EXCLUDE_TERMS) + r")\b", re.IGNORECASE
)

RETRYABLE_MARKERS = ("RESOURCE_EXHAUSTED", "UNAVAILABLE", "INTERNAL")

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "es_oferta": {"type": "boolean"},
        "confianza": {"type": "number"},
        "es_duplicado": {"type": "boolean"},
        "titulo": {"type": "string"},
        "servicio": {"type": "string"},
        "beneficio": {"type": "string"},
        "requisitos": {"type": "string"},
        "instrucciones": {"type": "string"},
        "paises": {"type": "string"},
        "caducidad": {"type": "string"},
    },
    "required": ["es_oferta", "confianza", "es_duplicado"],
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AIDealsTracker/2.0"}
# =========================================================
# PERSISTENCIA
# =========================================================
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def save_link(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(link + "\n")


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ No se pudo leer {path}: {e}")
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_recent_deals():
    """Ofertas enviadas en los últimos DEDUP_DAYS días (dedup semántica)."""
    deals = load_json(RECENT_DEALS_FILE, [])
    cutoff = datetime.utcnow() - timedelta(days=DEDUP_DAYS)
    fresh = []
    for d in deals:
        try:
            if datetime.fromisoformat(d["sent_at"]) >= cutoff:
                fresh.append(d)
        except Exception:
            continue
    return fresh


def add_recent_deal(recent_deals, deal, link, source):
    recent_deals.append({
        "servicio": deal.get("servicio", ""),
        "beneficio": deal.get("beneficio", ""),
        "titulo": deal.get("titulo", ""),
        "link": link,
        "source": source,
        "sent_at": datetime.utcnow().isoformat(),
    })
    save_json(RECENT_DEALS_FILE, recent_deals)


def register_failure(failed, link):
    """Suma un intento fallido. True si se agotaron los intentos."""
    failed[link] = failed.get(link, 0) + 1
    save_json(FAILED_FILE, failed)
    return failed[link] >= MAX_ATTEMPTS


def clear_failure(failed, link):
    if link in failed:
        del failed[link]
        save_json(FAILED_FILE, failed)


# =========================================================
# FILTROS PREVIOS (sin gastar IA)
# =========================================================
def clean_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def is_potential_deal(title, summary):
    text = f"{title} {summary}"
    if EXCLUDE_PATTERN.search(text):
        return False
    return bool(BRAND_PATTERN.search(text))


def is_recent(entry):
    struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not struct:
        return True
    age_hours = (time.time() - calendar.timegm(struct)) / 3600
    return age_hours <= MAX_ENTRY_AGE_HOURS


def source_name(feed_url):
    host = urlparse(feed_url).netloc.replace("www.", "")
    if "reddit.com" in host:
        m = re.search(r"/r/([^/]+)/", feed_url)
        return f"Reddit r/{m.group(1)}" if m else "Reddit"
    return {
        "chollometro.com": "Chollometro",
        "hotukdeals.com": "HotUKDeals",
        "slickdeals.net": "Slickdeals",
        "hnrss.org": "Hacker News",
        "openai.com": "OpenAI News",
    }.get(host, host)


def passes_region_filter(paises):
    """Si MY_REGIONS está vacío, todo pasa. Si la oferta no indica país, pasa."""
    if not MY_REGIONS:
        return True
    p = (paises or "").strip().lower()
    if not p or p in {"desconocido", "unknown", "n/a", "-"}:
        return True
    return any(region in p for region in MY_REGIONS)


def fetch_feed(feed_url):
    """Descarga el feed con un reintento con backoff si hay 429/5xx."""
    for attempt in range(2):
        resp = requests.get(feed_url, headers=HEADERS, timeout=12)
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == 0:
                wait = 8
                ra = resp.headers.get("Retry-After")
                if ra and ra.isdigit():
                    wait = min(int(ra), 30)
                print(f"   ⏳ {resp.status_code} en {feed_url[:60]}... reintento en {wait}s")
                time.sleep(wait)
                continue
        return resp
    return resp


# =========================================================
# GEMINI
# =========================================================
def get_available_models():
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    env_models = [m.strip() for m in os.environ.get("GEMINI_MODELS", "").split(",") if m.strip()]
    priority = env_models or DEFAULT_MODEL_PRIORITY
    try:
        data = requests.get(url, timeout=10).json()
        available = [
            m["name"] for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
        models = [m for m in priority if m in available]
        if models:
            return models
        # Si ninguno de la lista existe, usa los flash disponibles
        flash = [m for m in available if "flash" in m]
        return flash or available or priority
    except Exception as e:
        print(f"Error listando modelos: {e}")
        return priority


def build_prompt(title, summary, recent_deals):
    recientes = "\n".join(
        f"- {d.get('servicio','?')}: {d.get('beneficio','?')} ({d.get('titulo','')})"
        for d in recent_deals[-25:]
    ) or "(ninguna)"
    return f"""
Eres un detector de ofertas de plataformas y servicios de Inteligencia Artificial
(ChatGPT, Claude, Gemini, Grok, Perplexity, Cursor, Copilot, Midjourney, DeepSeek, Mistral, etc.).

Analiza este post:
Título: {title}
Contenido: {summary[:SUMMARY_CHARS]}

Ofertas YA ENVIADAS en los últimos {DEDUP_DAYS} días:
{recientes}

Devuelve un JSON con estos campos:
- es_oferta: true SOLO si es una oferta real, legal y vigente de una SUSCRIPCIÓN, PLAN, CRÉDITOS
  o SERVICIO de IA (gratis, descuento, meses gratis, créditos, programa de estudiantes, bundle con
  operadora, etc.). false si es: duda, queja, debate, noticia sin promoción, tutorial, reventa de
  cuentas, claves compartidas, spam, o un DISPOSITIVO físico (portátil, móvil, gafas, TV...).
- confianza: número 0-1 de lo seguro que estás de que es una oferta real y aprovechable.
- es_duplicado: true si es la MISMA oferta (mismo servicio y mismo beneficio) que alguna ya enviada.
- titulo: máx 60 caracteres, directo (ej. "Perplexity Pro 1 año gratis con Movistar").
- servicio: nombre de la plataforma.
- beneficio: qué se consigue (meses gratis, % descuento, saldo de crédito...).
- requisitos: condiciones, cupón, tipo de cuenta necesaria.
- instrucciones: pasos breves para canjearlo.
- paises: países/regiones donde aplica ("España", "UK", "EE.UU.", "Global"...) o "desconocido".
- caducidad: fecha límite si se indica, o "desconocida".
Responde en español.
""".strip()


def query_gemini(model_path, prompt):
    """Devuelve dict con el JSON, o los strings 'RETRYABLE_ERROR' / 'ERROR'."""
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_path}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
        },
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
    except requests.RequestException as e:
        print(f"⚠️ Error de red con Gemini ({model_path}): {e}")
        return "RETRYABLE_ERROR"

    try:
        data = resp.json()
    except ValueError:
        print(f"⚠️ Gemini ({model_path}) devolvió no-JSON: status={resp.status_code} {resp.text[:200]}")
        return "RETRYABLE_ERROR" if resp.status_code in (429, 500, 502, 503, 504) else "ERROR"

    if resp.status_code == 429 or any(m in str(data) for m in RETRYABLE_MARKERS):
        return "RETRYABLE_ERROR"

    try:
        candidate = data["candidates"][0]
        if candidate.get("finishReason") == "SAFETY":
            print(f"⚠️ Gemini bloqueó por SAFETY: {str(data)[:200]}")
            return "ERROR"
        text = candidate["content"]["parts"][0]["text"].strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)  # por si envuelve en ```json
        result = json.loads(text)
        if not isinstance(result, dict) or "es_oferta" not in result:
            raise ValueError("JSON sin campos esperados")
        return result
    except Exception as e:
        print(f"⚠️ Respuesta inesperada de Gemini ({model_path}): {e} | {str(data)[:300]}")
        return "ERROR"


def analyze_deal_with_fallback(models, prompt):
    for model in list(models):
        res = query_gemini(model, prompt)
        if res == "RETRYABLE_ERROR":
            print(f"⚠️ {model} no disponible (cuota/saturación). Probando siguiente...")
            models.remove(model)
            continue
        return res
    return "ERROR"
    # =========================================================
# TELEGRAM
# =========================================================
def esc(text):
    """Escapa texto para parse_mode=HTML de Telegram."""
    return html.escape(str(text or ""), quote=False)


def build_message(deal, link, source):
    lines = [f"🚨 <b>CHOLLO IA: {esc(deal.get('titulo') or deal.get('servicio') or 'Oferta')}</b>", ""]
    fields = [
        ("Servicio", deal.get("servicio")),
        ("Beneficio", deal.get("beneficio")),
        ("Requisitos", deal.get("requisitos")),
        ("Instrucciones", deal.get("instrucciones")),
        ("Países", deal.get("paises")),
        ("Caducidad", deal.get("caducidad")),
    ]
    for label, value in fields:
        v = (value or "").strip()
        if v and v.lower() not in {"desconocido", "desconocida", "unknown", "n/a", "-"}:
            lines.append(f"• <b>{label}:</b> {esc(v)}")
    conf = deal.get("confianza")
    conf_txt = f" · confianza {int(round(float(conf) * 100))}%" if isinstance(conf, (int, float)) else ""
    lines.append("")
    lines.append(f"📌 Fuente: {esc(source)}{conf_txt}")
    lines.append(f'🔗 <a href="{esc(link)}">Ver publicación original</a>')
    return "\n".join(lines)


def telegram_post(payload):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        return requests.post(url, json=payload, timeout=10)
    except requests.RequestException as e:
        print(f"❌ Error de red con Telegram: {e}")
        return None


def send_telegram(deal, link, source):
    text = build_message(deal, link, source)
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    resp = telegram_post(payload)
    if resp is not None and resp.status_code == 200:
        return True

    # Fallback: texto plano sin etiquetas
    plain = re.sub(r"<[^>]+>", "", text)
    plain = html.unescape(plain) + f"\n\nEnlace: {link}"
    payload = {"chat_id": CHAT_ID, "text": plain, "disable_web_page_preview": False}
    resp = telegram_post(payload)
    ok = resp is not None and resp.status_code == 200
    if not ok:
        print(f"❌ Telegram rechazó el mensaje: {getattr(resp, 'text', '')[:200]}")
    return ok


def send_summary(stats):
    if not (SEND_SUMMARY and BOT_TOKEN and CHAT_ID):
        return
    text = (
        "📊 <b>Resumen del rastreo</b>\n\n"
        f"• Feeds OK: {stats['feeds_ok']}/{stats['feeds_total']}\n"
        f"• Feeds con error/bloqueo: {stats['feeds_error']}\n"
        f"• Entradas nuevas revisadas: {stats['new_entries']}\n"
        f"• Descartadas por antigüedad: {stats['stale_skipped']}\n"
        f"• Candidatos analizados con IA: {stats['candidates']}\n"
        f"• Fallos de análisis (IA): {stats['ai_errors']}\n"
        f"• Descartados por confianza baja: {stats['low_conf']}\n"
        f"• Descartados por duplicado: {stats['duplicates']}\n"
        f"• Descartados por región: {stats['region_skipped']}\n"
        f"• Chollos enviados: {stats['deals_sent']}"
    )
    telegram_post({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})


# =========================================================
# MAIN
# =========================================================
def main():
    if not BOT_TOKEN or not CHAT_ID or not GEMINI_API_KEY:
        print("❌ Faltan variables de entorno.")
        return

    models = get_available_models()
    print(f"🚀 Modelos en cola de uso: {models}")
    if MY_REGIONS:
        print(f"🌍 Filtro de región activo: {sorted(MY_REGIONS)}")

    seen_links = load_history()
    recent_deals = load_recent_deals()
    failed = load_json(FAILED_FILE, {})

    stats = {
        "feeds_total": len(FEEDS), "feeds_ok": 0, "feeds_error": 0,
        "new_entries": 0, "stale_skipped": 0, "candidates": 0,
        "ai_errors": 0, "low_conf": 0, "duplicates": 0,
        "region_skipped": 0, "deals_sent": 0,
    }

    def mark_seen(link):
        save_link(link)
        seen_links.add(link)

    for feed_url, entry_limit in FEEDS:
        time.sleep(DELAY_BETWEEN_FEEDS)
        source = source_name(feed_url)
        try:
            resp = fetch_feed(feed_url)
            feed = feedparser.parse(resp.content)

            if resp.status_code != 200 or not feed.entries:
                stats["feeds_error"] += 1
                print(f"⚠️ [{source}] status={resp.status_code} entradas={len(feed.entries)} "
                      f"→ posible bloqueo, endpoint incorrecto o feed vacío")
                continue

            stats["feeds_ok"] += 1
            new_in_feed = 0

            for entry in feed.entries[:entry_limit]:
                link = getattr(entry, "link", "")
                if not link or link in seen_links:
                    continue

                if not is_recent(entry):
                    mark_seen(link)
                    stats["stale_skipped"] += 1
                    continue

                new_in_feed += 1
                stats["new_entries"] += 1

                title = clean_html(getattr(entry, "title", ""))
                summary = clean_html(getattr(entry, "summary", ""))

                # 1. Filtro barato: marca de IA presente y sin hardware
                if not is_potential_deal(title, summary):
                    mark_seen(link)
                    continue

                # 2. Sin modelos disponibles: no seguir gastando intentos
                if not models:
                    print("⛔ Ningún modelo de Gemini disponible; se pospone el resto de candidatos.")
                    break

                print(f"🔍 Analizando candidato [{source}]: {title[:50]}...")
                stats["candidates"] += 1
                result = analyze_deal_with_fallback(models, build_prompt(title, summary, recent_deals))
                time.sleep(GEMINI_PAUSE)

                if not isinstance(result, dict):
                    stats["ai_errors"] += 1
                    if register_failure(failed, link):
                        print(f"❌ Descartado tras {MAX_ATTEMPTS} fallos de IA: {title[:50]}")
                        mark_seen(link)
                    else:
                        print(f"❌ Fallo de análisis IA (se reintentará): {title[:50]}")
                    continue

                clear_failure(failed, link)

                try:
                    confianza = float(result.get("confianza", 0))
                except (TypeError, ValueError):
                    confianza = 0.0

                if not result.get("es_oferta"):
                    mark_seen(link)
                    continue

                if confianza < MIN_CONFIDENCE:
                    stats["low_conf"] += 1
                    print(f"   ↳ Confianza baja ({confianza:.2f}) — descartado: {title[:50]}")
                    mark_seen(link)
                    continue

                if result.get("es_duplicado"):
                    stats["duplicates"] += 1
                    print(f"   ↳ Duplicado de una oferta ya enviada: {title[:50]}")
                    mark_seen(link)
                    continue

                if not passes_region_filter(result.get("paises")):
                    stats["region_skipped"] += 1
                    print(f"   ↳ Fuera de tu región ({result.get('paises')}): {title[:50]}")
                    mark_seen(link)
                    continue

                if send_telegram(result, link, source):
                    stats["deals_sent"] += 1
                    add_recent_deal(recent_deals, result, link, source)
                    print(f"✅ Enviado: {result.get('titulo') or title[:50]}")
                    time.sleep(2)
                else:
                    # Si Telegram falla, no marcamos como visto para reintentar
                    continue

                mark_seen(link)

            print(f"   → [{source}] {len(feed.entries)} entradas, {new_in_feed} nuevas")

        except Exception as e:
            stats["feeds_error"] += 1
            print(f"❌ Error en feed [{source}] {feed_url}: {e}")

    print(
        "\n📊 Resumen: "
        f"feeds_ok={stats['feeds_ok']}/{stats['feeds_total']}, "
        f"feeds_error={stats['feeds_error']}, nuevas={stats['new_entries']}, "
        f"antiguas={stats['stale_skipped']}, candidatos={stats['candidates']}, "
        f"errores_ia={stats['ai_errors']}, conf_baja={stats['low_conf']}, "
        f"duplicados={stats['duplicates']}, region={stats['region_skipped']}, "
        f"enviados={stats['deals_sent']}"
    )
    send_summary(stats)


if __name__ == "__main__":
    main()
