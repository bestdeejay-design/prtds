/* Search page: query, filters, category chips, results and sponsored block.
 *
 * Sponsored results are rendered in a separate labelled block — a paid position
 * is never presented as the objectively best offer (concept §13.4).
 */

import { get, queryParam } from "./api.js";
import { escapeHtml, fmtPyg, hoursToday, statusBadge, VERIFICATION_ES, relativeAge } from "./format.js";
import { track, utmFromLocation } from "./tracking.js";

const state = {
  q: queryParam("q") || "",
  category: queryParam("categoria") || "",
  barrio: queryParam("barrio") || "",
  channel: queryParam("canal") || "",
  sort: queryParam("orden") || "relevance",
  max_price: queryParam("max") || "",
  page: 1,
  categories: [],
  facets: null,
  loading: false,
};

const el = {
  form: document.getElementById("search-form"),
  q: document.getElementById("q"),
  chips: document.getElementById("chips"),
  barrio: document.getElementById("barrio"),
  channel: document.getElementById("channel"),
  sort: document.getElementById("sort"),
  maxPrice: document.getElementById("max_price"),
  results: document.getElementById("results"),
  sponsored: document.getElementById("sponsored"),
  count: document.getElementById("results-count"),
  title: document.getElementById("results-title"),
  note: document.getElementById("ranking-note"),
  notice: document.getElementById("notice"),
  pager: document.getElementById("pager"),
  footerNotice: document.getElementById("footer-notice"),
};

const { utm, campaignId } = utmFromLocation();

function syncUrl() {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.category) params.set("categoria", state.category);
  if (state.barrio) params.set("barrio", state.barrio);
  if (state.channel) params.set("canal", state.channel);
  if (state.sort !== "relevance") params.set("orden", state.sort);
  if (state.max_price) params.set("max", state.max_price);
  if (state.page > 1) params.set("pagina", String(state.page));
  const query = params.toString();
  window.history.replaceState({}, "", query ? `/?${query}` : "/");
}

function renderChips() {
  const all = { slug: "", name_es: "Todas", published_companies: null };
  const items = [all, ...state.categories];
  el.chips.innerHTML = items
    .map((cat) => {
      const active = state.category === cat.slug;
      const count = cat.published_companies ? `<span class="count">${cat.published_companies}</span>` : "";
      return `<button type="button" class="chip" data-slug="${escapeHtml(cat.slug)}" aria-pressed="${active}">
        ${escapeHtml(cat.name_es)}${count}
      </button>`;
    })
    .join("");
}

function renderFacets() {
  if (!state.facets) return;
  const barrios = state.facets.barrios || [];
  el.barrio.innerHTML =
    '<option value="">Todos</option>' +
    barrios
      .map((b) => `<option value="${escapeHtml(b.name)}">${escapeHtml(b.name)} (${b.count})</option>`)
      .join("");
  el.barrio.value = state.barrio;
}

function actionButtons(item) {
  const branch = item.primary_branch;
  const buttons = [];
  if (branch?.channels?.whatsapp) {
    buttons.push(
      `<button type="button" class="btn whatsapp small" data-action="whatsapp" data-slug="${escapeHtml(item.slug)}" data-branch="${escapeHtml(branch.id)}">WhatsApp</button>`
    );
  }
  if (branch?.channels?.phone) {
    buttons.push(
      `<button type="button" class="btn small" data-action="call" data-slug="${escapeHtml(item.slug)}" data-branch="${escapeHtml(branch.id)}">Llamar</button>`
    );
  }
  if (branch?.map_url) {
    buttons.push(
      `<a class="btn small" href="${escapeHtml(branch.map_url)}" target="_blank" rel="noopener" data-action="route" data-slug="${escapeHtml(item.slug)}">Cómo llegar</a>`
    );
  }
  return buttons.join("");
}

/* Путь категории. Фильтр по категории включает все её подкатегории (дерево
 * таксономии), поэтому карточка суши-доставки законно попадает в «Gastronomía».
 * Без подписи это выглядит как сломанный фильтр — карточка сама показывает,
 * через какую подкатегорию она здесь: «Gastronomía › Delivery de comida».
 * Каждая часть в своём <span>, чтобы словарь переводов нашёл их по отдельности. */
const categoryPaths = {};

function indexCategoryPaths(nodes, trail) {
  (nodes || []).forEach((node) => {
    const path = [...trail, node.name_es];
    categoryPaths[node.slug] = path;
    indexCategoryPaths(node.children || [], path);
  });
}

function categoryTrail(item) {
  const trail = state.category ? categoryPaths[item.category_slug] : null;
  const names = trail && trail.length > 1 ? trail : item.category ? [item.category] : [];
  if (!names.length) return "";
  return `<span class="cat-trail">${names
    .map((name) => `<span>${escapeHtml(name)}</span>`)
    .join('<span class="sep">›</span>')}</span>`;
}

