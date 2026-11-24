#!/usr/bin/env python3
"""Recolecta los proyectos de IA que más crecen en GitHub y las noticias clave,
los resume en español con IA (GitHub Models, gratis) y guarda una edición en data/.

Solo usa la biblioteca estándar de Python: no hay que instalar nada.
"""
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EDITIONS = DATA / "ediciones"
HISTORY_FILE = DATA / "historial_estrellas.json"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
NOW = datetime.now(timezone.utc)
TODAY = NOW.date().isoformat()
UA = "radar-ia-bot/1.0"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

AI_WORDS = re.compile(
    r"\b(ai|a\.i\.|llms?|gpt[\w.-]*|chatgpt|claude|gemini|llama|openai|anthropic|deepmind|"
    r"mistral|deepseek|qwen|grok|copilot|agents?|agentic|mcp|rag|embeddings?|transformers?|"
    r"diffusion|neural|machine learning|deep learning|inference|fine-?tun\w*|hugging ?face|"
    r"vibe cod\w*|chatbots?|multimodal|reasoning model|language models?)\b",
    re.I,
)


def log(msg):
    print(msg, flush=True)


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def http(url, *, data=None, headers=None, timeout=30, retries=2, max_bytes=None):
    h = {"User-Agent": UA}
    h.update(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        h["Content-Type"] = "application/json"
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(max_bytes) if max_bytes else r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 500, 502, 503, 504) and attempt < retries:
                wait = int(e.headers.get("Retry-After") or 0) or 20 * (attempt + 1)
                log(f"    HTTP {e.code}; reintento en {min(wait, 90)} s")
                time.sleep(min(wait, 90))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < retries:
                time.sleep(5)
                continue
            raise


def gh_api(path, accept="application/vnd.github+json"):
    h = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return http("https://api.github.com" + path, headers=h)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def previous_editions(n):
    files = sorted(p for p in EDITIONS.glob("*.json") if p.stem != TODAY)
    return [load_json(p, {}) for p in files[-n:]] if n else []


# ---------------------------------------------------------------- IA (Google Gemini, plan gratuito)

_ai_state = {"enabled": bool(GEMINI_KEY) and CONFIG["ia"]["activada"], "calls": 0, "model": None}


def warn(msg):
    """Aviso visible en el resumen de la ejecución de GitHub Actions."""
    log(f"::warning::{msg}" if os.environ.get("GITHUB_ACTIONS") else f"AVISO: {msg}")


def pick_model():
    """Usa el modelo de config.json o, si es "auto", el Flash-Lite más reciente disponible."""
    wanted = CONFIG["ia"]["modelo"]
    if wanted and wanted != "auto":
        return wanted
    raw = http(f"{GEMINI_BASE}/models?pageSize=200", headers={"x-goog-api-key": GEMINI_KEY}, retries=1)
    names = [m["name"].removeprefix("models/") for m in json.loads(raw).get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]

    def version(name):
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
        return float(m.group(1)) if m else 0

    for family in ("flash-lite", "flash"):
        stable = [n for n in names if f"-{family}" in n and n.endswith(family)]
        candidates = stable or [n for n in names if f"-{family}" in n and "image" not in n and "tts" not in n]
        if candidates:
            return max(candidates, key=version)
    raise RuntimeError("no hay modelos Gemini Flash disponibles para esta clave")

SYSTEM_PROMPT = (
    "Eres editor de un diario de inteligencia artificial para desarrolladores hispanohablantes "
    "que construyen agentes, automatizaciones y productos SaaS. Escribes en español neutro, claro "
    "y profesional. No exageras, no usas clickbait y no inventas datos: si algo no está en el "
    "material, no lo afirmes. Respondes SOLO con un objeto JSON válido, sin texto adicional."
)


def ai_json(prompt, max_tokens=450):
    if not _ai_state["enabled"]:
        return None
    if not _ai_state["model"]:
        try:
            _ai_state["model"] = pick_model()
            log(f"    Modelo de IA: {_ai_state['model']}")
        except Exception as e:  # noqa: BLE001
            warn(f"IA desactivada: no se pudo elegir modelo de Gemini ({e}). Revisa el secreto GEMINI_API_KEY.")
            _ai_state["enabled"] = False
            return None
    if _ai_state["calls"]:
        time.sleep(CONFIG["ia"]["pausa_segundos"])
    _ai_state["calls"] += 1
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": max_tokens * 4,  # margen para modelos que "piensan" antes de responder
            "responseMimeType": "application/json",
        },
    }
    url = f"{GEMINI_BASE}/models/{_ai_state['model']}:generateContent"
    try:
        raw = http(url, data=payload, headers={"x-goog-api-key": GEMINI_KEY}, timeout=90, retries=2)
        data = json.loads(raw)
        parts = data["candidates"][0]["content"]["parts"]
        content = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        match = re.search(r"\{.*\}", content, re.S)
        return json.loads(match.group(0)) if match else None
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        log(f"    IA no disponible (HTTP {e.code}): {detail}")
        if e.code in (400, 401, 403, 404, 429):
            warn(f"IA desactivada en esta edición (HTTP {e.code}); se usan las descripciones originales.")
            _ai_state["enabled"] = False
    except Exception as e:  # noqa: BLE001 - la IA nunca debe tumbar la edición
        log(f"    Error de IA: {e}")
    return None


