/* Presentation helpers: Spanish (Paraguay), guaraníes without decimals,
 * local timezone America/Asuncion (concept §02). */

const TZ = "America/Asuncion";

export function fmtDateTime(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("es-PY", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: TZ,
  }).format(date);
}

export function fmtDate(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("es-PY", { dateStyle: "medium", timeZone: TZ }).format(date);
}

/** PYG has no fractional units: 1250000 -> "G. 1.250.000". */
export function fmtPyg(amount) {
  if (amount === null || amount === undefined) return "—";
  const negative = amount < 0;
  const digits = Math.abs(Number(amount)).toLocaleString("es-PY", { maximumFractionDigits: 0 });
  return `${negative ? "-" : ""}G. ${digits.replaceAll(",", ".")}`;
}

export const LEAD_STATUS_ES = {
  submitted: { label: "Entregada", tone: "neutral", hint: "El comercio aún no respondió." },
  accepted: { label: "Aceptada", tone: "ok", hint: "El comercio confirmó la solicitud." },
  rejected: { label: "Rechazada", tone: "danger", hint: "El comercio no puede atenderla." },
  booked: { label: "Turno confirmado", tone: "ok", hint: "Hay día y hora confirmados." },
  visit_done: { label: "Servicio realizado", tone: "ok", hint: "El comercio marcó la visita como realizada." },
  sale_confirmed: { label: "Venta confirmada", tone: "ok", hint: "Resultado confirmado con evidencia." },
  cancelled: { label: "Cancelada", tone: "warn", hint: "Cancelada por el cliente o el comercio." },
  expired: { label: "Vencida", tone: "warn", hint: "Sin respuesta dentro del plazo acordado." },
};

export const SETTLEMENT_STATUS_ES = {
  pending: { label: "Pendiente de conciliación", tone: "warn" },
  approved: { label: "Aprobada", tone: "ok" },
  flagged_negative_cm: { label: "Margen no positivo", tone: "danger" },
  no_contract_basis: { label: "Sin contrato (ingreso 0)", tone: "neutral" },
  disputed: { label: "En disputa", tone: "danger" },
  void: { label: "Anulada", tone: "neutral" },
  paid: { label: "Pagada", tone: "ok" },
};

export const VERIFICATION_ES = {
  unverified: { label: "Sin verificar", tone: "warn" },
  source_only: { label: "Solo fuente registrada", tone: "neutral" },
  partner_confirmed: { label: "Confirmado por el comercio", tone: "ok" },
  field_verified: { label: "Verificado en campo", tone: "ok" },
};

export const PUBLICATION_ES = {
  draft: "Borrador",
  staging: "Staging",
  validated: "Validado",
  moderated: "Moderado",
  published: "Publicado",
  archived: "Archivado",
};

export function badge(text, tone = "neutral") {
  return `<span class="badge ${tone}">${escapeHtml(text)}</span>`;
}

export function statusBadge(map, key) {
  const entry = map[key] || { label: key, tone: "neutral" };
  return badge(entry.label, entry.tone);
}

export function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** Today's weekday key in local time ("mon", "tue", …) for opening hours. */
export function todayKey() {
  const parts = new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: TZ }).format(new Date());
  return parts.toLowerCase();
}

export function hoursToday(openingHours) {
  const key = todayKey();
  const slots = (openingHours || {})[key];
  if (!slots || !slots.length) return "Cerrado hoy";
  return slots.map(([open, close]) => `${open}–${close}`).join(", ");
}

export function relativeAge(iso) {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const hours = Math.round((Date.now() - then) / 3_600_000);
  if (hours < 1) return "hace minutos";
  if (hours < 48) return `hace ${hours} h`;
  const days = Math.round(hours / 24);
  return `hace ${days} días`;
}
