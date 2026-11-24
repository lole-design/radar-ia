#!/usr/bin/env python3
"""Genera la web estática (carpeta site/) a partir de las ediciones guardadas en data/."""
import json
import os
import shutil
from datetime import date, datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDITIONS = ROOT / "data" / "ediciones"
SITE = ROOT / "site"
STATIC = ROOT / "static"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
S = CONFIG["sitio"]

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def site_url():
    if S.get("url"):
        return S["url"].rstrip("/") + "/"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        if name.lower() == f"{owner.lower()}.github.io":
            return f"https://{owner.lower()}.github.io/"
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


def fecha_larga(iso):
    d = date.fromisoformat(iso)
    return f"{DIAS[d.weekday()]}, {d.day} de {MESES[d.month - 1]} de {d.year}"


def fecha_corta(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {MESES[d.month - 1][:3]}. {d.year}"


def num(n):
    return f"{n:,}".replace(",", ".")


def e(s):
    return escape(str(s or ""), quote=True)


def load_editions():
    eds = []
    for p in sorted(EDITIONS.glob("*.json"), reverse=True):
        try:
            eds.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            print(f"Aviso: {p.name} está dañado y se omite")
    return eds


# ---------------------------------------------------------------- piezas

def page(title, body, base, description=None, active=""):
    nav = [("index.html", "Hoy", "hoy"), ("archivo.html", "Archivo", "archivo"),
           ("como-funciona.html", "Cómo funciona", "como"), ("feed.xml", "RSS", "rss")]
    nav_html = "".join(
        f'<a href="{base}{href}"{" aria-current=\"page\"" if key == active else ""}>{label}</a>'
        for href, label, key in nav)
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description or S['descripcion'])}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description or S['descripcion'])}">
<meta property="og:type" content="website">
<link rel="icon" href="{base}favicon.svg" type="image/svg+xml">
<link rel="alternate" type="application/rss+xml" title="{e(S['nombre'])}" href="{base}feed.xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;0,8..60,700;1,8..60,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{base}styles.css">
</head>
<body>
<header class="masthead">
  <div class="wrap">
    <a class="brand" href="{base}index.html">{e(S['nombre'])}</a>
    <p class="tagline">{e(S['lema'])}</p>
    <nav class="nav" aria-label="Secciones">{nav_html}</nav>
  </div>
</header>
<main class="wrap">
{body}
</main>
<footer class="footer">
  <div class="wrap footer-grid">
    <div>
      <p class="footer-brand">{e(S['nombre'])}</p>
      <p>{e(S['descripcion'])}</p>
    </div>
    <div>
      <p>{e(S['frecuencia'])}. Selección automática a partir de GitHub, Hacker News y blogs oficiales; resúmenes generados con IA, que puede cometer errores: verifica en la fuente antes de decidir.</p>
      <p><a href="{base}como-funciona.html">Cómo se eligen los contenidos</a> · <a href="{base}feed.xml">RSS</a></p>
    </div>
  </div>
</footer>
</body>
</html>
"""


def project_meta(p):
    bits = [f'<span class="stars" title="Estrellas totales">★ {num(p["estrellas"])}</span>',
            f'<span class="growth" title="Estrellas ganadas por día">+{num(p["estrellas_dia"])} al día</span>']
    if p.get("lenguaje"):
        bits.append(f"<span>{e(p['lenguaje'])}</span>")
    if p.get("licencia") and p["licencia"] != "NOASSERTION":
        bits.append(f"<span>{e(p['licencia'])}</span>")
    bits.append(f'<a class="repo" href="{e(p["url"])}" rel="noopener">{e(p["full_name"])} ↗</a>')
    return '<p class="meta">' + "".join(bits) + "</p>"


def project_card(p, lead=False):
    use = (f'<p class="use"><strong>Para qué te sirve:</strong> {e(p["para_que_sirve"])}</p>'
           if p.get("para_que_sirve") else "")
    tag = "h2" if lead else "h3"
    cls = "story lead" if lead else "story"
    return f"""<article class="{cls}">
  <p class="kicker"><span class="rank">{p['rank']:02d}</span>{e(p['categoria'])}</p>
  <{tag} class="headline"><a href="{e(p['url'])}" rel="noopener">{e(p['titular'])}</a></{tag}>
  <p class="summary">{e(p['resumen'])}</p>
  {use}
  {project_meta(p)}