def valid_category(value, fallback_text):
    cats = CONFIG["categorias"]
    if isinstance(value, str):
        for c in cats:
            if c.lower() == value.strip().lower():
                return c
    return guess_category(fallback_text)


def guess_category(text):
    t = text.lower()
    rules = [
        ("Agentes", ["agent", "agentic", "mcp", "autonomous"]),
        ("RAG y datos", ["rag", "retrieval", "vector", "embedding", "knowledge base", "database"]),
        ("Imagen, audio y vídeo", ["image", "video", "audio", "speech", "voice", "tts", "diffusion", "vision"]),
        ("Automatización", ["automation", "workflow", "n8n", "zapier", "browser", "scraping", "rpa"]),
        ("Seguridad", ["security", "jailbreak", "vulnerab", "privacy", "attack"]),
        ("Infraestructura", ["inference", "serving", "gpu", "deploy", "kubernetes", "cluster", "datacenter"]),
        ("Modelos", ["model", "weights", "llama", "qwen", "mistral", "deepseek", "gemma", "fine-tun"]),
        ("Investigación", ["paper", "research", "benchmark", "arxiv"]),
        ("Negocio e industria", ["funding", "raises", "acquire", "billion", "startup", "lawsuit", "regulat"]),
    ]
    for cat, words in rules:
        if any(w in t for w in words):
            return cat
    return "Herramientas para devs"


def clean_text(s):
    return re.sub(r"\s+", " ", s or "").strip()


# ---------------------------------------------------------------- GitHub

def search_repos():
    cfg = CONFIG["github"]
    new_since = (NOW - timedelta(days=cfg["dias_repos_nuevos"])).date().isoformat()
    pushed_since = (NOW - timedelta(days=3)).date().isoformat()
    queries = []
    for topic in cfg["temas"]:
        queries.append(f"topic:{topic} created:>{new_since} stars:>={cfg['min_estrellas_nuevos']}")
        queries.append(f"topic:{topic} pushed:>{pushed_since} stars:>={cfg['min_estrellas_establecidos']}")
    pause = 2.5 if TOKEN else 7
    found, errors = {}, 0
    for i, q in enumerate(queries, 1):
        params = urllib.parse.urlencode({"q": q, "sort": "stars", "order": "desc", "per_page": 50})
        try:
            items = json.loads(gh_api(f"/search/repositories?{params}"))["items"]
            for it in items:
                found[it["full_name"].lower()] = it
            log(f"  [{i}/{len(queries)}] {q} → {len(items)}")
        except Exception as e:  # noqa: BLE001
            errors += 1
            log(f"  [{i}/{len(queries)}] ERROR {q}: {e}")
        time.sleep(pause)
    if errors == len(queries):
        raise RuntimeError("No se pudo consultar GitHub (todas las búsquedas fallaron).")
    return list(found.values())


def repo_ok(r):
    if r.get("fork") or r.get("archived") or r.get("disabled") or not r.get("description"):
        return False
    # Señal típica de estrellas compradas: muchísimas estrellas y casi ningún fork.
    if r["stargazers_count"] >= 300 and r.get("forks_count", 0) < r["stargazers_count"] * 0.01:
        return False
    text = " ".join([r["full_name"], r.get("description") or "", " ".join(r.get("topics") or [])]).lower()
    return not any(w in text for w in CONFIG["lista_negra"])


def fetch_readme(full_name):
    try:
        raw = gh_api(f"/repos/{full_name}/readme", accept="application/vnd.github.raw").decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""
    raw = re.sub(r"<!--.*?-->", " ", raw, flags=re.S)
    raw = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", raw)          # imágenes markdown
    raw = re.sub(r"<[^>]+>", " ", raw)                        # html
    raw = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", raw)        # enlaces → texto
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n", raw)
    return raw.strip()[:3500]


