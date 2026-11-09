#!/usr/bin/env bash
# Live end-to-end smoke test against a RUNNING server (not TestClient).
#
# Walks the whole slice: search → card → WhatsApp attempt → lead (with consent)
# → partner CRM decision → confirmed sale → commission basis → replay check.
# Prints the economics so GMV vs PRTDS revenue is visible on every run.
#
# Usage:  ./scripts/funnel-smoke.sh [base_url] [company_slug]
set -euo pipefail

B="${1:-http://127.0.0.1:8000}"
SLUG="${2:-nails-mburucuya}"
TOKEN="${PARTNER_TOKEN:-prtds-socio-nails}"
SESSION="X-PRTDS-Session: smoke-$(date +%s)"
PY="${PY:-python3}"

j() { "$PY" -c "import sys,json;d=json.load(sys.stdin);print($1)"; }

echo "PRTDS smoke → $B ($SLUG)"

echo "1. health"
curl -fsS --max-time 10 "$B/api/health" | j "d['status'] + ' · ' + d['locale'] + ' · ' + d['currency']"

echo "2. search (search_result)"
curl -fsS --max-time 10 -H "$SESSION" "$B/api/search?q=manicura&limit=3" \
  | j "'total=' + str(d['total']) + ' organic=' + str(d['total_organic']) + ' sponsored=' + str(d['total_sponsored'])"

echo "3. card (card_open)"
curl -fsS --max-time 10 -H "$SESSION" "$B/api/companies/$SLUG" \
  | j "d['display_name'] + ' · ' + str(len(d['branches'])) + ' sucursales · ' + str(len(d['offers'])) + ' ofertas'"

echo "4. whatsapp link (attempt, not a sale)"
curl -fsS --max-time 10 -H "$SESSION" -H 'Content-Type: application/json' -X POST "$B/api/whatsapp-link" \
  -d "{\"company_slug\":\"$SLUG\",\"source\":\"card\",\"campaign_id\":\"smoke\"}" \
  | j "d['reference'] + ' → ' + d['url'][:60] + '…'"

echo "5. lead (consent required)"
REF=$(curl -fsS --max-time 10 -H "$SESSION" -H 'Content-Type: application/json' -X POST "$B/api/leads" -d "{
  \"company_slug\":\"$SLUG\",\"intent\":\"booking\",\"customer_name\":\"Ana Benítez\",
  \"customer_phone\":\"+59598155500$RANDOM\",\"message\":\"Consulta del smoke test\",
  \"source\":\"card\",\"campaign_id\":\"smoke\",
  \"consent\":{\"purpose\":\"lead_transfer\",\"granted\":true,\"channel\":\"web_form\"}}" | j "d['ref_code']")
echo "   ref_code = $REF"

echo "5b. lead without consent must be refused"
CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X POST "$B/api/leads" \
  -H 'Content-Type: application/json' \
  -d "{\"company_slug\":\"$SLUG\",\"consent\":{\"purpose\":\"lead_transfer\",\"granted\":false}}")
echo "   HTTP $CODE (esperado 403)"

echo "6. partner accepts (CRM)"
curl -fsS --max-time 10 -H "X-Partner-Token: $TOKEN" -H 'Content-Type: application/json' \
  -X POST "$B/api/partner/leads/$REF/decision" -d '{"status":"accepted","note":"smoke"}' \
  | j "'status=' + d['status']"

echo "7. confirm sale → commission basis"
curl -fsS --max-time 10 -H "X-Partner-Token: $TOKEN" -H 'Content-Type: application/json' \
  -X POST "$B/api/partner/leads/$REF/sale" -d '{"amount_pyg":180000,"proof_ref":"SMOKE-0001"}' \
  | j "'evento=' + d['event']['event_type'] + ' · GMV=' + d['settlement']['basis_amount_display'] + ' · comisión=' + d['settlement']['commission_display'] + ' · margen=' + d['settlement']['contribution_margin_display'] + ' · estado=' + d['settlement']['status']"

echo "8. replay must not create a second commission"
curl -fsS --max-time 10 -H "X-Partner-Token: $TOKEN" -H 'Content-Type: application/json' \
  -X POST "$B/api/partner/leads/$REF/sale" -d '{"amount_pyg":180000,"proof_ref":"SMOKE-0001"}' \
  | j "'misma liquidación=' + d['settlement']['id'][-8:] + ' · comisión=' + d['settlement']['commission_display']"

echo "9. public ingest of a commercial fact must be refused"
CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X POST "$B/api/events" \
  -H 'Content-Type: application/json' -d '{"event_type":"sale_confirmed","amount_pyg":180000}')
echo "   HTTP $CODE (esperado 422)"

echo "10. partner economics"
curl -fsS --max-time 10 -H "X-Partner-Token: $TOKEN" "$B/api/partner/dashboard" \
  | "$PY" -c "
import sys, json
e = json.load(sys.stdin)['economics']
print(
    'GMV comercio=' + e['gmv_display']
    + ' · ingreso PRTDS=' + e['prtds_revenue_display']
    + ' · margen=' + e['contribution_margin_display']
    + ' · ' + str(e['counters'])
)
"

echo "OK: путь пройден целиком."