</article>"""


def news_item(n):
    meta = []
    if n.get("puntos"):
        meta.append(f'<a href="{e(n["hn_url"])}" rel="noopener">{num(n["puntos"])} puntos · {num(n["comentarios"])} comentarios en HN</a>')
    if n.get("oficial"):
        meta.append('<span class="badge">Fuente oficial</span>')
    why = (f'<p class="why">{e(n["por_que_importa"])}</p>' if n.get("por_que_importa") else "")
    original = ""
    if n.get("titulo_original") and n["titulo_original"] != n["titular"]:
        original = f' title="{e(n["titulo_original"])}"'
    return f"""<article class="news">
  <p class="kicker">{e(n['categoria'])} <span class="source">· {e(n['fuente'])}</span></p>
  <h3 class="headline"><a href="{e(n['url'])}" rel="noopener"{original}>{e(n['titular'])}</a></h3>
  {f'<p class="summary">{e(n["resumen"])}</p>' if n.get('resumen') else ''}
  {why}
  {f'<p class="meta">{"".join(meta)}</p>' if meta else ''}
</article>"""


def edition_body(ed, base, latest):
    projects, news = ed.get("proyectos", []), ed.get("noticias", [])
    head = f"""<div class="dateline">
  <span>{e(fecha_larga(ed['fecha']).capitalize())}</span>
  <span>Edición nº {ed['numero']}</span>
  <span>{e(S['frecuencia'])}</span>
</div>"""
    if not latest:
        head += f'<p class="notice">Estás viendo una edición anterior. <a href="{base}index.html">Ir a la edición más reciente →</a></p>'
    intro = (f'<section class="editorial"><p class="label">Editorial</p><p>{e(ed["intro"])}</p></section>'
             if ed.get("intro") else "")
    proj_html = ""
    if projects:
        rest = "".join(project_card(p) for p in projects[1:])
        proj_html = f"""<section class="projects" aria-labelledby="h-proyectos">
  <div class="section-head">
    <h2 id="h-proyectos">Proyectos en tendencia</h2>
    <p>Top {len(projects)} de GitHub por estrellas ganadas al día</p>
  </div>
  {project_card(projects[0], lead=True)}
  <div class="grid">{rest}</div>
</section>"""
    news_html = ""
    if news:
        news_html = f"""<aside class="newscol" aria-labelledby="h-noticias">
  <div class="section-head">
    <h2 id="h-noticias">Noticias</h2>
    <p>Lo más comentado de los últimos días</p>
  </div>
  {''.join(news_item(n) for n in news)}
</aside>"""
    return f"{head}{intro}<div class=\"layout\">{proj_html}{news_html}</div>"


def empty_body():
    return """<section class="empty">
  <h2>La primera edición está en camino</h2>
  <p>El sistema todavía no ha publicado ninguna edición. Vuelve en unas horas.</p>
</section>"""


def archive_body(eds):
    rows = []
    for ed in eds:
        tops = ", ".join(e(p["nombre"]) for p in ed.get("proyectos", [])[:3])
        rows.append(f"""<li class="arch-row">
  <a href="ediciones/{ed['fecha']}.html">
    <span class="arch-date">{e(fecha_corta(ed['fecha']))}<small>Edición nº {ed['numero']}</small></span>
    <span class="arch-body">
      <span class="arch-title">{e(fecha_larga(ed['fecha']).capitalize())}</span>
      {f'<span class="arch-intro">{e(ed["intro"])}</span>' if ed.get('intro') else ''}
      {f'<span class="arch-tops">Destacados: {tops}</span>' if tops else ''}
    </span>
  </a>
</li>""")
    return f"""<div class="page-head"><h1>Archivo</h1><p>{len(eds)} ediciones publicadas</p></div>
<ol class="archive">{''.join(rows) or '<li>Aún no hay ediciones.</li>'}</ol>"""


def about_body():
    g, n = CONFIG["github"], CONFIG["noticias"]
    feeds = ", ".join(e(f["nombre"]) for f in n["feeds"])
    return f"""<div class="page-head"><h1>Cómo funciona</h1><p>Un diario que se escribe solo, con criterios a la vista</p></div>