def collect_projects():
    cfg = CONFIG["github"]
    log("→ Buscando proyectos en GitHub…")
    repos = [r for r in search_repos() if repo_ok(r)]
    log(f"  {len(repos)} candidatos tras filtros")

    history = load_json(HISTORY_FILE, {})
    recent = {p["full_name"].lower() for ed in previous_editions(cfg["no_repetir_ediciones"]) for p in ed.get("proyectos", [])}

    scored = []
    for r in repos:
        key = r["full_name"].lower()
        stars = r["stargazers_count"]
        created = parse_date(r["created_at"])
        age_days = max((NOW - created).total_seconds() / 86400, 1)
        prev = history.get(key)
        speed, method = None, None
        if prev:
            days = (NOW - parse_date(prev["fecha"])).total_seconds() / 86400
            if days >= 0.8:
                speed, method = (stars - prev["estrellas"]) / days, "historial"
        if speed is None and age_days <= cfg["dias_repos_nuevos"]:
            speed, method = stars / age_days, "nuevo"
        # Actualiza el historial (sin pisar un registro de hace menos de ~20 h).
        if not prev or (NOW - parse_date(prev["fecha"])).total_seconds() > 72000:
            history[key] = {"estrellas": stars, "fecha": NOW.isoformat(timespec="seconds")}
        if speed is None or speed < cfg["min_estrellas_por_dia"] or key in recent:
            continue
        scored.append((speed, method, r))

    # Limpia del historial repos que no se ven desde hace más de 30 días.
    cutoff = NOW - timedelta(days=30)
    history = {k: v for k, v in history.items() if parse_date(v["fecha"]) >= cutoff}
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[: cfg["cantidad"]]
    log(f"  Seleccionados {len(top)} proyectos")

    projects = []
    for rank, (speed, method, r) in enumerate(top, 1):
        full = r["full_name"]
        log(f"  · #{rank} {full} (+{speed:.0f}★/día)")
        readme = fetch_readme(full)
        topics = r.get("topics") or []
        base_text = f"{full} {r.get('description') or ''} {' '.join(topics)}"
        ai = ai_json(
            f"Proyecto de GitHub: {full}\n"
            f"Descripción: {r.get('description')}\n"
            f"Lenguaje: {r.get('language')} · Estrellas: {r['stargazers_count']} · Temas: {', '.join(topics)}\n"
            f"Extracto del README:\n{readme}\n\n"
            "Devuelve un JSON con estas claves:\n"
            '"titular": titular en español de máximo 80 caracteres que diga qué es el proyecto (sin clickbait);\n'
            '"resumen": 2 o 3 frases en español sobre qué es y qué hace;\n'
            '"para_que_sirve": 1 frase concreta sobre cómo lo aprovecharía alguien que crea agentes, automatizaciones o SaaS;\n'
            f'"categoria": exactamente una de {json.dumps(CONFIG["categorias"], ensure_ascii=False)}.'
        ) or {}
        projects.append({
            "rank": rank,
            "full_name": full,
            "nombre": r["name"],
            "url": r["html_url"],
            "homepage": r.get("homepage") or "",
            "descripcion": clean_text(r.get("description")),
            "titular": clean_text(ai.get("titular")) or r["name"],
            "resumen": clean_text(ai.get("resumen")) or clean_text(r.get("description")),
            "para_que_sirve": clean_text(ai.get("para_que_sirve")),
            "categoria": valid_category(ai.get("categoria"), base_text),
            "estrellas": r["stargazers_count"],
            "estrellas_dia": round(speed),
            "metodo": method,
            "lenguaje": r.get("language") or "",
            "temas": topics[:6],
            "licencia": (r.get("license") or {}).get("spdx_id") or "",
            "creado": r["created_at"][:10],
            "resumido_con_ia": bool(ai),
        })
    return projects


# ---------------------------------------------------------------- Noticias

def norm_url(url):
    p = urllib.parse.urlsplit(url or "")
    host = p.netloc.lower().removeprefix("www.")
    return f"{host}{p.path.rstrip('/')}"


STOPWORDS = {"the", "and", "for", "with", "its", "from", "that", "this", "are", "has", "how", "new", "our", "your", "you", "into", "now", "show"}


def title_words(title):
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def same_story(a, b):
    wa, wb = title_words(a), title_words(b)
    if not wa or not wb:
        return False
    overlap = len(wa & wb)
    return overlap / len(wa | wb) >= 0.5 or overlap / min(len(wa), len(wb)) >= 0.75


def domain(url):
    return urllib.parse.urlsplit(url).netloc.lower().removeprefix("www.")


