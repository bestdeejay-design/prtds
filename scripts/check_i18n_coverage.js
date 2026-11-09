/* Проверка покрытия перевода интерфейса.
 *
 * Что делает: рендерит собранные страницы демо в ES / RU / EN, собирает видимые
 * строки и сообщает, какие испанские строки остались непереведёнными.
 *
 * Зачем: перевод применяется поверх отрисованного DOM по словарю «испанский
 * оригинал → перевод», поэтому пропуск легко не заметить глазами. Здесь он
 * становится числом.
 *
 * Зависимости (вне репозитория, ставятся в любую временную папку):
 *     npm install jsdom
 * Запуск:
 *     node scripts/check_i18n_coverage.js [папка_с_демо]
 * по умолчанию — docs/demo (соберите её: python scripts/build_offline_demo.py).
 *
 * Код возврата 1, если найдены непереведённые строки не из списка KEEP — это
 * позволяет использовать скрипт как проверку в CI.
 */

const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const DIR = process.argv[2] ? path.resolve(process.argv[2]) : path.join(ROOT, "docs", "demo");
const PAGES = ["index.html", "empresa.html", "solicitud.html", "socio.html", "admin.html", "salud.html"];
const LANGS = ["es", "ru", "en"];

const TOKENS = {
  "socio.html": ["prtds.partner_token", "prtds-demo-partner-token"],
  "admin.html": ["prtds.admin_token", "prtds-demo-admin-token"],
};

/* Не переводятся намеренно: бренды, идентификаторы, имена, адреса, коды,
 * названия демо-компаний и баррио — это данные продавцов, а не текст платформы. */
const KEEP = [
  /^PRTDS/, /^WhatsApp$/, /^README\.md$/, /^API$/, /^SKU /, /^prtds-/, /^\+595/,
  /^(ES|RU|EN)$/,
  /^\d{4}-\d{2}-\d{2}T/, /^bodega-/, /^corte-1/, /Benítez/, /OpenStreetMap/,
  /Mburucuyá Beauty/, /Nails Mburucuyá/, /Las Mercedes/,
  // названия демо-компаний: имена собственные, переводу не подлежат
  /Agenda\ Yvoty\ Shows|Almacén\ Doña\ Nidia|Barbería\ Ypacaraí|Café\ Kuratũ|Clínica\ Mborayhu|Estudio\ Contable\ Aty|Farmacia\ Ysapy|Ferretería\ Itá|Hotel\ Paraná\ Mboy|InfoCenter\ Yvyrá|Instituto\ Ñe'ẽngatú|Mudanzas\ Ypytũ|Nails\ Mburucuyá|Parrilla\ Yvoty|Peluquería\ Porã|RentCar\ Tereré|Supermercado\ Ka'aguy|Sushi\ Mbokajá|Taller\ Mecánico\ Ñandutí|TecnoMóvil\ Guaraní|Veterinaria\ Jaguarete|Estudio Las Mercedes/,
  /^(Centro|Villa Morra|Santísima Trinidad|San Lorenzo|Sajonia|Recoleta|Manorá|Luque|Lambaré|Fernando de la Mora|Barrio Jara)( \(\d+\))?(,|$)/,
];

/* Признаки испанского текста: так отсеиваются строки, которые переводить нечего
 * (числа, цены, даты без слов, идентификаторы). */
const SPANISH = /[áéíóúñ¿¡]|\b(de|del|la|el|los|las|y|en|con|por|para|una|uno|que|se|su|al|a\. m\.|p\. m\.)\b/i;

async function render(file, lang) {
  const html = fs.readFileSync(path.join(DIR, file), "utf8");
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (e) => errors.push(String(e.message).split("\n")[0]));

  const dom = new JSDOM(html, {
    virtualConsole,
    runScripts: "dangerously",
    pretendToBeVisual: true,
    url: "http://localhost/" + file,
    beforeParse(window) {
      window.Response = Response;
      window.Request = Request;
      window.Headers = Headers;
      if (!window.crypto) window.crypto = require("crypto").webcrypto;
      window.localStorage.setItem("prtds.lang", lang);
      const token = TOKENS[file];
      if (token) window.sessionStorage.setItem(token[0], token[1]);
    },
  });
  // страницы грузят данные асинхронно — даём отрисовке завершиться
  await new Promise((resolve) => setTimeout(resolve, 2600));

  const strings = new Set();
  const walker = dom.window.document.createTreeWalker(dom.window.document.body, 4 /* SHOW_TEXT */);
  let node;
  while ((node = walker.nextNode())) {
    const parent = node.parentElement;
    if (parent && ["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE"].includes(parent.tagName)) continue;
    // хром переключателя языков — не текст платформы
    if (parent && parent.closest && parent.closest(".lang-switch")) continue;
    const text = (node.nodeValue || "").replace(/\s+/g, " ").trim();
    if (text) strings.add(text);
  }
  const htmlLang = dom.window.document.documentElement.lang;
  dom.window.close();
  return { strings, errors, htmlLang };
}

(async () => {
  if (!fs.existsSync(DIR)) {
    console.error(`нет папки ${DIR} — сначала соберите демо: python scripts/build_offline_demo.py`);
    process.exit(2);
  }

  const baseline = {};
  for (const file of PAGES) baseline[file] = (await render(file, "es")).strings;

  let untranslatedTotal = 0;
  let errorsTotal = 0;

  for (const lang of LANGS.slice(1)) {
    console.log(`════ язык: ${lang} ════`);
    for (const file of PAGES) {
      const { strings, errors, htmlLang } = await render(file, lang);
      errorsTotal += errors.length;

      // строки, которые были на испанском в ES-рендере и остались там же
      const left = [...baseline[file]]
        .filter((text) => strings.has(text))
        .filter((text) => SPANISH.test(text))
        .filter((text) => !KEEP.some((pattern) => pattern.test(text)));

      untranslatedTotal += left.length;
      const status = left.length ? `НЕ ПЕРЕВЕДЕНО: ${left.length}` : "переведено полностью";
      console.log(
        `  ${file.padEnd(18)} <html lang="${htmlLang}"> · строк ${String(strings.size).padEnd(4)} · ошибок ${errors.length} · ${status}`
      );
      for (const text of left.slice(0, 8)) console.log(`      • ${text.slice(0, 110)}`);
      if (errors.length) console.log(`      ! ${errors[0].slice(0, 110)}`);
    }
  }

  console.log(`\nИТОГО: непереведённых испанских строк ${untranslatedTotal}, ошибок консоли ${errorsTotal}`);
  process.exit(untranslatedTotal > 0 || errorsTotal > 0 ? 1 : 0);
})();