<div class="prose">
<h2>Proyectos</h2>
<p>Tres veces por semana revisamos en GitHub los repositorios con temas como {', '.join('<code>' + e(t) + '</code>' for t in g['temas'])}. No se ordenan por estrellas totales, porque así siempre ganarían los mismos gigantes, sino por <strong>estrellas ganadas al día</strong>:</p>
<ul>
<li>Para los repositorios creados en los últimos {g['dias_repos_nuevos']} días, estrellas totales divididas entre los días de vida.</li>
<li>Para los repositorios más veteranos, la diferencia de estrellas desde la revisión anterior.</li>
</ul>
<p>Se descartan forks, repositorios archivados o sin descripción, temas ajenos (cripto, apuestas…) y lo que ya salió en las {g['no_repetir_ediciones']} ediciones anteriores. Pasan los {g['cantidad']} que más crecen, con un mínimo de {g['min_estrellas_por_dia']} estrellas al día.</p>
<h2>Noticias</h2>
<p>Recogemos las historias sobre IA más votadas en Hacker News en los últimos {n['dias']} días y las publicaciones de blogs oficiales ({feeds}). Si una noticia aparece en varios sitios, sube en el ranking.</p>
<h2>Resúmenes</h2>
<p>Un modelo de IA lee el README o el artículo y escribe el titular, el resumen y la línea “para qué te sirve”. Puede equivocarse: cada pieza enlaza a su fuente original.</p>
</div>"""


def rss(eds, url):
    items = []
    for ed in eds[:20]:
        link = f"{url}ediciones/{ed['fecha']}.html" if url else f"ediciones/{ed['fecha']}.html"
        lines = [f"<li><a href=\"{e(p['url'])}\">{e(p['titular'])}</a> (+{p['estrellas_dia']} ★/día)</li>" for p in ed.get("proyectos", [])]
        lines += [f"<li><a href=\"{e(n['url'])}\">{e(n['titular'])}</a></li>" for n in ed.get("noticias", [])]
        desc = f"<p>{e(ed.get('intro'))}</p><ul>{''.join(lines)}</ul>"
        pub = datetime.fromisoformat(ed["generado"]) if ed.get("generado") else datetime.now(timezone.utc)
        items.append(f"""<item><title>{e(S['nombre'])} · Edición nº {ed['numero']} ({e(fecha_corta(ed['fecha']))})</title>
<link>{e(link)}</link><guid>{e(link)}</guid><pubDate>{format_datetime(pub)}</pubDate>
<description>{e(desc)}</description></item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>{e(S['nombre'])}</title><link>{e(url or '')}</link>
<description>{e(S['descripcion'])}</description><language>es</language>
{''.join(items)}
</channel></rss>
"""


def main():
    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "ediciones").mkdir(parents=True)
    for f in STATIC.iterdir():
        shutil.copy(f, SITE / f.name)
    (SITE / ".nojekyll").write_text("", encoding="utf-8")

    eds = load_editions()
    name = S["nombre"]
    if eds:
        latest = eds[0]
        body = edition_body(latest, "", latest=True)
        (SITE / "index.html").write_text(page(f"{name} · {S['lema']}", body, "", active="hoy"), encoding="utf-8")
        for ed in eds:
            body = edition_body(ed, "../", latest=(ed is latest))
            title = f"{name} · Edición nº {ed['numero']} · {fecha_corta(ed['fecha'])}"
            (SITE / "ediciones" / f"{ed['fecha']}.html").write_text(page(title, body, "../"), encoding="utf-8")
    else:
        (SITE / "index.html").write_text(page(name, empty_body(), "", active="hoy"), encoding="utf-8")
    (SITE / "archivo.html").write_text(page(f"Archivo · {name}", archive_body(eds), "", active="archivo"), encoding="utf-8")
    (SITE / "como-funciona.html").write_text(page(f"Cómo funciona · {name}", about_body(), "", active="como"), encoding="utf-8")
    (SITE / "feed.xml").write_text(rss(eds, site_url()), encoding="utf-8")
    print(f"✓ Web generada en site/ ({len(eds)} ediciones)")


if __name__ == "__main__":
    main()
