/* Funnel instrumentation.
 *
 * The client only reports *attempts and impressions*. The server decides what an
 * event proves, de-duplicates it and refuses commercial facts through this
 * channel (concept §07). Nothing here may be read as a sale.
 */

import { post, sessionRef } from "./api.js";

function bucketKey(type, slug, extra = "") {
  const now = new Date();
  const bucket = `${now.getFullYear()}${now.getMonth()}${now.getDate()}${Math.floor(now.getHours() / 1)}`;
  return `c_${sessionRef()}_${type}_${slug}_${extra}_${bucket}`;
}

/** Fire-and-forget: instrumentation must never block the user path. */
export function track(type, { companySlug, branchId, offerId, source, campaignId, amountPyg } = {}) {
  const payload = {
    event_type: type,
    company_slug: companySlug || null,
    branch_id: branchId || null,
    offer_id: offerId || null,
    source: source || null,
    campaign_id: campaignId || null,
    amount_pyg: amountPyg ?? null,
    idempotency_key: bucketKey(type, companySlug || "", offerId || branchId || ""),
  };
  return post("/api/events", payload).catch((error) => {
    console.warn("evento no registrado:", type, error.message);
    return null;
  });
}

/** UTM / QR parameters carried through the session so attribution has a source. */
export function utmFromLocation() {
  const params = new URLSearchParams(window.location.search);
  const utm = {};
  ["source", "medium", "campaign", "term", "content"].forEach((key) => {
    const value = params.get(`utm_${key}`);
    if (value) utm[key] = value;
  });
  const campaign = params.get("campaign") || params.get("ref");
  return { utm: Object.keys(utm).length ? utm : null, campaignId: campaign || null };
}
