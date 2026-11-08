/* Honest status page: renders /api/meta/status + the funnel dictionary. */

import { get } from "./api.js";
import { badge, escapeHtml, fmtPyg } from "./format.js";

const el = {
  summary: document.getElementById("summary"),
  numbers: document.getElementById("numbers"),
  numbersNotes: document.getElementById("numbers-notes"),
  funnel: document.getElementById("funnel"),
  notEquivalent: document.getElementById("not-equivalent"),
  pending: document.getElementById("pending"),
  demoNotice: document.getElementById("demo-notice"),
};

function metric(label, value, hint = "") {
  return `<div class="metric"><div class="label">${escapeHtml(label)}</div>
    <div class="value">${escapeHtml(value)}</div>
    ${hint ? `<div class="hint">${escapeHtml(hint)}</div>` : ""}</div>`;
}

async function boot() {
  try {
    const [status, funnel, market] = await Promise.all([
      get("/api/meta/status"),
      get("/api/meta/funnel"),
      get("/api/meta/market"),
    ]);

    el.summary.innerHTML = `
      <p class="small" style="margin-top:10px">${badge(status.slice, "neutral")} ${badge(status.app_env, "neutral")}
        ${badge(`${market.locale} · ${market.currency} sin decimales · ${market.timezone}`, "neutral")}</p>
      <div class="notice tiny">${escapeHtml(status.demo_data_notice_es || "")}</div>`;

    const catalog = status.catalog || {};
    const econ = status.economics || {};
    el.numbers.innerHTML = [
      metric("Fichas publicadas", catalog.published_cards ?? 0, "Visibles en la búsqueda"),
      metric("Personas jurídicas", catalog.legal_entities_in_registry ?? 0, "Registro maestro ≠ fichas"),
      metric("Solicitudes", econ.counters?.leads_total ?? 0, "Entregadas con consentimiento"),
      metric("Ventas confirmadas", econ.counters?.confirmed_sales ?? 0, "Con evidencia"),
      metric("GMV de comercios", econ.gmv_display || fmtPyg(0), "No es ingreso de PRTDS"),
      metric("Ingreso PRTDS", econ.prtds_revenue_display || fmtPyg(0), "Solo comisión contractual"),
      metric("Margen de contribución", econ.contribution_margin_display || fmtPyg(0), "Comisión − costos variables"),
      metric("Recompras", econ.counters?.repeat_purchases ?? 0, "Dentro de los consentimientos"),
    ].join("");

    el.numbersNotes.innerHTML = `
      <div class="notice tiny">${escapeHtml(catalog.warning_es || "")}</div>
      <div class="notice tiny">${escapeHtml(econ.warning_es || "")}</div>
      <p class="small" style="margin:6px 0 0">Fichas por estado: ${Object.entries(catalog.by_status || {})
        .map(([state, count]) => `${badge(state, state === "published" ? "ok" : "neutral")} ${count}`)
        .join(" ") || "—"}</p>`;

    el.funnel.innerHTML = `<table>
      <thead><tr><th>Etapa</th><th>Evento</th><th>Qué prueba</th><th>Qué NO prueba</th><th>Genera comisión</th></tr></thead>
      <tbody>${(funnel.events || [])
        .map(
          (event) => `<tr>
            <td>${badge(event.stage, "neutral")}</td>
            <td><span class="mono tiny">${escapeHtml(event.code)}</span></td>
            <td class="tiny">${escapeHtml(event.proves_es)}</td>
            <td class="tiny muted">${escapeHtml(event.does_not_prove_es)}</td>
            <td class="tiny">${event.commissionable ? badge("sí, con contrato", "ok") : badge("no", "neutral")}</td>
          </tr>`
        )
        .join("")}</tbody></table>`;

    el.notEquivalent.innerHTML = (funnel.not_equivalent_es || [])
      .map((line) => `<li>${escapeHtml(line)}</li>`)
      .join("");

    el.pending.innerHTML = (status.pending_verification_es || [])
      .map((line) => `<li>${escapeHtml(line)}</li>`)
      .join("");
    el.demoNotice.textContent = status.demo_data_notice_es || "";
  } catch (error) {
    el.summary.innerHTML = `<div class="notice danger">${escapeHtml(error.message)}</div>`;
  }
}

boot();
