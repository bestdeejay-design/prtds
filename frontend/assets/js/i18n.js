/* Переключатель языков интерфейса: es (по умолчанию) / ru / en.
 *
 * Как это работает и почему именно так
 * ------------------------------------
 * Продукт остаётся Spanish-first (§02 концепции): испанский — язык по умолчанию,
 * русский и английский добавлены как языки просмотра для команды и партнёров.
 *
 * Перевод применяется поверх уже отрисованного DOM, а не через переписывание
 * шаблонов: ключ словаря — испанский оригинал строки. Это даёт три вещи:
 *   1. рабочий код экранов не меняется (нет риска сломать проверенное);
 *   2. переводятся и статические надписи, и то, что пришло из API;
 *   3. покрытие можно измерить (scripts/check_i18n_coverage.py).
 *
 * Не переводятся названия компаний, брендов, баррио, адреса, телефоны, SKU,
 * номера обращений и коды событий — это данные продавцов и идентификаторы,
 * а не текст платформы.
 */

import { RU, EN, PATTERNS, DATE_BITS } from "./i18n-dict.js";

export const LANGS = ["es", "ru", "en"];
export const LANG_LABELS = { es: "ES", ru: "RU", en: "EN" };
const STORAGE_KEY = "prtds.lang";
const HTML_LANG = { es: "es-PY", ru: "ru", en: "en" };

const HINTS = {
  es: "Interfaz traducible. Los nombres de comercios, marcas y barrios quedan en español: son datos de los vendedores.",
  ru: "Интерфейс переводится. Названия компаний, брендов и районов остаются на испанском — это данные продавцов.",
  en: "The interface is translated. Merchant, brand and neighborhood names stay in Spanish: that is seller data.",
};
const GROUP_LABEL = { es: "Idioma", ru: "Язык интерфейса", en: "Interface language" };

const DICTS = { es: null, ru: RU, en: EN };
const COMPILED = PATTERNS.map(([source, ru, en]) => [new RegExp(source), ru, en]);

/* --- состояние ---------------------------------------------------------- */

function readStored() {
  for (const store of [window.localStorage, window.sessionStorage]) {
    try {
      const value = store.getItem(STORAGE_KEY);
      if (value && LANGS.includes(value)) return value;
    } catch {
      /* приватный режим или file:// — просто идём дальше */
    }
  }
  return "es";
}

let current = readStored();

export function lang() {
  return current;
}

export function setLang(code) {
  if (!LANGS.includes(code)) return;
  current = code;
  for (const store of [window.localStorage, window.sessionStorage]) {
    try {
      store.setItem(STORAGE_KEY, code);
    } catch {
      /* не критично: язык просто не запомнится */
    }
  }
  apply();
}

/* --- перевод строки ----------------------------------------------------- */

function normalize(text) {
  return text.replace(/\s+/g, " ");
}

function translateDateBits(text, code) {
  const bits = DATE_BITS[code];
  if (!bits) return text;
  return text.replace(
    /\b(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\.|\b(a\. m\.|p\. m\.)/g,
    (match) => bits[match] || match
  );
}

/** Переводит строку; если перевода нет — возвращает оригинал. */
export function tr(raw) {
  if (typeof raw !== "string" || !raw.trim()) return raw;
  if (current === "es") return raw;

  const dict = DICTS[current];
  // текстовые узлы в HTML окружены переносами и отступами, поэтому ключ ищется
  // по строке без краевых пробелов; отступы возвращаются переводу обратно
  const text = normalize(raw).trim();
  const lead = raw.slice(0, raw.length - raw.replace(/^\s+/, "").length);
  const tail = raw.slice(raw.replace(/\s+$/, "").length);

  if (dict && Object.prototype.hasOwnProperty.call(dict, text)) {
    return lead + dict[text] + tail;
  }
  for (const [pattern, ru, en] of COMPILED) {
    const replacement = current === "ru" ? ru : en;
    if (pattern.test(text)) {
      return lead + translateDateBits(text.replace(pattern, replacement), current) + tail;
    }
  }
  // даты и прочие строки с испанскими месяцами, не попавшие в шаблоны
  const withDates = translateDateBits(text, current);
  if (withDates !== text) return lead + withDates + tail;
  return raw;
}

/* --- применение к DOM --------------------------------------------------- */

const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "TEXTAREA", "CODE", "PRE"]);
const TRANSLATABLE_ATTRS = ["placeholder", "title", "aria-label", "alt"];