function renderResult(item, { sponsored = false } = {}) {
  const branch = item.primary_branch;
  const offer = item.offers_preview?.[0];
  const meta = [
    categoryTrail(item),
    item.barrios?.length ? `<span>${escapeHtml(item.barrios.slice(0, 3).join(", "))}</span>` : "",
    branch ? `<span>Hoy: ${escapeHtml(hoursToday(branch.opening_hours))}</span>` : "",
    item.min_price_display ? `<span>Desde <strong>${escapeHtml(item.min_price_display)}</strong></span>` : "",
    item.branch_count > 1 ? `<span>${item.branch_count} sucursales</span>` : "",
  ]
    .filter(Boolean)
    .join("");

  const badges = [
    sponsored ? '<span class="badge ad">Publicidad</span>' : "",
    statusBadge(VERIFICATION_ES, item.verification_level),
    item.published_at ? `<span class="tiny muted">Actualizada ${escapeHtml(relativeAge(item.published_at) || "—")}</span>` : "",
  ]
    .filter(Boolean)
    .join(" ");

  return `<article class="result" data-slug="${escapeHtml(item.slug)}">
    <div class="result-head">
      <div style="flex:1">
        <h3><a href="/empresa/${escapeHtml(item.slug)}">${escapeHtml(item.display_name)}</a></h3>
        <div class="tiny" style="margin-top:4px">${badges}</div>
      </div>
      ${offer ? `<div class="price">${escapeHtml(offer.price_display)}</div>` : ""}
    </div>
    ${item.short_description_es ? `<p class="muted small" style="margin:8px 0 0">${escapeHtml(item.short_description_es)}</p>` : ""}
    <div class="result-meta">${meta}</div>
    <div class="result-actions">
      ${actionButtons(item)}
      <a class="btn primary small" href="/empresa/${escapeHtml(item.slug)}">Ver ficha</a>
    </div>
  </article>`;
}

function renderSponsored(block) {
  const items = block?.items || [];
  if (!items.length) {
    el.sponsored.innerHTML = "";
    return;
  }
  el.sponsored.innerHTML = `
    <div class="card">
      <div class="spread">
        <h2 style="margin:0"><span class="badge ad">${escapeHtml(block.label_es || "Publicidad")}</span></h2>
        <span class="muted tiny">${escapeHtml(block.note_es || "")}</span>
      </div>
      <div class="stack" style="margin-top:10px">
        ${items.map((item) => renderResult(item, { sponsored: true })).join("")}
      </div>
    </div>`;
}

function renderPager(payload) {
  const { page, page_count: pageCount } = { page: payload.query.page, page_count: payload.page_count };
  if (pageCount <= 1) {
    el.pager.innerHTML = "";
    return;
  }
  const buttons = [];
  if (page > 1) buttons.push(`<button class="btn small" data-page="${page - 1}">← Anterior</button>`);
  buttons.push(`<span class="muted small" style="align-self:center">Página ${page} de ${pageCount}</span>`);
  if (page < pageCount) buttons.push(`<button class="btn small" data-page="${page + 1}">Siguiente →</button>`);
  el.pager.innerHTML = buttons.join("");
}

function skeleton() {
  el.results.innerHTML = Array.from({ length: 4 })
    .map(() => `<div class="card"><div class="skeleton" style="width:45%"></div><div class="skeleton" style="margin-top:10px"></div><div class="skeleton" style="margin-top:8px;width:70%"></div></div>`)
    .join("");
}

async function loadResults() {
  if (state.loading) return;
  state.loading = true;
  skeleton();
  syncUrl();

  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.category) params.set("category", state.category);
  if (state.barrio) params.set("barrio", state.barrio);
  if (state.channel) params.set("channel", state.channel);
  if (state.max_price) params.set("max_price", state.max_price);
  if (state.sort) params.set("sort", state.sort);
  params.set("page", String(state.page));
  params.set("limit", "20");
  if (campaignId) params.set("campaign_id", campaignId);

  try {
    const payload = await get(`/api/search?${params.toString()}`);
    const items = payload.results || [];
    el.title.textContent = state.category || state.q ? "Resultados" : "Empresas publicadas";
    // счётчик собирается из отдельных <span>: строка «3 fichas · 1 en publicidad»
    // целиком не переводится, а её части — переводятся
    el.count.innerHTML = [
      `<span>${payload.total} ${payload.total === 1 ? "ficha" : "fichas"}</span>`,
      payload.total_sponsored ? `<span>${payload.total_sponsored} en publicidad</span>` : "",
      payload.tracked_impressions ? `<span>${payload.tracked_impressions} impresiones registradas</span>` : "",
    ]
      .filter(Boolean)
      .join('<span class="sep">·</span>');

    const sponsoredItems = payload.sponsored?.items || [];
    el.results.innerHTML = items.length
      ? items.map((item) => renderResult(item)).join("")
      : sponsoredItems.length
        ? /* Органики нет, но под фильтр подошла оплаченная позиция (§13.4):
             говорить «ничего не найдено» рядом с подходящей карточкой — неправда. */
          `<div class="notice warn">
          <span>No hay fichas orgánicas para esta búsqueda.</span>
          <span>Abajo hay una posición contratada que coincide con el filtro.</span>
          <div class="tiny" style="margin-top:6px">
            <span>La publicidad nunca ocupa el lugar de la mejor oferta objetiva.</span>
          </div>
        </div>`
        : `<div class="notice warn">
          Sin resultados para esta búsqueda. Probá con menos palabras, sin acentos u otro barrio.
          <div class="tiny" style="margin-top:6px">
            Sugerencia: para buscar por precio usá el filtro «Precio máximo» y el orden «Precio más bajo».
          </div>
        </div>`;
    el.note.textContent = payload.ranking_note_es || "";
    renderSponsored(payload.sponsored);
    renderPager(payload);
  } catch (error) {
    el.results.innerHTML = `<div class="notice danger">No se pudo cargar la búsqueda: ${escapeHtml(error.message)}</div>`;
    el.sponsored.innerHTML = "";
    el.count.textContent = "";
  } finally {
    state.loading = false;
  }
}

