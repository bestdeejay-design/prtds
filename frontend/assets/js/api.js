/* API client.
 *
 * Only relative URLs are used, so the same code runs behind the sandbox preview
 * proxy, behind a Cloudflare Worker or behind Render — the browser never talks
 * to localhost or to another origin (concept §13.3, sandbox preview rules).
 */

const SESSION_KEY = "prtds.session_ref";
const ACTOR_KEY = "prtds.actor_ref";
const PARTNER_TOKEN_KEY = "prtds.partner_token";
const ADMIN_TOKEN_KEY = "prtds.admin_token";

function randomRef(prefix) {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return prefix + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Pseudonymous per-visit reference. Never derived from personal data. */
export function sessionRef() {
  let value = sessionStorage.getItem(SESSION_KEY);
  if (!value) {
    value = randomRef("s_");
    sessionStorage.setItem(SESSION_KEY, value);
  }
  return value;
}

export function actorRef() {
  return sessionStorage.getItem(ACTOR_KEY);
}

export function setActorRef(value) {
  if (value) sessionStorage.setItem(ACTOR_KEY, value);
  else sessionStorage.removeItem(ACTOR_KEY);
}

export const tokens = {
  get partner() {
    return sessionStorage.getItem(PARTNER_TOKEN_KEY) || "";
  },
  set partner(value) {
    value ? sessionStorage.setItem(PARTNER_TOKEN_KEY, value) : sessionStorage.removeItem(PARTNER_TOKEN_KEY);
  },
  get admin() {
    return sessionStorage.getItem(ADMIN_TOKEN_KEY) || "";
  },
  set admin(value) {
    value ? sessionStorage.setItem(ADMIN_TOKEN_KEY, value) : sessionStorage.removeItem(ADMIN_TOKEN_KEY);
  },
};

export class ApiError extends Error {
  constructor(status, detail, payload) {
    super(typeof detail === "string" ? detail : "Error de red");
    this.status = status;
    this.detail = detail;
    this.payload = payload;
  }
}

async function parse(response) {
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { detail: text.slice(0, 300) };
  }
  if (!response.ok) {
    const detail =
      (payload && (payload.detail || payload.message)) || `HTTP ${response.status}`;
    throw new ApiError(response.status, detail, payload);
  }
  return payload;
}

export async function api(path, { method = "GET", body, auth, headers = {} } = {}) {
  const finalHeaders = {
    "X-PRTDS-Session": sessionRef(),
    ...headers,
  };
  if (actorRef()) finalHeaders["X-PRTDS-Actor"] = actorRef();
  if (auth === "partner" && tokens.partner) finalHeaders["X-Partner-Token"] = tokens.partner;
  if (auth === "admin" && tokens.admin) finalHeaders["X-Admin-Token"] = tokens.admin;
  if (body !== undefined) finalHeaders["Content-Type"] = "application/json";

  const response = await fetch(path, {
    method,
    headers: finalHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return parse(response);
}

export const get = (path, options) => api(path, { ...options, method: "GET" });
export const post = (path, body, options) => api(path, { ...options, method: "POST", body });
export const patch = (path, body, options) => api(path, { ...options, method: "PATCH", body });

/** Reads the slug from /empresa/{slug}. */
export function pathParam(index = 1) {
  const parts = window.location.pathname.split("/").filter(Boolean);
  return decodeURIComponent(parts[index] || "");
}

export function queryParam(name) {
  return new URLSearchParams(window.location.search).get(name);
}
