/* Company card — the screen that must work on a narrow display with a slow
 * mobile connection and offer clear actions (concept §02, §05):
 * WhatsApp · call · route · site · offer · request.
 *
 * Honesty rules applied here:
 *  - prices show their source, observation time and expiry (§09);
 *  - a conditional bank cashback is displayed separately, never inside the
 *    guaranteed total (§08.2);
 *  - a promoted card is always labelled as advertising (§13.4);
 *  - a WhatsApp click is an *attempt* to contact, not a sale (§07).
 */

import { get, post, pathParam, tokens } from "./api.js";
import {
  badge,
  escapeHtml,
  fmtDateTime,
  fmtPyg,
  hoursToday,
  relativeAge,
  statusBadge,
  VERIFICATION_ES,
} from "./format.js";
import { track, utmFromLocation } from "./tracking.js";

const slug = pathParam(1);
const { utm, campaignId } = utmFromLocation();
let card = null;

const el = {
  loading: document.getElementById("loading"),
  error: document.getElementById("error"),
  content: document.getElementById("content"),
  left: document.getElementById("left"),
  right: document.getElementById("right"),
  footerNotice: document.getElementById("footer-notice"),
};

function renderBranch(branch, index) {
  const channels = branch.channels || {};
  const contacts = (branch.contacts || [])
    .map(
      (contact) =>
        `<li><span class="muted">${escapeHtml(contact.channel)}</span> · ${escapeHtml(contact.value)}
         ${contact.verified_at ? `<span class="tiny muted">(verificado ${escapeHtml(relativeAge(contact.verified_at) || "")})</span>` : ""}</li>`
    )
    .join("");

  const hours = Object.entries(branch.opening_hours || {})
    .map(([day, slots]) => `<li><span class="muted">${escapeHtml(day)}</span> ${escapeHtml(slots.map((s) => s.join("–")).join(", "))}</li>`)
    .join("");

  return `<article class="card" id="sucursal-${index}">
    <div class="spread">
      <h3 style="margin:0">${escapeHtml(branch.name_es)}</h3>
      ${statusBadge(VERIFICATION_ES, branch.freshness?.verification_level)}
    </div>
    <p class="muted small" style="margin:6px 0 0">${escapeHtml(branch.address_text || "")}</p>
    <p class="small" style="margin:4px 0 0">
      ${escapeHtml(branch.barrio || "")}${branch.city ? `, ${escapeHtml(branch.city)}` : ""}
      · <strong>Hoy: ${escapeHtml(hoursToday(branch.opening_hours))}</strong>
    </p>

    <div class="btn-row" style="margin-top:12px">
      ${channels.whatsapp
        ? `<button type="button" class="btn whatsapp" data-action="whatsapp" data-branch="${escapeHtml(branch.id)}">WhatsApp</button>`
        : `<button type="button" class="btn" disabled title="Esta sucursal no tiene WhatsApp verificado">Sin WhatsApp verificado</button>`}
      ${channels.phone ? `<button type="button" class="btn" data-action="call" data-branch="${escapeHtml(branch.id)}">Llamar</button>` : ""}
      ${branch.map_url ? `<a class="btn" href="${escapeHtml(branch.map_url)}" target="_blank" rel="noopener" data-action="route" data-branch="${escapeHtml(branch.id)}">Cómo llegar</a>` : ""}
      ${channels.website ? `<a class="btn" href="${escapeHtml(channels.website)}" target="_blank" rel="noopener" data-action="site" data-branch="${escapeHtml(branch.id)}">Sitio web</a>` : ""}
    </div>

    <div class="grid two" style="margin-top:12px;gap:10px">
      <div>
        <h3 class="tiny muted" style="text-transform:uppercase;letter-spacing:.04em">Horarios</h3>
        <ul class="clean tiny">${hours || "<li>Sin horarios declarados</li>"}</ul>
      </div>
      <div>
        <h3 class="tiny muted" style="text-transform:uppercase;letter-spacing:.04em">Retiro y delivery</h3>
        <ul class="clean tiny">
          <li>${branch.pickup_available ? "Retiro en local disponible" : "Sin retiro en local"}</li>
          <li>${branch.delivery_available ? `Delivery: ${escapeHtml(branch.delivery_fee_display || "costo a confirmar")}` : "Sin delivery propio"}</li>
          ${branch.delivery_zone_es ? `<li>Zona: ${escapeHtml(branch.delivery_zone_es)}</li>` : ""}
        </ul>
      </div>
    </div>

    ${contacts ? `<details style="margin-top:10px"><summary class="small muted">Canales verificados</summary><ul class="clean small" style="margin-top:8px">${contacts}</ul></details>` : ""}

    <p class="tiny muted" style="margin:10px 0 0">
      Datos observados ${escapeHtml(relativeAge(branch.freshness?.observed_at) || "—")}
      · fuente: ${escapeHtml(branch.freshness?.source || "sin fuente registrada")}
      ${branch.freshness?.is_stale ? " · <strong>requiere actualización</strong>" : ""}
    </p>
  </article>`;
}

