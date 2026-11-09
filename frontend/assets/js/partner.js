/* Partner cabinet: manual reconciliation of requests and confirmed results.
 *
 * What the cabinet must make impossible to confuse (concept §07, §10, §15):
 *  - a WhatsApp click is not a customer;
 *  - the seller's amount (GMV) is not PRTDS revenue;
 *  - a settlement without an active contract yields zero commission;
 *  - a non-positive contribution margin is flagged, not hidden.
 */

import { get, post, tokens } from "./api.js";
import {
  badge,
  escapeHtml,
  fmtDateTime,
  fmtPyg,
  LEAD_STATUS_ES,
  SETTLEMENT_STATUS_ES,
  statusBadge,
} from "./format.js";

const el = {
  gate: document.getElementById("gate"),
  gateForm: document.getElementById("gate-form"),
  gateError: document.getElementById("gate-error"),
  token: document.getElementById("token"),
  panel: document.getElementById("panel"),
  title: document.getElementById("panel-title"),
  subtitle: document.getElementById("panel-subtitle"),
  tabs: document.querySelectorAll(".tabs button"),
  dashboard: document.getElementById("tab-dashboard"),
  leads: document.getElementById("tab-leads"),
  settlements: document.getElementById("tab-settlements"),
};

let me = null;
let leadFilter = "";

function metric(label, value, hint = "") {
  return `<div class="metric"><div class="label">${escapeHtml(label)}</div>
    <div class="value">${escapeHtml(value)}</div>
    ${hint ? `<div class="hint">${escapeHtml(hint)}</div>` : ""}</div>`;
}

function eventRow(event) {
  return `<tr>
    <td><span class="mono tiny">${escapeHtml(event.code)}</span></td>
    <td class="num">${event.count}</td>
    <td class="tiny">${escapeHtml(event.proves_es)}</td>
    <td class="tiny muted">${escapeHtml(event.does_not_prove_es)}</td>
  </tr>`;
}

async function renderDashboard() {
  el.dashboard.innerHTML = '<div class="card"><div class="skeleton"></div></div>';
  const data = await get("/api/partner/dashboard", { auth: "partner" });
  const funnel = data.funnel || {};
  const econ = data.economics || {};
  const counts = funnel.leads_by_status || {};
  const conv = funnel.conversion || {};

  const events = (funnel.events || []).filter((event) => event.count > 0);

  el.dashboard.innerHTML = `
    <div class="metrics">
      ${metric("Solicitudes nuevas", counts.submitted || 0, "Entregadas, aún sin respuesta")}
      ${metric("Aceptadas", counts.accepted || 0, "Confirmadas por el comercio")}
      ${metric("Ventas confirmadas", counts.sale_confirmed || 0, "Con evidencia cargada")}
      ${metric("Tasa de aceptación", conv.lead_acceptance_rate !== null ? `${(conv.lead_acceptance_rate * 100).toFixed(1)}%` : "—", "Aceptadas / entregadas")}
    </div>

    <div class="metrics" style="margin-top:10px">
      ${metric("GMV del comercio", econ.gmv_display || fmtPyg(0), "Ventas confirmadas; NO es ingreso de PRTDS")}
      ${metric("Ingreso PRTDS", econ.prtds_revenue_display || fmtPyg(0), "Solo comisión contractual")}
      ${metric("Margen de contribución", econ.contribution_margin_display || fmtPyg(0), "Comisión − costos variables")}
      ${metric("Recompras", econ.counters?.repeat_purchases || 0, "Dentro de los consentimientos")}
    </div>

    <div class="card" style="margin-top:14px">
      <h2>Eventos registrados <span class="badge neutral">qué prueba cada uno</span></h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Evento</th><th class="num">Cantidad</th><th>Qué prueba</th><th>Qué NO prueba</th></tr></thead>
          <tbody>${events.map(eventRow).join("") || '<tr><td colspan="4" class="muted">Sin eventos en el período.</td></tr>'}</tbody>
        </table>
      </div>
      <p class="tiny muted" style="margin:10px 0 0">${escapeHtml(funnel.warning_es || "")}</p>
    </div>

    <div class="card">
      <h2>Alertas de economía</h2>
      ${(econ.alerts || [])
        .filter((alert) => alert.count > 0)
        .map((alert) => `<div class="notice ${alert.code === "negative_contribution_margin" ? "danger" : "warn"}">
            <strong>${escapeHtml(alert.code)}</strong> · ${alert.count} caso(s). ${escapeHtml(alert.message_es)}
          </div>`)
        .join("") || '<div class="notice ok">Sin alertas: todas las operaciones tienen margen positivo y contrato.</div>'}
      ${data.card_health ? `<dl class="kv" style="margin-top:12px">
          <dt>Estado de la ficha</dt><dd>${escapeHtml(data.card_health.publication_status)}</dd>
          <dt>Verificación</dt><dd>${escapeHtml(data.card_health.verification_level)}</dd>
          <dt>Sucursales / ofertas</dt><dd>${data.card_health.branches} / ${data.card_health.offers}</dd>
          <dt>Ofertas con datos vencidos</dt><dd>${data.card_health.stale_offers}</dd>
          <dt>Última observación</dt><dd>${escapeHtml(data.card_health.last_observed_at || "—")}</dd>
        </dl>` : ""}
      <h3 style="margin-top:14px">Tareas sugeridas</h3>
      <ul class="clean small">${(data.todo_es || []).map((todo) => `<li>${escapeHtml(todo)}</li>`).join("")}</ul>
    </div>`;
}

