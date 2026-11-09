#!/usr/bin/env python3
"""Build a self-contained offline demo of the PRTDS frontend.

Why this exists
---------------
The dev sandbox serves the preview only through the Arena proxy (a raw
``https://{port}-{sandbox}.e2b.app`` URL answers 403 "Missing traffic access
token"), and the sandbox has no browser, so nobody can take a screenshot from
inside it. This script produces something better than a screenshot: the *real*
pages (same HTML, same CSS, same JavaScript) with the network layer replaced by
responses recorded from the running API.

The result opens by double-clicking ``index.html`` — no server, no build step,
no internet. Module scripts are inlined because ``file://`` blocks ES module
imports.

Usage
-----
    python scripts/build_offline_demo.py            # records from http://127.0.0.1:8000
    python scripts/build_offline_demo.py --base-url http://127.0.0.1:8000 --out dist/offline
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
JS_DIR = FRONTEND / "assets" / "js"

#: shared modules first, then the page module (order matters: the offline shim
#: re-declares pathParam/queryParam *after* api.js but *before* the page code).
SHARED = ["api.js", "format.js", "tracking.js", "i18n-dict.js", "i18n.js"]

#: file → module, route it pretends to be on, and the API prefixes it needs.
#: Filtering keeps every page small: the full dump is ~200 KB, a page needs a
#: fraction of it. Correctness is re-checked by executing the pages in a DOM.
PAGES = {
    "index.html": {
        "module": "search.js",
        "path": "/",
        "title": "Búsqueda",
        "needs": ["/api/search", "/api/categories", "/api/facets", "/api/meta/status", "/api/whatsapp-link", "/api/call-link"],
    },
    "empresa.html": {
        "module": "company.js",
        "path": "/empresa/nails-mburucuya",
        "title": "Ficha",
        "needs": ["/api/companies/", "/api/whatsapp-link", "/api/call-link", "/api/leads"],
    },
    "solicitud.html": {
        "module": "lead.js",
        "path": "/solicitud/PRTDS-2026-000001",
        "title": "Solicitud",
        "needs": ["/api/leads/"],
    },
    "socio.html": {
        "module": "partner.js",
        "path": "/socio",
        "title": "Socios",
        "needs": ["/api/partner/"],
    },
    "admin.html": {
        "module": "admin.js",
        "path": "/admin",
        "title": "Admin",
        "needs": ["/api/admin/"],
    },
    "salud.html": {
        "module": "status.js",
        "path": "/salud",
        "title": "Estado",
        "needs": ["/api/meta/"],
    },
}


def subset(snapshot: dict[str, Any], needs: list[str]) -> dict[str, Any]:
    """Only the recorded responses this page can ask for."""
    selected = {}
    for key, value in snapshot.items():
        path = key.split(" ", 1)[1].split("?", 1)[0]
        if any(path.startswith(prefix) for prefix in needs):
            selected[key] = value
    if not selected:
        raise SystemExit(f"фильтр не оставил данных для {needs}")
    return selected

PARTNER_TOKEN = "prtds-socio-nails"
ADMIN_TOKEN = "prtds-demo-admin-token"

#: порядок параметров совпадает с search.js, иначе ключ записи не совпадёт
#: со строкой запроса, которую построит браузер.
SEARCH_PARAM_ORDER = ["q", "category", "barrio", "channel", "max_price", "sort", "campaign_id", "page", "limit"]

SEARCH_QUERIES = ["manicura", "yerba mate", "celular", "alquiler de autos", "sushi", "farmacia", "belleza", "pizza"]
SEARCH_CATEGORIES = ["gastronomia", "supermercados", "belleza", "vehiculos", "tecnologia", "salud",
                     "hogar", "educacion", "servicios", "eventos", "turismo", "mascotas"]
SEARCH_BARRIOS = ["Centro", "Villa Morra", "Santísima Trinidad", "San Lorenzo", "Sajonia", "Recoleta",
                  "Manorá", "Luque", "Las Mercedes", "Lambaré", "Fernando de la Mora", "Barrio Jara"]
SEARCH_CHANNELS = ["whatsapp", "phone", "delivery", "pickup"]
SEARCH_SORTS = ["relevance", "name", "recent", "price_asc"]
SEARCH_PRICES = ["100000", "500000"]


def search_combos() -> list[dict[str, str]]:
    """Комбинации фильтров, которые записываются с живого API."""
    combos: list[dict[str, str]] = [{"page": "1", "limit": "20"}]
    for query in SEARCH_QUERIES:
        combos.append({"q": query, "page": "1", "limit": "20"})
    for key, values in (
        ("category", SEARCH_CATEGORIES),
        ("barrio", SEARCH_BARRIOS),
        ("channel", SEARCH_CHANNELS),
        ("sort", SEARCH_SORTS),
        ("max_price", SEARCH_PRICES),
    ):
        for value in values:
            combos.append({key: value, "page": "1", "limit": "20"})
    combos += [
        {"q": "celular", "sort": "price_asc", "page": "1", "limit": "20"},
        {"q": "manicura", "barrio": "Las Mercedes", "page": "1", "limit": "20"},
        {"category": "belleza", "channel": "whatsapp", "page": "1", "limit": "20"},
        {"category": "gastronomia", "sort": "name", "page": "1", "limit": "20"},
        {"q": "yerba mate", "max_price": "100000", "page": "1", "limit": "20"},
        {"category": "vehiculos", "barrio": "Centro", "page": "1", "limit": "20"},
    ]
    return combos


def search_query_string(params: dict[str, str]) -> str:
    ordered = [(key, params[key]) for key in SEARCH_PARAM_ORDER if key in params]
    return urllib.parse.urlencode(ordered)


def http(base: str, path: str, *, method: str = "GET", body: Any = None, headers: dict[str, str] | None = None):
    """Record one real response from the running API."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
    request.add_header("X-PRTDS-Session", "offline-demo-builder")
    if data:
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode()
            return response.status, json.loads(payload) if payload else None
    except urllib.error.HTTPError as error:  # a recorded error is still a useful snapshot
        payload = error.read().decode()
        try:
            return error.code, json.loads(payload) if payload else None
        except json.JSONDecodeError:
            return error.code, {"detail": payload[:200]}