function renderOffer(offer) {
  const price = offer.price || {};
  const rows = [];
  // one formatter for money everywhere: PYG without decimals (§02)
  if (price.seller_discount) rows.push(["Descuento del comercio", `− ${fmtPyg(price.seller_discount)}`]);
  if (price.confirmed_benefits) rows.push(["Beneficios confirmados", `− ${fmtPyg(price.confirmed_benefits)}`]);
  if (price.delivery_fee) rows.push(["Delivery", `+ ${fmtPyg(price.delivery_fee)}`]);
  if (price.charges) rows.push(["Cargos", `+ ${fmtPyg(price.charges)}`]);

  const breakdown = rows.length
    ? `<ul class="breakdown">${rows.map(([label, value]) => `<li><span>${escapeHtml(label)}</span><span>${escapeHtml(String(value))}</span></li>`).join("")}</ul>`
    : "";

  const cashback = price.potential_cashback
    ? `<p class="tiny conditional" style="margin:6px 0 0">
         Cashback bancario potencial: ${escapeHtml(price.potential_cashback_display)} —
         <strong>condicional</strong>, depende de reglas del banco y de tu límite personal.
         No está incluido en el precio final garantizado.
       </p>`
    : "";

  const availability = {
    in_stock: badge("Disponible", "ok"),
    on_request: badge("A confirmar", "warn"),
    out_of_stock: badge("Sin stock", "danger"),
    seasonal: badge("Temporada", "neutral"),
  }[offer.availability_status] || badge(offer.availability_status);

  return `<article class="offer">
    <div class="offer-head">
      <div>
        <strong>${escapeHtml(offer.title_es)}</strong>
        ${offer.unit ? `<span class="muted small"> / ${escapeHtml(offer.unit)}</span>` : ""}
        <div style="margin-top:4px">${availability}</div>
      </div>
      <div class="right">
        <div class="price">
          ${price.seller_discount || price.confirmed_benefits ? `<s>${escapeHtml(offer.base_price_display)}</s>` : ""}
          ${escapeHtml(offer.price_display)}
        </div>
      </div>
    </div>
    ${offer.description_es ? `<p class="muted small" style="margin:6px 0 0">${escapeHtml(offer.description_es)}</p>` : ""}
    ${breakdown}
    ${cashback}
    <div class="btn-row" style="margin-top:10px">
      <button type="button" class="btn whatsapp small" data-action="whatsapp" data-offer="${escapeHtml(offer.id)}">Consultar por WhatsApp</button>
      <button type="button" class="btn small" data-action="request" data-offer="${escapeHtml(offer.id)}" data-title="${escapeHtml(offer.title_es)}">Enviar solicitud</button>
    </div>
    <p class="tiny muted" style="margin:8px 0 0">
      ${escapeHtml(offer.sku ? `SKU ${offer.sku} · ` : "")}
      observado ${escapeHtml(relativeAge(offer.freshness?.observed_at) || "—")}
      · válido hasta ${escapeHtml(offer.freshness?.valid_until ? fmtDateTime(offer.freshness.valid_until) : "sin límite declarado")}
      · fuente: ${escapeHtml(offer.freshness?.source || "sin fuente")}
      ${offer.freshness?.is_stale ? " · <strong>dato vencido, confirmar con el comercio</strong>" : ""}
    </p>
  </article>`;
}

