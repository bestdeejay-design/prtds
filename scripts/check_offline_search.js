/* Проверка поиска в офлайн-демо: демо против настоящего бэкенда.
 *
 * Зачем
 * -----
 * Демо работает без сервера и считает выборку само (scripts/offline_search.js).
 * «Само» не значит «как получится»: этот скрипт сравнивает каждый ответ демо с
 * ответом бэкенда и падает, если наборы карточек расходятся. Раньше именно так
 * проглядели баг, когда клик по категории показывал весь каталог: на глаз 20
 * карточек выглядели правдоподобно.
 *
 * Проверяются два уровня:
 *   1. интерфейс — настоящие клики по чипсам категорий, выбор баррио, канала,
 *      сортировки, цены и ввод текста (jsdom);
 *   2. движок — матрица комбинаций фильтров, включая все 46 категорий, все
 *      сортировки, пагинацию, запросы с диакритикой и в верхнем регистре.
 * Плюс структурные инварианты, которые должны выполняться даже без бэкенда:
 * каждая выданная карточка обязана подходить под каждый включённый фильтр.
 *
 * Зависимости (вне репозитория):  npm install jsdom
 * Запуск:
 *   NODE_PATH=/path/to/node_modules node scripts/check_offline_search.js
 *   ... --api http://127.0.0.1:8000   эталон — живой бэкенд (полная матрица)
 *   ... --fixtures                    эталон — записанные ответы из snapshot.json
 *                                     (сервер не нужен, проверяются записи)
 * Код возврата 1 при любом расхождении.
 */

const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const DEMO = path.join(ROOT, "docs", "demo", "index.html");
const SNAPSHOT_FILE = path.join(ROOT, "docs", "demo", "snapshot.json");
const CATALOG_KEY = "GET /api/search#catalog";

const argv = process.argv.slice(2);
const flagIndex = argv.indexOf("--api");
const API = flagIndex !== -1 ? argv[flagIndex + 1] : "http://127.0.0.1:8000";
const FIXTURES_ONLY = argv.includes("--fixtures");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/* ------------------------------------------------------------------ эталон */
async function oracle(query) {
  if (!FIXTURES_ONLY) {
    try {
      const response = await fetch(`${API}/api/search?${query}&track=false`, {
        headers: { "X-PRTDS-Session": "check-offline-search" },
      });
      if (response.ok) return normalize(await response.json());
    } catch (error) {
      if (!fixtures) throw new Error(`бэкенд недоступен (${API}): ${error.message}`);
    }
  }
  const key = `GET /api/search?${query}`;
  const entry = fixtures[key];
  if (!entry || entry.status !== 200) return null; // эталона нет — проверка пропускается
  return normalize(entry.body);
}

function normalize(payload) {
  return {
    total: payload.total,
    page_count: payload.page_count,
    organic: (payload.results || []).map((item) => item.slug),
    sponsored: ((payload.sponsored || {}).items || []).map((item) => item.slug),
  };
}