function leadRow(lead) {
  const actions = [];
  (lead.allowed_transitions || []).forEach((status) => {
    if (status === "sale_confirmed") return;
    const label = LEAD_STATUS_ES[status]?.label || status;
    const tone = status === "rejected" || status === "cancelled" ? "danger" : "primary";
    actions.push(
      `<button class="btn small ${tone === "danger" ? "danger" : ""}" data-transition="${status}" data-ref="${escapeHtml(lead.ref_code)}">${escapeHtml(label)}</button>`
    );
  });
  if (!["sale_confirmed", "rejected", "cancelled"].includes(lead.status)) {
    actions.push(`<button class="btn small primary" data-sale="${escapeHtml(lead.ref_code)}">Confirmar venta</button>`);
  }

  return `<article class="card" data-lead="${escapeHtml(lead.ref_code)}">
    <div class="spread">
      <div>
        <strong class="mono">${escapeHtml(lead.ref_code)}</strong>
        <div class="tiny muted">${escapeHtml(fmtDateTime(lead.submitted_at))}</div>
      </div>
      ${statusBadge(LEAD_STATUS_ES, lead.status)}
    </div>
    <dl class="kv" style="margin-top:10px">
      <dt>Empresa</dt><dd>${escapeHtml(lead.company?.display_name || "—")}</dd>
      <dt>Sucursal</dt><dd>${escapeHtml(lead.branch?.name_es || "—")}</dd>
      <dt>Cliente</dt><dd>${escapeHtml(lead.customer_name || "sin nombre")} ${lead.customer_phone ? `· <span class="mono">${escapeHtml(lead.customer_phone)}</span>` : ""}</dd>
      ${lead.offer ? `<dt>Oferta</dt><dd>${escapeHtml(lead.offer.title_es)}</dd>` : ""}
      ${lead.requested_at ? `<dt>Cuándo</dt><dd>${escapeHtml(lead.requested_at)}</dd>` : ""}
      <dt>Mensaje</dt><dd>${escapeHtml(lead.message || lead.prefilled_message || "—")}</dd>
      ${lead.attribution ? `<dt>Atribución</dt><dd>${escapeHtml(lead.attribution.channel)} · ${escapeHtml(lead.attribution.method)} · confianza ${escapeHtml(lead.attribution.confidence)}</dd>` : ""}
      ${lead.confirmed_amount_display ? `<dt>Resultado confirmado</dt><dd><strong>${escapeHtml(lead.confirmed_amount_display)}</strong>${lead.proof_ref ? ` · comprobante ${escapeHtml(lead.proof_ref)}` : ""}</dd>` : ""}
    </dl>
    ${lead.partner_note ? `<p class="tiny muted" style="margin-top:8px">Nota: ${escapeHtml(lead.partner_note)}</p>` : ""}
    <div class="btn-row" style="margin-top:12px">${actions.join("") || '<span class="muted tiny">Sin transiciones disponibles.</span>'}</div>
    <div class="lead-detail"></div>
  </article>`;
}