def hn_news():
    cfg = CONFIG["noticias"]
    since = int((NOW - timedelta(days=cfg["dias"])).timestamp())
    params = urllib.parse.urlencode({
        "tags": "story",
        "numericFilters": f"created_at_i>{since},points>={cfg['min_puntos_hn']}",
        "hitsPerPage": 500,
    })
    hits = json.loads(http(f"https://hn.algolia.com/api/v1/search?{params}"))["hits"]
    items = []
    for h in hits:
        title = h.get("title") or ""
        if not AI_WORDS.search(title):
            continue
        hn_url = f"https://news.ycombinator.com/item?id={h['objectID']}"
        url = h.get("url") or hn_url
        items.append({
            "titulo_original": title,
            "url": url,
            "fuente": domain(url) if h.get("url") else "news.ycombinator.com",
            "puntos": h.get("points") or 0,
            "comentarios": h.get("num_comments") or 0,
            "hn_url": hn_url,
            "fecha": (h.get("created_at") or "")[:10],
            "oficial": False,
            "extracto": "",
            "score": h.get("points") or 0,
        })
    log(f"  Hacker News: {len(items)} noticias de IA")
    return items


def xml_text(el, *names):
    for name in names:
        found = el.find(name)
        if found is not None:
            if found.text and found.text.strip():
                return found.text.strip()
            if found.get("href"):
                return found.get("href")
    return ""


def rss_news():
    cfg = CONFIG["noticias"]
    since = NOW - timedelta(days=cfg["dias"])
    atom = "{http://www.w3.org/2005/Atom}"
    items = []
    for feed in cfg["feeds"]:
        try:
            root = ET.fromstring(http(feed["url"], timeout=20, retries=1))
        except Exception as e:  # noqa: BLE001
            log(f"  Feed {feed['nombre']}: no disponible ({e})")
            continue
        entries = list(root.iter("item")) + list(root.iter(f"{atom}entry"))
        count = 0
        for it in entries:
            title = clean_text(html.unescape(xml_text(it, "title", f"{atom}title")))
            link = xml_text(it, "link", f"{atom}link")
            date = parse_date(xml_text(it, "pubDate", f"{atom}published", f"{atom}updated"))
            if not title or not link or not date:
                continue
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            if date < since or (feed.get("filtrar") and not AI_WORDS.search(title)):
                continue
            summary = xml_text(it, "description", f"{atom}summary", f"{atom}content")
            summary = clean_text(html.unescape(re.sub(r"<[^>]+>", " ", summary)))[:1500]
            items.append({
                "titulo_original": title,
                "url": link,
                "fuente": feed["nombre"],
                "puntos": 0,
                "comentarios": 0,
                "hn_url": "",
                "fecha": date.date().isoformat(),
                "oficial": True,
                "extracto": summary,
                "score": cfg["puntuacion_fuente_oficial"],
            })
            count += 1
        log(f"  Feed {feed['nombre']}: {count} publicaciones recientes")
    return items


def fetch_article_text(url):
    """Extrae la meta-descripción y los primeros párrafos de un artículo (mejor esfuerzo)."""
    if "news.ycombinator.com" in url:
        return ""
    try:
        raw = http(url, headers={"Accept": "text/html"}, timeout=15, retries=0, max_bytes=1_500_000)
        page = raw.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""
    meta = ""
    m = re.search(r'<meta[^>]+(?:name|property)=["\'](?:og:)?description["\'][^>]+content=["\']([^"\']+)', page, re.I)
    if m:
        meta = html.unescape(m.group(1))
    paras = re.findall(r"<p[^>]*>(.*?)</p>", page, re.S | re.I)
    body = " ".join(clean_text(html.unescape(re.sub(r"<[^>]+>", " ", p))) for p in paras[:25])
    return clean_text(f"{meta} {body}")[:3000]