/* ------------------------------------------------------- инварианты выборки */
function invariants(query, payload, catalog) {
  const problems = [];
  const params = new URLSearchParams(query);
  const bySlug = {};
  catalog.companies.forEach((company) => {
    bySlug[company.slug] = company;
  });

  /* дерево категорий: фильтр всегда включает потомков */
  const childrenOf = {};
  catalog.categories.forEach((cat) => {
    const key = cat.parent_slug || "";
    (childrenOf[key] = childrenOf[key] || []).push(cat.slug);
  });
  const descendants = (slug) => {
    const out = [];
    const stack = [slug];
    while (stack.length) {
      const current = stack.pop();
      out.push(current);
      (childrenOf[current] || []).forEach((child) => stack.push(child));
    }
    return out;
  };

  const asciiLower = (value) => String(value || "").replace(/[A-Z]/g, (ch) => String.fromCharCode(ch.charCodeAt(0) + 32));
  const all = [...payload.organic, ...payload.sponsored];

  all.forEach((slug) => {
    const company = bySlug[slug];
    if (!company) {
      problems.push(`${slug}: карточки нет в снимке каталога`);
      return;
    }
    const category = params.get("category");
    if (category) {
      const allowed = new Set(descendants(category));
      if (!(company.category_slugs || []).some((slug2) => allowed.has(slug2))) {
        problems.push(`${slug}: не входит в категорию ${category} (её категории: ${company.category_slugs.join(", ")})`);
      }
    }
    const barrio = params.get("barrio");
    if (barrio) {
      const needle = asciiLower(barrio.trim());
      if (!(company.barrios || []).some((value) => asciiLower(value).includes(needle))) {
        problems.push(`${slug}: нет баррио «${barrio}» (есть: ${company.barrios.join(", ")})`);
      }
    }
    const channel = params.get("channel");
    if (channel && !(company.channels || {})[channel]) {
      problems.push(`${slug}: канал ${channel} недоступен`);
    }
    const maxPrice = params.get("max_price");
    const minPrice = params.get("min_price");
    if (maxPrice || minPrice) {
      const hit = (company.prices || []).some((value) => {
        if (maxPrice && value > Number(maxPrice)) return false;
        if (minPrice && value < Number(minPrice)) return false;
        return true;
      });
      if (!hit) problems.push(`${slug}: нет предложения в диапазоне цен`);
    }
    if (company.is_promoted && payload.organic.includes(slug)) {
      problems.push(`${slug}: рекламная карточка попала в органическую выдачу (§13.4)`);
    }
    if (!company.is_promoted && payload.sponsored.includes(slug)) {
      problems.push(`${slug}: нерекламная карточка показана как реклама`);
    }
  });
  return problems;
}

/* ------------------------------------------------------------------- демо */
async function bootDemo() {
  const html = fs.readFileSync(DEMO, "utf8");
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (error) => errors.push(String(error.message).split("\n")[0]));

  const dom = new JSDOM(html, {
    virtualConsole,
    runScripts: "dangerously",
    pretendToBeVisual: true,
    url: "https://bestdeejay-design.github.io/prtds/demo/index.html",
    beforeParse(window) {
      window.Response = Response;
      window.Request = Request;
      window.Headers = Headers;
      if (!window.crypto) window.crypto = require("crypto").webcrypto;
    },
  });
  await sleep(2600);
  return { dom, errors };
}

function readDemo(dom) {
  const document = dom.window.document;
  const organic = [...document.querySelectorAll("#results .result")].map((el) => el.dataset.slug);
  const sponsored = [...document.querySelectorAll("#sponsored .result")].map((el) => el.dataset.slug);
  const count = (document.querySelector("#results-count") || {}).textContent || "";
  return { total: organic.length, page_count: null, organic, sponsored, count: count.replace(/\s+/g, " ").trim() };
}

/* --------------------------------------------------------------- матрица */
function buildMatrix(catalog) {
  const slugs = catalog.companies.map((company) => company.slug);
  const allCategories = catalog.categories.map((cat) => cat.slug);
  const barrios = [...new Set(catalog.companies.flatMap((company) => company.barrios || []))].sort();
  const sorts = ["relevance", "name", "recent", "price_asc"];
  const channels = ["whatsapp", "phone", "delivery", "pickup"];
  const queries = [
    "manicura", "uñas", "Manicura", "MANICURA", "yerba mate", "celular", "celulares",
    "smartphone", "iphone", "android", "pizza", "sushi", "farmacia", "belleza",
    "alquiler de autos", "movil", "móvil", "Ñandutí", "kaaguy", "tereré", "24 horas",
    "delivery", "veterinaria", "peluqueria", "contadores", "mudanzas", "hotel",
    "idiomas", "guarani", "ferreteria", "aceite", "fideos", "asuncion", "centro",
    "no existe tal producto", "",
  ];

  const combos = [];
  const add = (params) => {
    const ordered = new URLSearchParams();
    ["q", "category", "barrio", "channel", "min_price", "max_price", "sort", "page", "limit"].forEach((key) => {
      const value = params[key];
      if (value !== undefined && value !== null && value !== "") ordered.set(key, String(value));
    });
    combos.push(ordered.toString());
  };

  add({ sort: "relevance", page: 1, limit: 20 });
  sorts.forEach((sort) => add({ sort, page: 1, limit: 20 }));
  allCategories.forEach((category) => add({ category, sort: "relevance", page: 1, limit: 20 }));
  allCategories.forEach((category) => add({ category, sort: "name", page: 1, limit: 20 }));
  barrios.forEach((barrio) => add({ barrio, sort: "relevance", page: 1, limit: 20 }));
  channels.forEach((channel) => add({ channel, sort: "relevance", page: 1, limit: 20 }));
  [50000, 100000, 500000, 5000000].forEach((max_price) => add({ max_price, sort: "relevance", page: 1, limit: 20 }));
  add({ min_price: 100000, sort: "relevance", page: 1, limit: 20 });
  queries.forEach((q) => add({ q, sort: "relevance", page: 1, limit: 20 }));

  /* комбинированные фильтры: детерминированный «случайный» набор */
  let seed = 20261108;
  const rnd = (n) => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed % n;
  };
  for (let i = 0; i < 60; i += 1) {
    const params = { page: 1, limit: 20 };
    if (i % 2 === 0) params.category = allCategories[rnd(allCategories.length)];
    if (i % 3 === 0) params.barrio = barrios[rnd(barrios.length)];
    if (i % 4 === 0) params.channel = channels[rnd(channels.length)];
    if (i % 5 === 0) params.max_price = [50000, 100000, 500000, 2000000][rnd(4)];
    params.sort = sorts[rnd(sorts.length)];
    if (i % 7 === 0) params.q = queries[rnd(queries.length)];
    add(params);
  }
  /* пагинация: маленькие страницы, чтобы проверить окно и page_count */
  [2, 5, 7].forEach((limit) => {
    [1, 2, 3].forEach((page) => add({ sort: "relevance", page, limit }));
    add({ category: "gastronomia", sort: "name", page: 2, limit });
  });

  return [...new Set(combos)].filter((query) => query.length);
}