async function renderLeads() {
  el.leads.innerHTML = '<div class="card"><div class="skeleton"></div></div>';
  const params = new URLSearchParams({ limit: "50" });
  if (leadFilter) params.set("status", leadFilter);
  const data = await get(`/api/partner/leads?${params.toString()}`, { auth: "partner" });

  const filters = Object.entries(data.counts_by_status || {})
    .map(([status, count]) => `<button class="chip" data-filter="${escapeHtml(status)}" aria-pressed="${leadFilter === status}">${escapeHtml(LEAD_STATUS_ES[status]?.label || status)} <span class="count">${count}</span></button>`)
    .join("");

  el.leads.innerHTML = `
    <div class="chips" style="padding-bottom:10px">
      <button class="chip" data-filter="" aria-pressed="${leadFilter === ""}">Todas</button>
      ${filters}
    </div>
    ${(data.leads || []).map(leadRow).join("") || '<div class="notice warn">No hay solicitudes con este filtro.</div>'}`;
}

async function renderSettlements() {
  el.settlements.innerHTML = '<div class="card"><div class="skeleton"></div></div>';
  const data = await get("/api/partner/settlements?limit=100", { auth: "partner" });
  const rows = (data.settlements || [])
    .map(
      (settlement) => `<tr>
        <td class="mono tiny">${escapeHtml(settlement.lead_ref || "—")}</td>
        <td>${escapeHtml(settlement.company?.display_name || "—")}</td>
        <td class="num">${escapeHtml(settlement.basis_amount_display)}</td>
        <td class="num">${settlement.rule ? `${settlement.rule.rate_percent}%` : "—"}</td>
        <td class="num"><strong>${escapeHtml(settlement.commission_display)}</strong></td>
        <td class="num">${escapeHtml(settlement.contribution_margin_display)}</td>
        <td>${statusBadge(SETTLEMENT_STATUS_ES, settlement.status)}</td>
        <td class="tiny muted">${escapeHtml(settlement.status_reason_es || "")}</td>
      </tr>`
    )
    .join("");

  el.settlements.innerHTML = `<div class="card">
    <h2>Liquidaciones</h2>
    <p class="muted small">
      Base = venta del comercio (GMV). Comisión = ingreso de PRTDS. Sin contrato activo la
      comisión es cero, aunque la venta esté confirmada.
    </p>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Solicitud</th><th>Empresa</th><th class="num">Base (GMV)</th><th class="num">Tasa</th>
        <th class="num">Comisión</th><th class="num">Margen</th><th>Estado</th><th>Motivo</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="8" class="muted">Sin liquidaciones registradas.</td></tr>'}</tbody>
      </table>
    </div>
  </div>`;
}

function openSaleForm(ref) {
  const container = document.querySelector(`[data-lead="${CSS.escape(ref)}"] .lead-detail`);
  if (!container) return;
  container.innerHTML = `
    <form class="card" data-sale-form="${escapeHtml(ref)}" style="margin-top:12px;background:#fafbfe">
      <h3>Confirmar resultado</h3>
      <p class="muted tiny">
        Cargá el importe realmente cobrado por el comercio y una referencia de comprobante.
        PRTDS calculará su comisión según el contrato; el importe cargado nunca se cuenta como ingreso propio.
      </p>
      <div class="field-row split">
        <div class="field">
          <label for="amount-${escapeHtml(ref)}">Importe (G.)</label>
          <input id="amount-${escapeHtml(ref)}" name="amount" type="number" min="0" step="1" required placeholder="180000" />
        </div>
        <div class="field">
          <label for="proof-${escapeHtml(ref)}">Comprobante</label>
          <input id="proof-${escapeHtml(ref)}" name="proof" type="text" maxlength="120" placeholder="FACT-0001" />
        </div>
      </div>
      <div class="field">
        <label class="checkbox"><input type="checkbox" name="repeat" /> Es una recompra del mismo cliente</label>
      </div>
      <div class="btn-row">
        <button class="btn primary small" type="submit">Confirmar</button>
        <button class="btn small ghost" type="button" data-cancel>Cancelar</button>
      </div>
      <div class="sale-error"></div>
    </form>`;
}