/* ------------------------- event wiring ------------------------- */

let debounce;
el.q.addEventListener("input", () => {
  state.q = el.q.value.trim();
  state.page = 1;
  clearTimeout(debounce);
  debounce = setTimeout(loadResults, 260);
});

el.form.addEventListener("submit", (event) => {
  event.preventDefault();
  state.q = el.q.value.trim();
  state.page = 1;
  loadResults();
});

el.chips.addEventListener("click", (event) => {
  const chip = event.target.closest(".chip");
  if (!chip) return;
  state.category = chip.dataset.slug || "";
  state.page = 1;
  renderChips();
  loadResults();
});

[el.barrio, el.channel, el.sort].forEach((select) => {
  select.addEventListener("change", () => {
    state.barrio = el.barrio.value;
    state.channel = el.channel.value;
    state.sort = el.sort.value;
    state.page = 1;
    loadResults();
  });
});

el.maxPrice.addEventListener("change", () => {
  state.max_price = el.maxPrice.value;
  state.page = 1;
  loadResults();
});

el.pager.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-page]");
  if (!button) return;
  state.page = Number(button.dataset.page);
  loadResults();
  window.scrollTo({ top: 0, behavior: "smooth" });
});

/* WhatsApp / call / route from the results list: the transition is logged as an
 * attempt, never as a sale. */
el.results.addEventListener("click", onActionClick);
el.sponsored.addEventListener("click", onActionClick);

async function onActionClick(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    const card = event.target.closest(".result");
    if (card) track("view", { companySlug: card.dataset.slug, source: "search" });
    return;
  }
  const slug = button.dataset.slug;
  const branchId = button.dataset.branch || null;

  if (button.dataset.action === "route") {
    track("route_click", { companySlug: slug, branchId, source: "search" });
    return;
  }

  event.preventDefault();
  button.disabled = true;
  try {
    if (button.dataset.action === "whatsapp") {
      const { post } = await import("./api.js");
      const link = await post("/api/whatsapp-link", {
        company_slug: slug,
        branch_id: branchId,
        source: "search",
        campaign_id: campaignId,
        utm: utm || undefined,
      });
      window.open(link.url, "_blank", "noopener");
      showNotice(
        `Abrimos WhatsApp con un mensaje preparado. Referencia: <strong>${escapeHtml(link.reference)}</strong>. ${escapeHtml(link.disclaimer_es)}`,
        "ok"
      );
    } else if (button.dataset.action === "call") {
      const { post } = await import("./api.js");
      const link = await post("/api/call-link", { company_slug: slug, branch_id: branchId, source: "search" });
      window.location.href = link.url;
      showNotice(`Llamada iniciada. Referencia: <strong>${escapeHtml(link.reference)}</strong>.`, "ok");
    }
  } catch (error) {
    showNotice(error.message, "danger");
  } finally {
    button.disabled = false;
  }
}

function showNotice(html, tone = "warn") {
  el.notice.innerHTML = `<div class="notice ${tone}">${html}</div>`;
  window.setTimeout(() => {
    el.notice.innerHTML = "";
  }, 9000);
}

/* ------------------------- bootstrap ------------------------- */

async function boot() {
  el.q.value = state.q;
  el.sort.value = state.sort;

  try {
    const [cats, facets, status] = await Promise.all([
      get("/api/categories"),
      get("/api/facets"),
      get("/api/meta/status").catch(() => null),
    ]);
    state.categories = cats.categories || [];
    indexCategoryPaths(state.categories, []);
    state.facets = facets;
    renderChips();
    renderFacets();

    const notice = status?.demo_data_notice_es;
    if (notice) {
      el.notice.innerHTML = `<div class="notice warn">${escapeHtml(notice)}</div>`;
      el.footerNotice.textContent = notice;
    }
    const published = status?.catalog?.published_cards;
    if (typeof published === "number") {
      el.footerNotice.textContent = `${el.footerNotice.textContent} Fichas publicadas en este entorno: ${published}. Personas jurídicas en el registro: ${status.catalog.legal_entities_in_registry} (no son fichas).`;
    }
  } catch (error) {
    el.notice.innerHTML = `<div class="notice danger">No se pudo cargar la configuración inicial: ${escapeHtml(error.message)}</div>`;
  }

  await loadResults();
}

boot();

export { state, fmtPyg };