/* ------------------------------------------------------------------ отчёт */
async function main() {
  if (!fs.existsSync(DEMO)) {
    console.error(`нет ${DEMO} — соберите демо: python scripts/build_offline_demo.py`);
    process.exit(2);
  }
  const snapshot = JSON.parse(fs.readFileSync(SNAPSHOT_FILE, "utf8"));
  global.fixtures = snapshot;
  const catalogEntry = snapshot[CATALOG_KEY];
  if (!catalogEntry) {
    console.error(`в snapshot.json нет ${CATALOG_KEY} — снимок собран старым сборщиком`);
    process.exit(2);
  }
  const catalog = catalogEntry.body;

  const { dom, errors } = await bootDemo();
  if (errors.length) {
    console.log("ОШИБКИ СТРАНИЦЫ:", errors.slice(0, 5));
  }
  const window = dom.window;
  const document = window.document;

  let checks = 0;
  let skipped = 0;
  const failures = [];

  const compare = async (label, query, demoResult) => {
    const expected = await oracle(query);
    checks += 1;
    if (!expected) {
      skipped += 1;
      return;
    }
    const sameOrganic = JSON.stringify(demoResult.organic) === JSON.stringify(expected.organic);
    const sameSponsored = JSON.stringify(demoResult.sponsored) === JSON.stringify(expected.sponsored);
    const sameTotal = demoResult.total === expected.total;
    const broken = invariants(query, demoResult, catalog);
    if (!sameOrganic || !sameSponsored || !sameTotal || broken.length) {
      failures.push({
        label,
        query,
        demo: demoResult.organic,
        api: expected.organic,
        demoSponsored: demoResult.sponsored,
        apiSponsored: expected.sponsored,
        demoTotal: demoResult.total,
        apiTotal: expected.total,
        broken,
      });
    }
  };

  /* --- уровень 1: интерфейс (клики и выбор в селектах) -------------------- */
  /* Важно: после каждого клика чипсы перерисовываются, поэтому кнопки надо
   * искать заново — клик по «отвалившемуся» узлу до обработчика не доходит. */
  const chipSlugs = [...document.querySelectorAll("#chips .chip")].map((chip) => chip.dataset.slug || "");
  console.log(`чипсов категорий: ${chipSlugs.length} · карточек в снимке: ${catalog.companies.length}`);

  const resetFilters = async () => {
    const all = document.querySelector('#chips .chip[data-slug=""]');
    if (all) {
      all.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
      await sleep(380);
    }
    ["barrio", "channel"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = "";
    });
    const price = document.getElementById("max_price");
    if (price) price.value = "";
    const sort = document.getElementById("sort");
    if (sort) sort.value = "relevance";
  };

  for (const slug of chipSlugs) {
    await resetFilters();
    const chip = document.querySelector(`#chips .chip[data-slug="${slug}"]`);
    if (!chip) {
      failures.push({ label: `чипс «${slug}» исчез после перерисовки`, query: slug, demo: [], api: [], demoSponsored: [], apiSponsored: [], demoTotal: 0, apiTotal: 0, broken: [] });
      continue;
    }
    const label = chip.textContent.replace(/\s+/g, " ").trim();
    chip.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await sleep(420);
    await compare(`клик по чипсу «${label}»`,
      slug ? `category=${encodeURIComponent(slug)}&sort=relevance&page=1&limit=20` : "sort=relevance&page=1&limit=20",
      readDemo(dom));
  }

  const barrioSelect = document.getElementById("barrio");
  for (const option of [...barrioSelect.options].slice(1)) {
    await resetFilters();
    barrioSelect.value = option.value;
    barrioSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
    await sleep(400);
    await compare(`баррио «${option.value}»`,
      `barrio=${encodeURIComponent(option.value)}&sort=relevance&page=1&limit=20`, readDemo(dom));
  }

  const channelSelect = document.getElementById("channel");
  for (const option of [...channelSelect.options].slice(1)) {
    await resetFilters();
    channelSelect.value = option.value;
    channelSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
    await sleep(400);
    await compare(`канал «${option.value}»`,
      `channel=${option.value}&sort=relevance&page=1&limit=20`, readDemo(dom));
  }

  const sortSelect = document.getElementById("sort");
  for (const option of [...sortSelect.options]) {
    await resetFilters();
    sortSelect.value = option.value;
    sortSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
    await sleep(400);
    await compare(`сортировка «${option.value}»`, `sort=${option.value}&page=1&limit=20`, readDemo(dom));
  }

  for (const text of ["manicura", "yerba mate", "celular", "farmacia", "Ñandutí", "alquiler de autos"]) {
    await resetFilters();
    const input = document.getElementById("q");
    input.value = text;
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
    await sleep(700);
    await compare(`поиск «${text}»`,
      `q=${encodeURIComponent(text)}&sort=relevance&page=1&limit=20`, readDemo(dom));
    input.value = "";
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
    await sleep(500);
  }

  /* фильтр + сортировка вместе: то, на чём ломалось раньше */
  await resetFilters();
  document.querySelector('#chips .chip[data-slug="gastronomia"]').dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await sleep(300);
  sortSelect.value = "name";
  sortSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
  await sleep(400);
  await compare("категория + сортировка", "category=gastronomia&sort=name&page=1&limit=20", readDemo(dom));

  /* --- уровень 2: движок на полной матрице -------------------------------- */
  const matrix = buildMatrix(catalog);
  console.log(`матрица движка: ${matrix.length} комбинаций`);
  for (const query of matrix) {
    const payload = window.eval(`window.__PRTDS_OFFLINE_SEARCH__(${JSON.stringify("?" + query)}, ${JSON.stringify(catalog)})`);
    await compare("движок", query, normalize(payload));
  }

  /* --- отчёт -------------------------------------------------------------- */
  for (const failure of failures.slice(0, 25)) {
    console.log(`\nРАСХОЖДЕНИЕ · ${failure.label}`);
    console.log(`  запрос      : ${failure.query}`);
    console.log(`  демо        : ${failure.demoTotal} → ${failure.demo.join(", ") || "—"}`);
    console.log(`  бэкенд      : ${failure.apiTotal} → ${failure.api.join(", ") || "—"}`);
    if (JSON.stringify(failure.demoSponsored) !== JSON.stringify(failure.apiSponsored)) {
      console.log(`  реклама демо: ${failure.demoSponsored.join(", ") || "—"}`);
      console.log(`  реклама API : ${failure.apiSponsored.join(", ") || "—"}`);
    }
    failure.broken.forEach((problem) => console.log(`  инвариант   : ${problem}`));
  }

  console.log(
    `\nпроверок: ${checks} · расхождений: ${failures.length} · без эталона пропущено: ${skipped}` +
      (FIXTURES_ONLY ? " (эталон — записи snapshot.json)" : ` (эталон — ${API})`)
  );
  if (errors.length) console.log(`ошибок консоли страницы: ${errors.length}`);
  process.exit(failures.length || errors.length ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(2);
});