function leadForm(primaryBranch) {
  return `<article class="card" id="solicitud">
    <h2>Enviar una solicitud</h2>
    <p class="muted small">
      El comercio recibe tu mensaje y te responde. PRTDS no cobra por enviar una solicitud y
      no guarda tu teléfono más allá de lo necesario para este contacto.
    </p>
    <form id="lead-form">
      <div class="field-row split">
        <div class="field">
          <label for="lead-name">Nombre</label>
          <input id="lead-name" name="name" type="text" maxlength="160" placeholder="Tu nombre" />
        </div>
        <div class="field">
          <label for="lead-phone">Teléfono / WhatsApp</label>
          <input id="lead-phone" name="phone" type="tel" maxlength="32" placeholder="+595 9XX XXX XXX" />
        </div>
      </div>
      <div class="field">
        <label for="lead-when">¿Cuándo lo necesitás?</label>
        <input id="lead-when" name="when" type="text" maxlength="160" placeholder="Ej.: viernes 18:00, o lo antes posible" />
      </div>
      <div class="field">
        <label for="lead-message">Mensaje</label>
        <textarea id="lead-message" name="message" maxlength="2000" placeholder="Contá qué necesitás: producto, cantidad, detalles"></textarea>
      </div>
      <div class="field">
        <label for="lead-branch">Sucursal</label>
        <select id="lead-branch" name="branch">
          ${(card.branches || [])
            .map((branch) => `<option value="${escapeHtml(branch.id)}"${branch.id === primaryBranch?.id ? " selected" : ""}>${escapeHtml(branch.name_es)} — ${escapeHtml(branch.barrio || branch.city)}</option>`)
            .join("")}
        </select>
      </div>
      <div class="field">
        <label class="checkbox" for="lead-consent">
          <input id="lead-consent" name="consent" type="checkbox" required />
          <span>
            Autorizo a PRTDS a compartir estos datos con <strong>${escapeHtml(card.display_name)}</strong>
            para que me contacte. Puedo revocar este consentimiento en cualquier momento.
          </span>
        </label>
      </div>
      <div id="lead-error"></div>
      <div class="btn-row">
        <button class="btn primary" type="submit" id="lead-submit">Enviar solicitud</button>
      </div>
      <p class="tiny muted" style="margin:10px 0 0">
        Una solicitud entregada no es una venta: el comercio debe confirmarla.
      </p>
    </form>
  </article>`;
}