def collect_news():
    cfg = CONFIG["noticias"]
    log("→ Buscando noticias…")
    items = []
    try:
        items += hn_news()
    except Exception as e:  # noqa: BLE001
        log(f"  Hacker News no disponible: {e}")
    items += rss_news()

    recent = {norm_url(n["url"]) for ed in previous_editions(cfg["no_repetir_ediciones"]) for n in ed.get("noticias", [])}
    merged = {}
    for it in items:
        key = norm_url(it["url"])
        if key in recent:
            continue
        if key in merged:  # la misma noticia en HN y en un blog oficial → se combinan
            cur = merged[key]
            cur["score"] = max(cur["score"], it["score"]) + 40
            cur["oficial"] = cur["oficial"] or it["oficial"]
            for f in ("puntos", "comentarios", "hn_url", "extracto"):
                cur[f] = cur[f] or it[f]
            if it["oficial"]:
                cur["fuente"] = it["fuente"]
        else:
            merged[key] = dict(it)
    ranked = sorted(merged.values(), key=lambda x: x["score"], reverse=True)

    # Evita duplicados (misma historia con otra URL) y que una sola fuente acapare la sección.
    chosen, per_source = [], {}
    for it in ranked:
        if per_source.get(it["fuente"], 0) >= 3:
            continue
        if any(same_story(it["titulo_original"], c["titulo_original"]) for c in chosen):
            continue
        per_source[it["fuente"]] = per_source.get(it["fuente"], 0) + 1
        chosen.append(it)
        if len(chosen) >= cfg["cantidad"]:
            break
    log(f"  Seleccionadas {len(chosen)} noticias")

    news = []
    for rank, it in enumerate(chosen, 1):
        log(f"  · #{rank} {it['titulo_original'][:70]}")
        context = it["extracto"] or fetch_article_text(it["url"])
        ai = ai_json(
            f"Titular original: {it['titulo_original']}\n"
            f"Fuente: {it['fuente']} · Fecha: {it['fecha']}\n"
            f"Texto del artículo (puede estar incompleto o vacío):\n{context or '(no disponible)'}\n\n"
            "Devuelve un JSON con estas claves:\n"
            '"titular": el titular traducido y adaptado al español (máximo 90 caracteres, sin clickbait);\n'
            '"resumen": 2 frases en español con lo esencial. Si el texto no está disponible, explica solo lo que dice el titular sin añadir datos;\n'
            '"por_que_importa": 1 frase sobre por qué le importa a un desarrollador que crea agentes, automatizaciones o SaaS;\n'
            f'"categoria": exactamente una de {json.dumps(CONFIG["categorias"], ensure_ascii=False)}.'
        ) or {}
        news.append({
            "rank": rank,
            "titular": clean_text(ai.get("titular")) or it["titulo_original"],
            "titulo_original": it["titulo_original"],
            "url": it["url"],
            "fuente": it["fuente"],
            "resumen": clean_text(ai.get("resumen")) or it["extracto"][:280],
            "por_que_importa": clean_text(ai.get("por_que_importa")),
            "categoria": valid_category(ai.get("categoria"), f"{it['titulo_original']} {context[:500]}"),
            "puntos": it["puntos"],
            "comentarios": it["comentarios"],
            "hn_url": it["hn_url"],
            "oficial": it["oficial"],
            "fecha": it["fecha"],
            "resumido_con_ia": bool(ai),
        })
    return news


# ---------------------------------------------------------------- Edición

def editorial(projects, news):
    if not projects and not news:
        return ""
    lines = [f"- Proyecto: {p['titular']} ({p['full_name']}, +{p['estrellas_dia']} estrellas/día)" for p in projects[:5]]
    lines += [f"- Noticia: {n['titular']}" for n in news[:5]]
    ai = ai_json(
        "Estos son los contenidos destacados de la edición de hoy:\n" + "\n".join(lines) +
        "\n\nDevuelve un JSON con la clave \"intro\": un párrafo editorial en español de 2 o 3 frases "
        "(máximo 75 palabras) que resuma la tendencia del día para desarrolladores. Tono sobrio, sin emojis.",
        max_tokens=250,
    ) or {}
    return clean_text(ai.get("intro"))


def main():
    EDITIONS.mkdir(parents=True, exist_ok=True)
    if not TOKEN:
        log("Aviso: sin GITHUB_TOKEN. Se usará la API de GitHub sin autenticar (más lenta).")
    if not GEMINI_KEY:
        warn("Falta el secreto GEMINI_API_KEY: la edición saldrá sin resúmenes en español.")
    projects = collect_projects()
    news = collect_news()
    if not projects and not news:
        raise RuntimeError("No se obtuvo ningún contenido; no se publica una edición vacía.")
    others = [p for p in EDITIONS.glob("*.json") if p.stem != TODAY]
    edition = {
        "fecha": TODAY,
        "generado": NOW.isoformat(timespec="seconds"),
        "numero": len(others) + 1,
        "intro": editorial(projects, news),
        "proyectos": projects,
        "noticias": news,
        "modelo_ia": (_ai_state["model"] or "") if any(
            x["resumido_con_ia"] for x in projects + news) else "",
    }
    out = EDITIONS / f"{TODAY}.json"
    out.write_text(json.dumps(edition, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"✓ Edición guardada en {out.relative_to(ROOT)} ({len(projects)} proyectos, {len(news)} noticias)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log(f"✗ Error: {e}")
        sys.exit(1)
