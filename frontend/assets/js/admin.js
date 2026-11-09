/* Admin console: taxonomy, publication pipeline, maintenance and audit tables. */

import { get, post, patch, tokens } from "./api.js";
import { badge, escapeHtml, fmtDateTime, fmtPyg, SETTLEMENT_STATUS_ES, statusBadge } from "./format.js";

const el = {
  gate: document.getElementById("gate"),
  gateForm: document.getElementById("gate-form"),
  gateError: document.getElementById("gate-error"),
  token: document.getElementById("token"),
  panel: document.getElementById("panel"),
  stats: document.getElementById("stats"),
  statsNotes: document.getElementById("stats-notes"),
  categories: document.getElementById("categories"),
  categoryForm: document.getElementById("category-form"),
  categoryMessage: document.getElementById("category-message"),
  publicationForm: document.getElementById("publication-form"),
  publicationMessage: document.getElementById("publication-message"),
  settlements: document.getElementById("settlements"),
  events: document.getElementById("events"),
  maintenanceMessage: document.getElementById("maintenance-message"),
};

function metric(label, value, hint = "") {
  return `<div class="metric"><div class="label">${escapeHtml(label)}</div>
    <div class="value">${escapeHtml(value)}</div>
    ${hint ? `<div class="hint">${escapeHtml(hint)}</div>` : ""}</div>`;
}

function renderStats(data) {
  const catalog = data.catalog || {};
  const econ = data.economics || {};
  el.stats.innerHTML = [
    metric("Fichas publicadas", catalog.published_cards ?? 0, "Lo que ve una persona"),
    metric("Personas jurídicas", catalog.legal_entities_in_registry ?? 0, "Registro maestro; NO son fichas"),
    metric("Registros de empresa", catalog.company_records_total ?? 0, "Incluye staging y borradores"),
    metric("Contratos activos", data.commerce?.active_contracts ?? 0, "Única base de cobro"),
    metric("Solicitudes", data.funnel?.leads_total ?? 0, "Entregadas con consentimiento"),
    metric("Eventos del ledger", data.funnel?.events_total ?? 0, "Append-only, con idempotencia"),
    metric("Ingreso PRTDS", econ.prtds_revenue_display || fmtPyg(0), "Comisión, no GMV"),
    metric("GMV confirmado", econ.gmv_display || fmtPyg(0), "Ventas de los comercios"),
  ].join("");

  const byStatus = Object.entries(catalog.by_status || {})
    .map(([status, count]) => `${badge(status, status === "published" ? "ok" : "neutral")} ${count}`)
    .join(" ");

  el.statsNotes.innerHTML = `
    <div class="notice tiny">${escapeHtml(catalog.warning_es || "")}</div>
    <p class="small" style="margin:8px 0 0">Fichas por estado: ${byStatus || "—"}</p>
    ${(econ.alerts || [])
      .filter((alert) => alert.count > 0)
      .map((alert) => `<div class="notice warn tiny"><strong>${escapeHtml(alert.code)}</strong> · ${alert.count}: ${escapeHtml(alert.message_es)}</div>`)
      .join("")}`;
}

function categoryRows(items, depth = 0) {
  return items
    .map((category) => {
      const children = category.children?.length ? categoryRows(category.children, depth + 1) : "";
      return `<tr>
        <td style="padding-left:${10 + depth * 18}px">
          ${depth ? "└ " : ""}<strong>${escapeHtml(category.name_es)}</strong>
          <span class="mono tiny muted">${escapeHtml(category.slug)}</span>
        </td>
        <td class="num">${category.published_companies ?? 0}</td>
        <td>${escapeHtml(category.default_intent)}</td>
        <td class="tiny muted">${category.is_active ? "activa" : "inactiva"}</td>
        <td><button class="btn small ghost" data-toggle="${escapeHtml(category.slug)}" data-active="${category.is_active}">
          ${category.is_active ? "Desactivar" : "Activar"}</button></td>
      </tr>${children}`;
    })
    .join("");
}