function render() {
  const primary = card.branches?.[0];

  el.left.innerHTML = `
    <article class="card">
      <div class="spread">
        <div>
          <h1 style="margin:0">${escapeHtml(card.display_name)}</h1>
          ${card.brand ? `<p class="muted small" style="margin:4px 0 0">Marca: ${escapeHtml(card.brand.name)}</p>` : ""}
        </div>
        ${card.is_promoted ? `<span class="badge ad">${escapeHtml(card.promotion_label_es || "Publicidad")}</span>` : ""}
      </div>

      <div style="margin:10px 0">
        ${(card.categories || [])
          .map((category) => `<a class="badge neutral" href="/?categoria=${escapeHtml(category.slug)}">${escapeHtml(category.name_es)}</a>`)
          .join(" ")}
        ${statusBadge(VERIFICATION_ES, card.verification_level)}
      </div>

      ${card.short_description_es ? `<p>${escapeHtml(card.short_description_es)}</p>` : ""}
      ${card.description_es && card.description_es !== card.short_description_es ? `<p class="muted small">${escapeHtml(card.description_es)}</p>` : ""}

      <div class="btn-row" style="margin-top:12px">
        ${primary?.channels?.whatsapp ? `<button type="button" class="btn whatsapp" data-action="whatsapp" data-branch="${escapeHtml(primary.id)}">WhatsApp</button>` : ""}
        ${primary?.channels?.phone ? `<button type="button" class="btn" data-action="call" data-branch="${escapeHtml(primary.id)}">Llamar</button>` : ""}
        <a class="btn" href="#solicitud" data-action="request">Enviar solicitud</a>
      </div>

      <dl class="kv" style="margin-top:14px">
        <dt>Sucursales</dt><dd>${card.branches?.length || 0}</dd>
        <dt>Ofertas activas</dt><dd>${card.offers?.length || 0}</dd>
        <dt>Publicada</dt><dd>${escapeHtml(card.published_at ? fmtDateTime(card.published_at) : "—")}</dd>
        <dt>Última observación de datos</dt><dd>${escapeHtml(relativeAge(card.data_freshness?.last_observed_at) || "—")}</dd>
      </dl>

      ${card.data_freshness?.stale_offers ? `<div class="notice warn tiny" style="margin-top:10px">${card.data_freshness.stale_offers} oferta(s) con datos vencidos: confirmá precio y disponibilidad con el comercio.</div>` : ""}
      ${card.legal_entity ? `<p class="tiny muted" style="margin:10px 0 0">Persona jurídica: ${escapeHtml(card.legal_entity.name)}${card.legal_entity.ruc ? ` · RUC ${escapeHtml(card.legal_entity.ruc)}` : ""}. ${escapeHtml(card.legal_entity.note_es)}</p>` : ""}
    </article>

    ${(card.branches || []).map((branch, index) => renderBranch(branch, index)).join("")}

    <article class="card">
      <h2>Productos y servicios</h2>
      <p class="muted small">
        ${escapeHtml(card.data_freshness?.source_note_es || "")}
      </p>
      ${(card.offers || []).map(renderOffer).join("") || '<p class="muted">Esta ficha aún no tiene ofertas publicadas.</p>'}
    </article>
  `;

  el.right.innerHTML = leadForm(primary) + `
    <article class="card">
      <h2>Qué significa cada paso</h2>
      <ul class="clean small">
        <li><strong>WhatsApp / llamada:</strong> registramos el intento de contacto, no una venta.</li>
        <li><strong>Solicitud entregada:</strong> el comercio la recibe con tu consentimiento.</li>
        <li><strong>Confirmada:</strong> el comercio acepta o confirma el resultado; solo entonces puede existir una comisión contractual.</li>
      </ul>
      <p class="tiny muted" style="margin-bottom:0">
        PRTDS no lee tu conversación de WhatsApp y no guarda el contenido del chat.
      </p>
    </article>`;

  el.loading.classList.add("hidden");
  el.content.classList.remove("hidden");
  document.title = `${card.display_name} · PRTDS`;
  if (card.is_promoted) {
    el.footerNotice.textContent =
      "Esta ficha incluye posición promocionada contratada, etiquetada como publicidad. " +
      "Una posición pagada no equivale a la mejor oferta objetiva.";
  }
}