async function refreshAll() {
  try {
    await renderDashboard();
    await renderLeads();
    await renderSettlements();
  } catch (error) {
    el.dashboard.innerHTML = `<div class="notice danger">${escapeHtml(error.message)}</div>`;
  }
}

async function enter() {
  el.gateError.innerHTML = "";
  try {
    me = await get("/api/partner/me", { auth: "partner" });
    el.gate.classList.add("hidden");
    el.panel.classList.remove("hidden");
    el.title.textContent = me.company ? me.company.display_name : "Operaciones PRTDS";
    el.subtitle.innerHTML = `${escapeHtml(me.full_name)} · ${escapeHtml(me.role)} · alcance ${escapeHtml(me.scope === "single_company" ? "una empresa" : "todas las empresas")}`;
    await refreshAll();
  } catch (error) {
    tokens.partner = "";
    el.gateError.innerHTML = `<div class="notice danger">${escapeHtml(error.message)}</div>`;
  }
}

el.gateForm.addEventListener("submit", (event) => {
  event.preventDefault();
  tokens.partner = el.token.value.trim();
  if (!tokens.partner) return;
  enter();
});

document.getElementById("logout").addEventListener("click", () => {
  tokens.partner = "";
  me = null;
  el.panel.classList.add("hidden");
  el.gate.classList.remove("hidden");
});

document.getElementById("refresh").addEventListener("click", refreshAll);

el.tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    el.tabs.forEach((other) => other.setAttribute("aria-selected", String(other === tab)));
    ["dashboard", "leads", "settlements"].forEach((name) => {
      el[name].classList.toggle("hidden", name !== tab.dataset.tab);
    });
  });
});

el.leads.addEventListener("click", async (event) => {
  const filter = event.target.closest("[data-filter]");
  if (filter) {
    leadFilter = filter.dataset.filter;
    await renderLeads();
    return;
  }
  if (event.target.closest("[data-cancel]")) {
    event.target.closest("form").remove();
    return;
  }
  const sale = event.target.closest("[data-sale]");
  if (sale) {
    openSaleForm(sale.dataset.sale);
    return;
  }
  const transition = event.target.closest("[data-transition]");
  if (transition) {
    transition.disabled = true;
    const note = window.prompt("Nota para el registro (opcional):", "") || null;
    try {
      await post(
        `/api/partner/leads/${encodeURIComponent(transition.dataset.ref)}/decision`,
        { status: transition.dataset.transition, note },
        { auth: "partner" }
      );
      await renderLeads();
      await renderDashboard();
    } catch (error) {
      window.alert(error.message);
      transition.disabled = false;
    }
  }
});

el.leads.addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-sale-form]");
  if (!form) return;
  event.preventDefault();
  const errorBox = form.querySelector(".sale-error");
  const payload = {
    amount_pyg: Number(form.amount.value || 0),
    proof_ref: form.proof.value.trim() || null,
    is_repeat: form.repeat.checked,
  };
  try {
    const result = await post(
      `/api/partner/leads/${encodeURIComponent(form.dataset.saleForm)}/sale`,
      payload,
      { auth: "partner" }
    );
    const settlement = result.settlement || {};
    window.alert(
      `Resultado confirmado.\n\nVenta del comercio (GMV): ${settlement.basis_amount_display}\n` +
        `Comisión PRTDS: ${settlement.commission_display}\n` +
        `Margen de contribución: ${settlement.contribution_margin_display}\n` +
        `Estado: ${settlement.status}\n\n${settlement.status_reason_es || ""}`
    );
    await refreshAll();
  } catch (error) {
    errorBox.innerHTML = `<div class="notice danger">${escapeHtml(error.message)}</div>`;
  }
});

if (tokens.partner) {
  el.token.value = tokens.partner;
  enter();
}

export { badge, fmtPyg };