def record(base: str) -> dict[str, Any]:
    """Capture every response the six pages need, from the live server."""
    snapshot: dict[str, Any] = {}

    def put(method: str, path: str, key: str | None = None, **kwargs) -> None:
        status, payload = http(base, path, method=method, **kwargs)
        snapshot[key or f"{method} {path}"] = {"status": status, "body": payload}

    # --- shared metadata -------------------------------------------------
    for path in ("/api/meta/status", "/api/meta/funnel", "/api/meta/market", "/api/categories", "/api/facets"):
        put("GET", path)

    # --- search page -----------------------------------------------------
    for params in search_combos():
        put("GET", f"/api/search?{search_query_string(params)}")

    # --- company cards ---------------------------------------------------
    slugs = ["nails-mburucuya", "tecnomovil-guarani", "supermercado-kaaguy", "parrilla-yvoty", "rentcar-terere"]
    for slug in slugs:
        put("GET", f"/api/companies/{slug}")

    # --- contact attempts and a lead ------------------------------------
    put("POST", "/api/whatsapp-link", body={"company_slug": "nails-mburucuya", "source": "card"})
    put("POST", "/api/call-link", body={"company_slug": "nails-mburucuya", "source": "card"})

    status, created = http(
        base,
        "/api/leads",
        method="POST",
        body={
            "company_slug": "nails-mburucuya",
            "intent": "booking",
            "customer_name": "Ana Benítez",
            "customer_phone": "+595981444222",
            "message": "Quiero un turno para uñas esculpidas el viernes",
            "requested_at": "viernes 17:00",
            "source": "offline_demo",
            "consent": {"purpose": "lead_transfer", "granted": True, "channel": "web_form"},
        },
    )
    snapshot["POST /api/leads"] = {"status": status, "body": created}
    ref = (created or {}).get("ref_code", "PRTDS-2026-000001")

    # partner accepts and confirms, so the CRM screens have a real trail
    partner_headers = {"X-Partner-Token": PARTNER_TOKEN}
    put("POST", f"/api/partner/leads/{ref}/decision", body={"status": "accepted"}, headers=partner_headers)
    put(
        "POST",
        f"/api/partner/leads/{ref}/sale",
        body={"amount_pyg": 180_000, "proof_ref": "FACT-DEMO-01"},
        headers=partner_headers,
    )
    put("GET", f"/api/leads/{ref}")
    put("GET", "/api/leads/PRTDS-2026-000001")

    # --- partner cabinet -------------------------------------------------
    put("GET", "/api/partner/me", headers=partner_headers)
    put("GET", "/api/partner/dashboard", headers=partner_headers)
    put("GET", "/api/partner/leads?limit=50", headers=partner_headers)
    put("GET", "/api/partner/settlements?limit=100", headers=partner_headers)

    # --- admin -----------------------------------------------------------
    admin_headers = {"X-Admin-Token": ADMIN_TOKEN}
    put("GET", "/api/admin/stats", headers=admin_headers)
    put("GET", "/api/admin/categories", headers=admin_headers)
    put("GET", "/api/admin/settlements?limit=50", headers=admin_headers)
    put("GET", "/api/admin/funnel/events?limit=30", headers=admin_headers)
    put("POST", "/api/admin/reindex", body={}, headers=admin_headers)

    # --- honest failure examples (the UI shows these states too) ---------
    put(
        "POST",
        "/api/leads",
        key="POST /api/leads#sin-consentimiento",
        body={"company_slug": "nails-mburucuya", "consent": {"purpose": "lead_transfer", "granted": False}},
    )
    put("GET", "/api/companies/bodega-mboriahu-staging", key="GET /api/companies/bodega-mboriahu-staging")

    return snapshot