async function renderCategories() {
  const data = await get("/api/admin/categories", { auth: "admin" });
  el.categories.innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>Categoría</th><th class="num">Fichas</th><th>Acción principal</th><th>Estado</th><th></th></tr></thead>
    <tbody>${categoryRows(data.categories || [])}</tbody></table></div>`;
}

async function renderCommerce() {
  const [settlements, events] = await Promise.all([
    get("/api/admin/settlements?limit=50", { auth: "admin" }),
    get("/api/admin/funnel/events?limit=30", { auth: "admin" }),
  ]);

  el.settlements.innerHTML = `<table>
    <thead><tr><th>Solicitud</th><th>Base (GMV)</th><th class="num">Comisión</th><th class="num">Margen</th><th>Estado</th><th>Motivo</th></tr></thead>
    <tbody>${
      (settlements.settlements || [])
        .map(
          (row) => `<tr>
            <td class="mono tiny">${escapeHtml(row.lead_ref || "—")}</td>
            <td>${escapeHtml(row.basis_amount_display)}</td>
            <td class="num">${escapeHtml(row.commission_display)}</td>
            <td class="num">${escapeHtml(row.contribution_margin_display)}</td>
            <td>${statusBadge(SETTLEMENT_STATUS_ES, row.status)}</td>
            <td class="tiny muted">${escapeHtml(row.status_reason_es || "")}</td>
          </tr>`
        )
        .join("") || '<tr><td colspan="6" class="muted">Sin liquidaciones.</td></tr>'
    }</tbody></table>`;

  el.events.innerHTML = `<table>
    <thead><tr><th>Cuándo</th><th>Evento</th><th>Origen</th><th class="num">Importe</th><th>Prueba</th></tr></thead>
    <tbody>${
      (events.events || [])
        .map(
          (row) => `<tr>
            <td class="tiny nowrap">${escapeHtml(fmtDateTime(row.occurred_at))}</td>
            <td><span class="mono tiny">${escapeHtml(row.event_type)}</span></td>
            <td class="tiny">${escapeHtml(row.source || "—")}</td>
            <td class="num tiny">${row.amount_pyg ? escapeHtml(fmtPyg(row.amount_pyg)) : "—"}</td>
            <td class="tiny muted">${escapeHtml(row.actor_kind)}${row.disputed ? " · en disputa" : ""}</td>
          </tr>`
        )
        .join("") || '<tr><td colspan="5" class="muted">Sin eventos.</td></tr>'
    }</tbody></table>`;
}

async function refreshAll() {
  try {
    const stats = await get("/api/admin/stats", { auth: "admin" });
    renderStats(stats);
    await renderCategories();
    await renderCommerce();
  } catch (error) {
    el.statsNotes.innerHTML = `<div class="notice danger">${escapeHtml(error.message)}</div>`;
  }
}

function flash(target, message, tone = "ok") {
  target.innerHTML = `<div class="notice ${tone}">${escapeHtml(message)}</div>`;
  window.setTimeout(() => (target.innerHTML = ""), 8000);
}

el.gateForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  tokens.admin = el.token.value.trim();
  el.gateError.innerHTML = "";
  try {
    await get("/api/admin/stats", { auth: "admin" });
    el.gate.classList.add("hidden");
    el.panel.classList.remove("hidden");
    await refreshAll();
  } catch (error) {
    tokens.admin = "";
    el.gateError.innerHTML = `<div class="notice danger">${escapeHtml(error.message)}</div>`;
  }
});

document.getElementById("logout").addEventListener("click", () => {
  tokens.admin = "";
  el.panel.classList.add("hidden");
  el.gate.classList.remove("hidden");
});

document.getElementById("refresh").addEventListener("click", refreshAll);

el.categoryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const synonyms = document.getElementById("cat-syn").value
    .split(",")
    .map((word) => word.trim())
    .filter(Boolean);
  const payload = {
    slug: document.getElementById("cat-slug").value.trim(),
    name_es: document.getElementById("cat-name").value.trim(),
    parent_slug: document.getElementById("cat-parent").value.trim() || null,
    default_intent: document.getElementById("cat-intent").value,
    description_es: document.getElementById("cat-desc").value.trim() || null,
    synonyms_es: synonyms.length ? synonyms : null,
  };
  try {
    const created = await post("/api/admin/categories", payload, { auth: "admin" });
    if (synonyms.length) await patch(`/api/admin/categories/${encodeURIComponent(created.slug)}`, { synonyms_es: synonyms }, { auth: "admin" });
    flash(el.categoryMessage, `Categoría creada: ${created.name_es} (${created.slug})`);
    el.categoryForm.reset();
    await renderCategories();
  } catch (error) {
    flash(el.categoryMessage, error.message, "danger");
  }
});

el.categories.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-toggle]");
  if (!button) return;
  button.disabled = true;
  try {
    await patch(
      `/api/admin/categories/${encodeURIComponent(button.dataset.toggle)}`,
      { is_active: button.dataset.active !== "true" },
      { auth: "admin" }
    );
    await renderCategories();
  } catch (error) {
    flash(el.categoryMessage, error.message, "danger");
    button.disabled = false;
  }
});

el.publicationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const slug = document.getElementById("pub-slug").value.trim();
  const status = document.getElementById("pub-status").value;
  try {
    const result = await post(
      `/api/admin/companies/${encodeURIComponent(slug)}/publication`,
      { status, reason: "cambio desde consola de administración" },
      { auth: "admin" }
    );
    flash(
      el.publicationMessage,
      `${result.slug}: ${result.previous_status} → ${result.status}. ${result.note_es}`
    );
    await refreshAll();
  } catch (error) {
    flash(el.publicationMessage, error.message, "danger");
  }
});

document.getElementById("reindex").addEventListener("click", async (event) => {
  event.target.disabled = true;
  try {
    const result = await post("/api/admin/reindex", {}, { auth: "admin" });
    flash(el.maintenanceMessage, `${result.reindexed_companies} fichas reindexadas. ${result.note_es}`);
  } catch (error) {
    flash(el.maintenanceMessage, error.message, "danger");
  } finally {
    event.target.disabled = false;
  }
});

document.getElementById("reseed").addEventListener("click", async (event) => {
  if (!window.confirm("Se reconstruyen los datos de demostración. ¿Continuar?")) return;
  event.target.disabled = true;
  try {
    const result = await post("/api/admin/reseed", {}, { auth: "admin" });
    flash(el.maintenanceMessage, `Datos reiniciados: ${result.companies} empresas, ${result.published_companies} publicadas.`);
    await refreshAll();
  } catch (error) {
    flash(el.maintenanceMessage, error.message, "danger");
  } finally {
    event.target.disabled = false;
  }
});

if (tokens.admin) {
  el.token.value = tokens.admin;
  get("/api/admin/stats", { auth: "admin" })
    .then(() => {
      el.gate.classList.add("hidden");
      el.panel.classList.remove("hidden");
      refreshAll();
    })
    .catch(() => (tokens.admin = ""));
}
