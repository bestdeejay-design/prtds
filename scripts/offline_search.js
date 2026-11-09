/* Локальный поиск для офлайн-демо (подключается только сборщиком
 * scripts/build_offline_demo.py, на реальном сайте этого файла нет).
 *
 * Зачем он нужен
 * --------------
 * Раньше демо хранило готовые ответы API для ~49 комбинаций фильтров и
 * подставляло их по ключу запроса. Браузер всегда добавляет sort=relevance,
 * а записи были без него, поэтому точного совпадения не случалось почти
 * никогда, и «запасной» подбор ключей отбрасывал сам фильтр (категория →
 * баррио → канал → цена) раньше, чем sort. В итоге клик по категории
 * показывал весь каталог: 20 карточек вместо 3.
 *
 * Теперь демо считает выборку само — по тем же правилам, что и бэкенд
 * (backend/app/modules/catalog.py: search + _matches_query), поэтому работает
 * любая комбинация фильтров, а не только записанная.
 *
 * Что должно совпадать с бэкендом (проверяет scripts/check_offline_search.js):
 *   1. текст: ищем по свёрнутому блобу (без регистра и диакритики) фразой ИЛИ
 *      по имени компании ИЛИ всеми словами сразу;
 *   2. категория: всегда вместе с потомками (дерево таксономии);
 *   3. баррио/город: подстрока, без учёта регистра ASCII (как SQLite ILIKE);
 *   4. канал: whatsapp / phone / delivery / pickup по опубликованным филиалам;
 *   5. цена: одно активное предложение должно попасть в диапазон;
 *   6. сортировки relevance / name / recent / price_asc;
 *   7. рекламные карточки (§13.4) идут отдельным блоком и не занимают мест в
 *      органической выдаче, total считает только органику;
 *   8. пагинация: limit зажимается в 1..50, page_count = ceil(total/limit).
 *
 * Свернутые строки (fold_name, score_blob, search_blob) и надбавка за
 * свежесть считаются на этапе сборки настоящим питоновским fold() — чтобы
 * нормализация текста не разъехалась с бэкендом ни на один символ.
 */
