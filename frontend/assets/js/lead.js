/* Public read-back of a request: status only, no contact data, no money. */

import { get, pathParam } from "./api.js";
import { escapeHtml, fmtDateTime, LEAD_STATUS_ES, statusBadge } from "./format.js";

const ORDER = ["submitted", "accepted", "booked", "visit_done", "sale_confirmed"];

const el = {
  ref: document.getElementById("ref"),
  form: document.getElementById("lookup-form"),
  error: document.getElementById("lookup-error"),
  detail: document.getElementById("detail"),
};

function timeline(lead) {
  const currentIndex = ORDER.indexOf(lead.status);
  const rejected = ["rejected", "cancelled", "expired"].includes(lead.status);

  const steps = ORDER.map((status, index) => {
    const entry = LEAD_STATUS_ES[status];
    const done = currentIndex > index && !rejected;
    const current = currentIndex === index && !rejected;
    const when =
      status === "submitted" ? lead.submitted_at
      : status === "sale_confirmed" ? lead.confirmed_at
      : lead.decided_at && current ? lead.decided_at
      : null;
    return `<li class="${done ? "done" : current ? "current" : ""}">
      <strong>${escapeHtml(entry.label)}</strong>
      <div class="tiny muted">${escapeHtml(entry.hint)}</div>
      ${when ? `<div class="when">${escapeHtml(fmtDateTime(when))}</div>` : ""}
    </li>`;
  }).join("");

  if (rejected) {
    const entry = LEAD_STATUS_ES[lead.status];
    return steps + `<li class="current"><strong>${escapeHtml(entry.label)}</strong>
      <div class="tiny muted">${escapeHtml(entry.hint)}</div>
      ${lead.rejection_reason_es ? `<div class="tiny">Motivo: ${escapeHtml(lead.rejection_reason_es)}</div>` : ""}
      ${lead.decided_at ? `<div class="when">${escapeHtml(fmtDateTime(lead.decided_at))}</div>` : ""}
    </li>`;
  }
  return steps;
}

function render(lead) {
  el.detail.innerHTML = `
    <section class="card">
      <div class="spread">
        <div>
          <h2 style="margin:0">${escapeHtml(lead.ref_code)}</h2>
          <p class="muted small" style="margin:4px 0 0">
            ${lead.company ? escapeHtml(lead.company.display_name) : ""}
            ${lead.branch ? ` · ${escapeHtml(lead.branch.name_es)}` : ""}
          </p>
        </div>
        ${statusBadge(LEAD_STATUS_ES, lead.status)}
      </div>

      ${lead.offer ? `<p class="small" style="margin-top:10px">Consulta sobre: <strong>${escapeHtml(lead.offer.title_es)}</strong></p>` : ""}
      ${lead.requested_at ? `<p class="small">Cuándo lo necesitás: ${escapeHtml(lead.requested_at)}</p>` : ""}
      ${lead.message ? `<p class="small">Tu mensaje: «${escapeHtml(lead.message)}»</p>` : ""}

      <h3 style="margin-top:16px">Recorrido</h3>
      <ol class="timeline">${timeline(lead)}</ol>

      <div class="notice tiny" style="margin-top:14px">
        ${escapeHtml(LEAD_STATUS_ES[lead.status]?.hint || "")}
        Una solicitud entregada no es una venta: el comercio debe confirmar el resultado.
      </div>

      <div class="btn-row" style="margin-top:12px">
        ${lead.company ? `<a class="btn" href="/empresa/${escapeHtml(lead.company.slug)}">Volver a la ficha</a>` : ""}
        <a class="btn ghost" href="/">Buscar otra cosa</a>
      </div>
    </section>`;
}

async function load(ref) {
  el.error.innerHTML = "";
  if (!ref) return;
  try {
    const lead = await get(`/api/leads/${encodeURIComponent(ref)}`);
    window.history.replaceState({}, "", `/solicitud/${encodeURIComponent(lead.ref_code)}`);
    el.ref.value = lead.ref_code;
    render(lead);
  } catch (error) {
    el.detail.innerHTML = "";
    el.error.innerHTML = `<div class="notice danger">${escapeHtml(error.message)}</div>`;
  }
}

el.form.addEventListener("submit", (event) => {
  event.preventDefault();
  load(el.ref.value.trim());
});

const initial = pathParam(1);
if (initial) {
  el.ref.value = initial;
  load(initial);
}