IMPORT_RE = re.compile(r'import\s*\{[^}]*\}\s*from\s*"[^"]+"\s*;?', re.S)
EXPORT_RE = re.compile(r"^export\s+", re.M)


def strip_modules(source: str) -> str:
    """Turn an ES module into a plain script (file:// cannot import modules)."""
    return EXPORT_RE.sub("", IMPORT_RE.sub("", source))


def inline_js(files: list[str], offline_path: str) -> str:
    parts: list[str] = []
    seen: dict[str, str] = {}
    for name in files:
        source = strip_modules((JS_DIR / name).read_text(encoding="utf-8"))
        # detect duplicate top-level declarations, which would break the page
        for match in re.finditer(r"^(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)", source, re.M):
            identifier = match.group(1)
            if identifier in seen and seen[identifier] != name:
                raise SystemExit(
                    f"conflicto de nombres: '{identifier}' definido en {seen[identifier]} y {name}"
                )
            seen[identifier] = name
        parts.append(f"/* ---- {name} ---- */\n{source}")

    shim = f"""
/* ---- offline shim (solo en esta сборка) ---- */
(function () {{
  const memory = {{}};
  const safeStorage = {{
    getItem: (key) => (key in memory ? memory[key] : null),
    setItem: (key, value) => {{ memory[key] = String(value); }},
    removeItem: (key) => {{ delete memory[key]; }},
  }};
  try {{ window.sessionStorage.getItem("probe"); }} catch (error) {{ window.sessionStorage = safeStorage; }}
  try {{ window.localStorage.getItem("probe"); }} catch (error) {{ window.localStorage = safeStorage; }}
}})();

/* file:// no permite reescribir la URL: se ignora en vez de romper la página */
history.replaceState = function noop() {{}};
history.pushState = function noop() {{}};

/* la página se comporta como si estuviera en esta ruta del sitio real */
const OFFLINE_PATH = {json.dumps(offline_path)};
function pathParam(index = 1) {{
  const parts = OFFLINE_PATH.split("/").filter(Boolean);
  return decodeURIComponent(parts[index] || "");
}}
function queryParam(name) {{
  return new URLSearchParams("").get(name);
}}

/* Нормализация строки запроса поиска: браузер собирает её сам, поэтому ключ
   приводится к каноническому виду, а при отсутствии точной записи параметры
   отбрасываются по очереди — фильтр показывает ближайший записанный результат. */
function canonicalSearch(rawSearch) {{
  const incoming = new URLSearchParams(rawSearch || "");
  const order = ["q", "category", "barrio", "channel", "max_price", "sort", "campaign_id", "page", "limit"];
  const out = new URLSearchParams();
  for (const key of order) {{
    const value = incoming.get(key);
    if (value) out.set(key, value);
  }}
  if (!out.has("page")) out.set("page", "1");
  if (!out.has("limit")) out.set("limit", "20");
  return out;
}}

function searchCandidates(rawSearch) {{
  const params = canonicalSearch(rawSearch);
  const keys = ["GET /api/search?" + params.toString()];
  for (const key of ["max_price", "channel", "barrio", "category", "sort", "q"]) {{
    if (!params.has(key)) continue;
    params.delete(key);
    keys.push("GET /api/search?" + params.toString());
  }}
  return keys;
}}

/* la red se sustituye por respuestas grabadas del API real */
window.__PRTDS_OFFLINE__ = true;
const OFFLINE_NOTES = [];
window.fetch = async function offlineFetch(input, init = {{}}) {{
  const method = (init.method || "GET").toUpperCase();
  const url = typeof input === "string" ? input : input.url;
  const [path, query = ""] = url.split("?");
  const search = query ? "?" + query : "";
  const candidates = [
    `${{method}} ${{path}}${{search}}`,
    `${{method}} ${{path}}`,
  ];
  if (method === "GET" && path === "/api/search") candidates.push(...searchCandidates(search));
  if (method === "GET" && path === "/api/partner/leads") candidates.push("GET /api/partner/leads?limit=50");
  if (method === "GET" && path.startsWith("/api/leads/")) candidates.push("GET /api/leads/PRTDS-2026-000001");
  if (method === "GET" && path.startsWith("/api/companies/")) candidates.push("GET /api/companies/nails-mburucuya");
  if (method === "POST" && path.endsWith("/decision")) {{
    candidates.push(Object.keys(SNAPSHOT).find((key) => key.endsWith("/decision")) || "");
  }}
  if (method === "POST" && path.endsWith("/sale")) {{
    candidates.push(Object.keys(SNAPSHOT).find((key) => key.endsWith("/sale")) || "");
  }}
  if (method === "POST" && path.startsWith("/api/admin/")) candidates.push("POST /api/admin/reindex");

  for (const key of candidates) {{
    const entry = SNAPSHOT[key];
    if (!entry) continue;
    OFFLINE_NOTES.push(key);
    return new Response(JSON.stringify(entry.body), {{
      status: entry.status,
      headers: {{ "Content-Type": "application/json" }},
    }});
  }}
  OFFLINE_NOTES.push(`${{method}} ${{path}} → sin datos grabados`);
  return new Response(
    JSON.stringify({{ detail: "Demostración sin conexión: esta respuesta no fue grabada." }}),
    {{ status: 404, headers: {{ "Content-Type": "application/json" }} }}
  );
}};
"""
    shared = [part for part, name in zip(parts, files) if name in SHARED]
    page = [part for part, name in zip(parts, files) if name not in SHARED]
    return "\n\n".join(shared) + "\n" + shim + "\n" + "\n".join(page)