(function () {
  "use strict";

  /* Тот же вес верификации, что в catalog._VERIFICATION_WEIGHT. */
  var VERIFICATION_WEIGHT = {
    field_verified: 15,
    partner_confirmed: 10,
    source_only: 5,
    unverified: 0,
  };

  /* SQLite lower() сворачивает только ASCII — это важно для точного
   * совпадения с ILIKE, поэтому для «сырых» полей используется именно оно. */
  function asciiLower(value) {
    return String(value == null ? "" : value).replace(/[A-Z]/g, function (ch) {
      return String.fromCharCode(ch.charCodeAt(0) + 32);
    });
  }

  /* Аналог app.core.text.fold(): NFKD, без диакритики, нижний регистр,
   * схлопнутые пробелы. */
  function fold(value) {
    if (!value) return "";
    var decomposed = String(value).normalize("NFKD");
    var withoutMarks = decomposed.replace(
      /[\u0300-\u036F\u1AB0-\u1AFF\u1DC0-\u1DFF\u20D0-\u20FF\uFE20-\uFE2F]/g,
      ""
    );
    return withoutMarks.toLowerCase().replace(/\s+/g, " ").trim();
  }

  function toInt(value, fallback) {
    if (value === null || value === undefined || value === "") return fallback;
    var parsed = parseInt(value, 10);
    return Number.isNaN(parsed) ? fallback : parsed;
  }

  /* Категория фильтруется вместе со всеми потомками (catalog.descendant_slugs). */
  function descendantSlugs(categories, slug) {
    var byParent = {};
    categories.forEach(function (cat) {
      var key = cat.parent_slug || "";
      (byParent[key] = byParent[key] || []).push(cat.slug);
    });
    var known = {};
    categories.forEach(function (cat) {
      known[cat.slug] = true;
    });
    if (!known[slug]) return [slug];
    var collected = [];
    var stack = [slug];
    while (stack.length) {
      var current = stack.pop();
      collected.push(current);
      (byParent[current] || []).forEach(function (child) {
        stack.push(child);
      });
    }
    return collected;
  }

  /* Аналог catalog._matches_query(): детерминированный скоринг релевантности. */
  function relevanceScore(company, needle) {
    if (!needle) return 10;
    var folded = fold(needle);
    var score = 0;
    if (company.fold_name === folded) score += 120;
    else if (company.fold_name.indexOf(folded) === 0) score += 90;
    else if (company.fold_name.indexOf(folded) !== -1) score += 60;
    if (company.score_blob.indexOf(folded) !== -1) score += 40;
    var tokens = folded.split(" ").filter(Boolean);
    var matched = tokens.filter(function (token) {
      return company.score_blob.indexOf(token) !== -1;
    }).length;
    if (tokens.length) score += Math.trunc((25 * matched) / tokens.length);
    if (tokens.length && matched === tokens.length && company.fold_name.indexOf(tokens[0]) === 0) {
      score += 15;
    }
    score += VERIFICATION_WEIGHT[company.verification_level] || 0;
    score += company.fresh_bonus || 0;
    return score;
  }

  /* Сортировка «цена вверх»: бэкенд берёт минимальную ненулевую цену активного
   * предложения, а без цены отправляет карточку в конец (10**15). */
  function minPrice(company) {
    var value = company.min_price_sort;
    return typeof value === "number" && value ? value : 1e15;
  }

  function publishedStamp(company) {
    if (!company.published_at) return -Infinity;
    var stamp = Date.parse(company.published_at);
    return Number.isNaN(stamp) ? -Infinity : stamp;
  }

  /**
   * @param {string} rawSearch строка запроса, как её собрал браузер ("?category=..." или "category=...")
   * @param {object} catalog   снимок каталога, записанный сборщиком
   * @returns объект той же формы, что и GET /api/search
   */
  function offlineSearch(rawSearch, catalog) {
    var meta = catalog.meta || {};
    var companies = catalog.companies || [];
    var categories = catalog.categories || [];
    var params = new URLSearchParams(String(rawSearch || "").replace(/^\?/, ""));

    var rawQuery = (params.get("q") || "").trim();
    var needle = rawQuery ? rawQuery.toLowerCase() : "";
    var categorySlug = params.get("category") || "";
    var barrio = params.get("barrio") || "";
    var city = params.get("city") || "";
    var channel = params.get("channel") || "";
    var rawMin = params.get("min_price");
    var rawMax = params.get("max_price");
    var minPriceFilter = rawMin === null || rawMin === "" ? null : toInt(rawMin, null);
    var maxPriceFilter = rawMax === null || rawMax === "" ? null : toInt(rawMax, null);
    var sort = params.get("sort") || "relevance";
    var page = Math.max(1, toInt(params.get("page"), 1));
    var limit = Math.min(50, Math.max(1, toInt(params.get("limit"), 20)));

    var tokens = needle ? fold(needle).split(" ").filter(Boolean) : [];
    var foldedNeedle = needle ? fold(needle) : "";
    var categorySet = {};
    if (categorySlug) {
      descendantSlugs(categories, categorySlug).forEach(function (slug) {
        categorySet[slug] = true;
      });
    }
    var barrioNeedle = barrio ? asciiLower(barrio.trim()) : "";
    var cityNeedle = city ? asciiLower(city.trim()) : "";

    var matched = companies.filter(function (company) {
      if (tokens.length) {
        var byPhrase = company.search_blob.indexOf(foldedNeedle) !== -1;
        var byName = asciiLower(company.display_name).indexOf(needle) !== -1;
        var byTokens = tokens.every(function (token) {
          return company.search_blob.indexOf(token) !== -1;
        });
        if (!byPhrase && !byName && !byTokens) return false;
      }
      if (categorySlug) {
        var slugs = company.category_slugs || [];
        if (!slugs.some(function (slug) { return categorySet[slug]; })) return false;
      }
      if (barrioNeedle) {
        var hitBarrio = (company.barrios || []).some(function (value) {
          return value && asciiLower(value).indexOf(barrioNeedle) !== -1;
        });
        if (!hitBarrio) return false;
      }
      if (cityNeedle) {
        var hitCity = (company.cities || []).some(function (value) {
          return value && asciiLower(value).indexOf(cityNeedle) !== -1;
        });
        if (!hitCity) return false;
      }
      if (channel) {
        var channels = company.channels || {};
        if (!channels[channel]) return false;
      }
      if (minPriceFilter !== null || maxPriceFilter !== null) {
        var hitPrice = (company.prices || []).some(function (value) {
          if (minPriceFilter !== null && value < minPriceFilter) return false;
          if (maxPriceFilter !== null && value > maxPriceFilter) return false;
          return true;
        });
        if (!hitPrice) return false;
      }
      return true;
    });

    /* Порядок базового массива — порядок строк в базе, поэтому устойчивая
     * сортировка JS даёт тот же результат, что и устойчивая сортировка Python. */
    /* Вторичные ключи — имя и slug, как в бэкенде: порядок карточек с равным
     * ключом должен быть одинаковым в демо и на сайте. */
    var byTiebreak = function (a, b) {
      var left = String(a.display_name || "").toLowerCase();
      var right = String(b.display_name || "").toLowerCase();
      if (left !== right) return left < right ? -1 : 1;
      return String(a.slug) < String(b.slug) ? -1 : String(a.slug) > String(b.slug) ? 1 : 0;
    };
    var ordered = matched.slice().sort(function (a, b) {
      var diff = relevanceScore(b, needle) - relevanceScore(a, needle);
      return diff !== 0 ? diff : byTiebreak(a, b);
    });
    if (sort === "name") {
      ordered = matched.slice().sort(byTiebreak);
    } else if (sort === "recent") {
      ordered = matched.slice().sort(function (a, b) {
        var diff = publishedStamp(b) - publishedStamp(a);
        return diff !== 0 ? diff : byTiebreak(a, b);
      });
    } else if (sort === "price_asc") {
      ordered = matched.slice().sort(function (a, b) {
        var diff = minPrice(a) - minPrice(b);
        return diff !== 0 ? diff : byTiebreak(a, b);
      });
    }

    var sponsored = ordered.filter(function (company) { return company.is_promoted; });
    var organic = ordered.filter(function (company) { return !company.is_promoted; });
    var total = organic.length;
    var start = (page - 1) * limit;
    var window = organic.slice(start, start + limit);
    var sponsoredItems = sponsored.slice(0, 3);
    var payloadOf = function (company) { return company.payload; };

    return {
      total_organic: organic.length,
      total_sponsored: sponsored.length,
      query: {
        q: needle || null,
        category: categorySlug || null,
        barrio: barrio || null,
        city: city || null,
        channel: channel || null,
        min_price: minPriceFilter,
        max_price: maxPriceFilter,
        sort: sort,
        page: page,
        limit: limit,
      },
      total: total,
      page_count: Math.ceil(total / limit),
      results: window.map(payloadOf),
      sponsored: {
        label_es: meta.sponsored_label_es || "Publicidad",
        note_es:
          meta.sponsored_note_es ||
          "Posiciones contratadas. No equivalen a la mejor oferta objetiva.",
        items: sponsoredItems.map(payloadOf),
      },
      ranking_note_es:
        meta.ranking_note_es ||
        "Orden por relevancia, verificación de datos y actualidad. " +
          "La publicidad se muestra por separado y siempre etiquetada.",
      /* Демонстрация без сервера ничего не сохраняет: счётчик показывает,
       * сколько карточек было бы зарегистрировано этим запросом (§07). */
      tracked_impressions: window.length + sponsoredItems.length,
      offline_computed: true,
    };
  }

  window.__PRTDS_OFFLINE_SEARCH__ = offlineSearch;
  window.__PRTDS_OFFLINE_FOLD__ = fold;
})();