const textOrigin = new WeakMap();
const attrOrigin = new WeakMap();

let applying = false;

function translateTextNode(node) {
  if (!node || node.nodeType !== 3) return;
  const parent = node.parentElement;
  if (parent && SKIP_TAGS.has(parent.tagName)) return;
  if (!textOrigin.has(node)) textOrigin.set(node, node.nodeValue);
  const source = textOrigin.get(node);
  const target = tr(source);
  if (target !== node.nodeValue) node.nodeValue = target;
}

function translateElement(element) {
  if (!element || element.nodeType !== 1 || SKIP_TAGS.has(element.tagName)) return;

  let store = attrOrigin.get(element);
  if (!store) {
    store = {};
    attrOrigin.set(element, store);
  }

  const attrs =
    element.tagName === "META" && element.getAttribute("name") === "description"
      ? [...TRANSLATABLE_ATTRS, "content"]
      : TRANSLATABLE_ATTRS;

  for (const attr of attrs) {
    if (!element.hasAttribute(attr)) continue;
    if (!(attr in store)) store[attr] = element.getAttribute(attr);
    const target = tr(store[attr]);
    if (target !== element.getAttribute(attr)) element.setAttribute(attr, target);
  }
}

function translateTree(node) {
  if (!node) return;
  if (node.nodeType === 3) {
    translateTextNode(node);
    return;
  }
  if (node.nodeType !== 1 && node.nodeType !== 11) return;
  if (node.dataset && node.dataset.noTranslate !== undefined) return;
  if (node.classList && node.classList.contains("lang-switch")) return;
  translateElement(node);
  const walker = document.createTreeWalker(node, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  let child = walker.nextNode();
  while (child) {
    if (child.nodeType === 3) translateTextNode(child);
    else if (!(child.dataset && child.dataset.noTranslate !== undefined) &&
             !(child.classList && child.classList.contains("lang-switch"))) {
      translateElement(child);
    }
    child = walker.nextNode();
  }
}

function translateDocumentTitle() {
  if (!titleOrigin) return;
  document.title = tr(titleOrigin);
}

let titleOrigin = "";

export function apply() {
  applying = true;
  try {
    document.documentElement.lang = HTML_LANG[current] || current;
    translateTree(document.body);
    translateDocumentTitle();
    renderSwitcher();
  } finally {
    applying = false;
  }
}

/* --- переключатель ------------------------------------------------------ */

function renderSwitcher() {
  const host = document.querySelector(".topbar-inner");
  if (!host) return;
  let box = host.querySelector(".lang-switch");
  if (!box) {
    box = document.createElement("div");
    box.className = "lang-switch";
    box.setAttribute("role", "group");
    box.dataset.noTranslate = "";
    host.appendChild(box);
  }
  box.setAttribute("aria-label", GROUP_LABEL[current]);
  box.title = HINTS[current];
  box.innerHTML =
    LANGS.map(
      (code) =>
        `<button type="button" data-lang="${code}" class="${code === current ? "on" : ""}"
           aria-pressed="${code === current}">${LANG_LABELS[code]}</button>`
    ).join("") + `<span class="lang-hint" data-no-translate>${HINTS[current]}</span>`;

  box.querySelectorAll("button[data-lang]").forEach((button) => {
    button.addEventListener("click", () => setLang(button.dataset.lang));
  });
}

/* --- наблюдение за динамической отрисовкой ------------------------------ */

function startObserver() {
  if (!window.MutationObserver || !document.body) return;
  const observer = new MutationObserver((records) => {
    if (applying || current === "es") return;
    applying = true;
    try {
      for (const record of records) {
        if (record.type === "attributes") translateElement(record.target);
        for (const node of record.addedNodes || []) translateTree(node);
      }
    } finally {
      applying = false;
    }
  });
  observer.observe(document.body, { childList: true, subtree: true, attributes: true,
    attributeFilter: TRANSLATABLE_ATTRS });
}

function init() {
  titleOrigin = document.title || "";
  renderSwitcher();
  if (current !== "es") apply();
  startObserver();
  window.PRTDS_I18N = { lang, setLang, tr, apply, LANGS };
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