def build(base: str, out_dir: Path) -> Path:
    snapshot = record(base)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    css = (FRONTEND / "assets" / "css" / "app.css").read_text(encoding="utf-8")
    (out_dir / "snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    banner_css = """
/* ---- aviso de demostración sin conexión ---- */
.offline-banner{position:sticky;top:0;z-index:60;background:#fff4d6;border-bottom:1px solid #e0b64a;
  color:#5a4300;font:13px/1.45 system-ui,sans-serif;padding:8px 14px;text-align:center}
.offline-banner strong{font-weight:700}
.offline-banner a{color:#5a4300}
"""

    nav = "".join(
        f'<a href="{name}" style="margin-left:10px">{meta["title"]}</a>' for name, meta in PAGES.items()
    )
    banner = (
        '<div class="offline-banner"><strong>Demostración sin conexión.</strong> '
        "<span>La interfaz es real; las respuestas del API fueron grabadas y nada se guarda.</span> "
        f'<span>Páginas:</span>{nav}</div>'
    )

    for name, meta in PAGES.items():
        source_html = (FRONTEND / _source_name(name)).read_text(encoding="utf-8")
        js = inline_js(SHARED + [meta["module"]], meta["path"])
        snapshot_json = json.dumps(
            subset(snapshot, meta["needs"]), ensure_ascii=False, separators=(",", ":")
        )

        html = source_html
        # styles: external file → inline, plus the demo banner styles
        html = re.sub(
            r'<link rel="stylesheet" href="/assets/css/app\.css"\s*/?>',
            f"<style>\n{css}\n{banner_css}\n</style>",
            html,
            count=1,
        )
        # scripts: a module in <head> is deferred by the browser; an inlined
        # classic script is not, so it must go at the end of <body> (otherwise
        # every getElementById returns null). Wrapped in an async IIFE so any
        # top-level await still works outside a module.
        html = re.sub(r'[ \t]*<script type="module" src="/assets/js/[\w.]+"></script>\n?', "", html, count=1)
        bundle = (
            "<script>\nconst SNAPSHOT = " + snapshot_json + ";\n"
            "(async () => {\n" + js + "\n})();\n</script>\n</body>"
        )
        html = html.replace("</body>", bundle, 1)
        # links to other screens must work inside the folder
        html = html.replace('href="/"', 'href="index.html"')
        html = html.replace('href="/salud"', 'href="salud.html"')
        html = html.replace('href="/socio"', 'href="socio.html"')
        html = html.replace('href="/admin"', 'href="admin.html"')
        html = html.replace('href="/docs"', 'href="https://github.com/bestdeejay-design/prtds/pull/1"')
        html = re.sub(r'href="/empresa/([^"]+)"', r'href="empresa.html"', html)
        html = re.sub(r'href="/solicitud/([^"]*)"', r'href="solicitud.html"', html)
        html = html.replace("<body>", "<body>\n" + banner, 1)

        (out_dir / name).write_text(html, encoding="utf-8")

    # a reader for people who open the folder without a server
    readme = f"""# PRTDS — демонстрация без подключения

Открой **index.html** двойным кликом. Сервер и интернет не нужны.

## Что это
Настоящие страницы PRTDS (тот же HTML, CSS и JavaScript, что отдаёт сервер),
но ответы API записаны заранее в `snapshot.json` — {len(snapshot)} записей.
Ничего никуда не отправляется и не сохраняется.

## Страницы
| Файл | Что показывает | Доступ |
|---|---|---|
| index.html | поиск, категории, фильтры, рекламный блок | — |
| empresa.html | карточка компании: филиалы, часы, цены, WhatsApp, заявка | — |
| solicitud.html | статус заявки (по номеру PRTDS-2026-000001) | — |
| socio.html | кабинет компании: заявки, подтверждение продажи, ликвидации | токен `{PARTNER_TOKEN}` |
| admin.html | таксономия, публикации, журнал событий, статистика | токен `{ADMIN_TOKEN}` |
| salud.html | честное состояние платформы и словарь воронки | — |

## Язык интерфейса
В правом верхнем углу каждой страницы — переключатель **ES / RU / EN**. Выбор
запоминается в браузере. Продукт остаётся испаноязычным (§02 концепции): русский
и английский — языки просмотра для команды и партнёров. Названия компаний,
брендов и баррио не переводятся, потому что это данные продавцов.

## Что попробовать
1. index.html → поиск `manicura` (записан) → карточка → кнопка WhatsApp.
2. empresa.html → форма заявки → «Enviar»: появится номер обращения.
3. socio.html → токен → принять заявку → подтвердить продажу на 180000:
   система покажет GMV G. 180.000 и доход PRTDS G. 12.600 отдельно.
4. salud.html → словарь событий: что каждое событие доказывает и чего НЕ доказывает.

## Ограничения демо
Записаны ответы только для нескольких запросов (см. `snapshot.json`);
другие поисковые запросы ответят «нет записанных данных». Это не ошибка кода,
а граница офлайн-сборки.

## Как получить живую версию
    git clone -b arena/36f33834-prtds https://github.com/bestdeejay-design/prtds.git
    cd prtds && python3 -m venv .venv
    .venv/bin/pip install -r backend/requirements.txt
    ./scripts/dev.sh          # → http://127.0.0.1:8000
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")

    # the archive must live OUTSIDE out_dir: packing a directory into a file
    # inside itself grows without limit (it consumed the whole disk once).
    archive = ROOT / "dist" / "prtds-offline-demo.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        for file in sorted(out_dir.rglob("*")):
            if file.is_file() and file != archive:
                handle.write(file, file.relative_to(out_dir))
    if archive.stat().st_size > 20 * 1024 * 1024:
        raise SystemExit(f"архив подозрительно большой: {archive.stat().st_size} байт")
    return archive


def _source_name(name: str) -> str:
    """Map the offline file name back to the real page in frontend/."""
    return {
        "index.html": "index.html",
        "empresa.html": "company.html",
        "solicitud.html": "lead.html",
        "socio.html": "partner.html",
        "admin.html": "admin.html",
        "salud.html": "status.html",
    }[name]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default=str(ROOT / "docs" / "demo"))
    args = parser.parse_args()

    archive = build(args.base_url, Path(args.out))
    size = archive.stat().st_size
    print(f"offline demo → {archive} ({size / 1024:.0f} KB)")
    print(f"страниц: {len(PAGES)} · открой index.html двойным кликом")
    return 0


if __name__ == "__main__":
    sys.exit(main())