async function onAction(event) {
  const trigger = event.target.closest("[data-action]");
  if (!trigger) return;
  const action = trigger.dataset.action;
  const branchId = trigger.dataset.branch || card.branches?.[0]?.id || null;
  const offerId = trigger.dataset.offer || null;

  if (action === "route" || action === "site") {
    track(action === "route" ? "route_click" : "site_click", { companySlug: slug, branchId, source: "card" });
    return;
  }

  if (action === "request") {
    event.preventDefault();
    document.getElementById("solicitud")?.scrollIntoView({ behavior: "smooth", block: "start" });
    if (offerId) {
      const message = document.getElementById("lead-message");
      message.value = message.value || `Consulta sobre: ${trigger.dataset.title || "una oferta"}`;
    }
    return;
  }

  event.preventDefault();
  trigger.disabled = true;
  try {
    if (action === "whatsapp") {
      const link = await post("/api/whatsapp-link", {
        company_slug: slug,
        branch_id: branchId,
        offer_id: offerId,
        source: "card",
        campaign_id: campaignId,
        utm: utm || undefined,
      });
      window.open(link.url, "_blank", "noopener");
      flash(
        `WhatsApp abierto con mensaje preparado. Referencia: <strong>${escapeHtml(link.reference)}</strong>. Guardá ese código: sirve para confirmar el resultado con el comercio.`,
        "ok"
      );
    } else if (action === "call") {
      const link = await post("/api/call-link", { company_slug: slug, branch_id: branchId, source: "card" });
      window.location.href = link.url;
      flash(`Llamada iniciada. Referencia: <strong>${escapeHtml(link.reference)}</strong>.`, "ok");
    }
  } catch (error) {
    flash(error.message, "danger");
  } finally {
    trigger.disabled = false;
  }
}

function flash(html, tone = "warn", target = el.left) {
  const node = document.createElement("div");
  node.className = `notice ${tone}`;
  node.innerHTML = html;
  target.prepend(node);
  window.setTimeout(() => node.remove(), 12000);
}

async function submitLead(event) {
  event.preventDefault();
  const form = event.target;
  const errorBox = document.getElementById("lead-error");
  const submit = document.getElementById("lead-submit");
  errorBox.innerHTML = "";

  const consent = document.getElementById("lead-consent");
  if (!consent.checked) {
    errorBox.innerHTML = '<div class="notice danger">Necesitamos tu consentimiento para compartir el contacto con el comercio.</div>';
    return;
  }

  const payload = {
    company_slug: slug,
    branch_id: document.getElementById("lead-branch").value || null,
    intent: card.primary_intent === "purchase" ? "request" : card.primary_intent || "request",
    customer_name: document.getElementById("lead-name").value.trim() || null,
    customer_phone: document.getElementById("lead-phone").value.trim() || null,
    message: document.getElementById("lead-message").value.trim() || null,
    requested_at: document.getElementById("lead-when").value.trim() || null,
    channel: "web_form",
    source: "card",
    campaign_id: campaignId,
    utm: utm || undefined,
    consent: { purpose: "lead_transfer", granted: true, channel: "web_form" },
  };

  submit.disabled = true;
  submit.textContent = "Enviando…";
  try {
    const created = await post("/api/leads", payload);
    window.location.href = `/solicitud/${encodeURIComponent(created.ref_code)}`;
  } catch (error) {
    errorBox.innerHTML = `<div class="notice danger">${escapeHtml(error.message)}</div>`;
    submit.disabled = false;
    submit.textContent = "Enviar solicitud";
  }
}

async function boot() {
  if (!slug) {
    el.loading.classList.add("hidden");
    el.error.innerHTML = '<div class="notice danger">Ficha no especificada.</div>';
    return;
  }
  try {
    card = await get(`/api/companies/${encodeURIComponent(slug)}`);
    render();
    el.left.addEventListener("click", onAction);
    document.getElementById("lead-form").addEventListener("submit", submitLead);
    track("view", { companySlug: slug, source: "card" });
    if (tokens.partner) {
      el.right.innerHTML += `<div class="notice tiny">Sesión de socio activa en esta pestaña: <a href="/socio">ir al panel</a>.</div>`;
    }
  } catch (error) {
    el.loading.classList.add("hidden");
    el.error.innerHTML = `<div class="notice danger">${escapeHtml(error.message)}
      <div class="tiny" style="margin-top:6px">Una ficha puede no estar publicada aunque la empresa exista en el registro maestro.</div></div>`;
  }
}

boot();
