#!/usr/bin/env bash
# End-to-end smoke test for a running backend.
#
#   ADMIN_PASSWORD=... ./scripts/smoke.sh
#   BASE_URL=http://localhost:8000 ./scripts/smoke.sh
#
# Creates a temporary mock router and removes it afterwards. Requires curl, jq
# and a running API with at least one admin account.
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
API="${BASE_URL}/api/v1"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"

if [[ -z "${ADMIN_PASSWORD}" && -f .env ]]; then
  # shellcheck disable=SC1091
  ADMIN_PASSWORD="$(grep -E '^BOOTSTRAP_ADMIN_PASSWORD=' .env | cut -d= -f2- || true)"
fi
if [[ -z "${ADMIN_PASSWORD}" ]]; then
  echo "error: set ADMIN_PASSWORD or BOOTSTRAP_ADMIN_PASSWORD in .env" >&2
  exit 2
fi

for tool in curl jq; do
  command -v "$tool" >/dev/null || { echo "error: $tool is required" >&2; exit 2; }
done

WORKDIR="$(mktemp -d)"
JAR="${WORKDIR}/cookies.txt"
cleanup() {
  if [[ -n "${TOKEN:-}" && -n "${ROUTER_ID:-}" ]]; then
    # Remove references first so route maps can be deleted on the mock device.
    curl -fsS -X DELETE -H "Authorization: Bearer ${TOKEN}" "${API}/routers/${ROUTER_ID}/bgp" >/dev/null 2>&1 || true
    for ospf_version in v2 v3; do
      curl -fsS -X DELETE -H "Authorization: Bearer ${TOKEN}" \
        "${API}/routers/${ROUTER_ID}/ospf/${ospf_version}" >/dev/null 2>&1 || true
    done
    curl -fsS -X DELETE -H "Authorization: Bearer ${TOKEN}" \
      "${API}/routers/${ROUTER_ID}/static-routes/ipv4/10.99.0.0/24" >/dev/null 2>&1 || true
    curl -fsS -X DELETE -H "Authorization: Bearer ${TOKEN}" \
      "${API}/routers/${ROUTER_ID}/static-routes/ipv6/2001:db8:99::/64" >/dev/null 2>&1 || true
    curl -fsS -X DELETE -H "Authorization: Bearer ${TOKEN}" \
      "${API}/routers/${ROUTER_ID}/wireguard/wg9" >/dev/null 2>&1 || true
    for rm in SMOKE-IN SMOKE-OUT; do
      curl -fsS -X DELETE -H "Authorization: Bearer ${TOKEN}" \
        "${API}/routers/${ROUTER_ID}/route-maps/${rm}" >/dev/null 2>&1 || true
    done
    curl -fsS -X DELETE -H "Authorization: Bearer ${TOKEN}" \
      "${API}/routers/${ROUTER_ID}/prefix-lists/ipv4/SMOKE-PL" >/dev/null 2>&1 || true
    curl -fsS -X DELETE -H "Authorization: Bearer ${TOKEN}" \
      "${API}/routers/${ROUTER_ID}/prefix-lists/ipv6/SMOKE-PL6" >/dev/null 2>&1 || true
    curl -fsS -X DELETE -H "Authorization: Bearer ${TOKEN}" "${API}/routers/${ROUTER_ID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${TOKEN:-}" ]]; then
    curl -fsS -X POST -H "Authorization: Bearer ${TOKEN}" -H "X-Requested-With: vyos-mgmt" \
      -b "${JAR}" -c "${JAR}" "${API}/auth/logout" >/dev/null 2>&1 || true
  fi
  rm -rf "${WORKDIR}"
}
trap cleanup EXIT

step() { printf '\n\033[1;36m== %s\033[0m\n' "$1"; }
ok() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

request() {
  # request METHOD PATH [BODY] -> response body; non-2xx raises with body
  local method="$1" path="$2" body="${3:-}" response status
  local args=(-sS -X "${method}" -b "${JAR}" -c "${JAR}" -H "Accept: application/json")
  [[ -n "${TOKEN:-}" ]] && args+=(-H "Authorization: Bearer ${TOKEN}")
  [[ -n "${body}" ]] && args+=(-H "Content-Type: application/json" -d "${body}")
  response="$(curl "${args[@]}" -w $'\n%{http_code}' "${API}${path}")"
  status="$(tail -n1 <<<"${response}")"
  body="$(sed '$d' <<<"${response}")"
  if [[ "${status}" -lt 200 || "${status}" -ge 300 ]]; then
    printf 'HTTP %s for %s %s\n%s\n' "${status}" "${method}" "${path}" "${body}" >&2
    return 1
  fi
  printf '%s' "${body}"
}

expect_error() {
  # expect_error METHOD PATH STATUS CODE [BODY]
  local method="$1" path="$2" expected_status="$3" expected_code="$4" body="${5:-}"
  local response status payload
  local args=(-sS -X "${method}" -b "${JAR}" -c "${JAR}" -H "Accept: application/json")
  [[ -n "${TOKEN:-}" ]] && args+=(-H "Authorization: Bearer ${TOKEN}")
  [[ -n "${body}" ]] && args+=(-H "Content-Type: application/json" -d "${body}")
  response="$(curl "${args[@]}" -w $'\n%{http_code}' "${API}${path}")"
  status="$(tail -n1 <<<"${response}")"
  payload="$(sed '$d' <<<"${response}")"
  [[ "${status}" == "${expected_status}" ]] || {
    printf 'expected HTTP %s, got %s for %s %s\n%s\n' "${expected_status}" "${status}" "${method}" "${path}" "${payload}" >&2
    return 1
  }
  [[ "$(jq -r '.error.code // empty' <<<"${payload}")" == "${expected_code}" ]] || {
    printf 'expected error %s, got %s\n%s\n' "${expected_code}" "${payload}" >&2
    return 1
  }
}

step "Health"
HEALTH="$(curl -fsS "${API}/health")"
jq -e '.status == "ok"' >/dev/null <<<"${HEALTH}" || fail "health is not ok: ${HEALTH}"
ok "API and database healthy ($(jq -r '.version' <<<"${HEALTH}"))"

step "Login"
LOGIN="$(curl -fsS -c "${JAR}" -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u "${ADMIN_USER}" --arg p "${ADMIN_PASSWORD}" '{username:$u,password:$p,remember_me:true}')" \
  "${API}/auth/login")"
TOKEN="$(jq -r '.access_token' <<<"${LOGIN}")"
[[ -n "${TOKEN}" && "${TOKEN}" != "null" ]] || fail "no access token"
ok "access token issued for $(jq -r '.user.username' <<<"${LOGIN}") ($(jq -r '.user.role' <<<"${LOGIN}"))"

step "Refresh rotation"
OLD_REFRESH_HASH="$(sha256sum "${JAR}" | cut -d' ' -f1)"
REFRESHED="$(curl -fsS -X POST -b "${JAR}" -c "${JAR}" -H "X-Requested-With: vyos-mgmt" "${API}/auth/refresh")"
NEW_REFRESH_HASH="$(sha256sum "${JAR}" | cut -d' ' -f1)"
[[ "${NEW_REFRESH_HASH}" != "${OLD_REFRESH_HASH}" ]] || fail "refresh cookie was not rotated"
TOKEN="$(jq -r '.access_token' <<<"${REFRESHED}")"
ok "refresh token rotated and access token renewed"

step "Router inventory (mock driver)"
ROUTER_NAME="smoke-$(date +%s)"
ROUTER="$(request POST "/routers" "$(jq -nc --arg n "${ROUTER_NAME}" '{name:$n,host:"192.0.2.10",port:443,protocol:"https",driver:"mock",verify_tls:true,description:"smoke test"}')")"
ROUTER_ID="$(jq -r '.id' <<<"${ROUTER}")"
[[ "${ROUTER_ID}" != "null" ]] || fail "router was not created"
ok "created mock router ${ROUTER_NAME}"

step "System info"
SYSTEM="$(request GET "/routers/${ROUTER_ID}/system")"
jq -e '.reachable == true' >/dev/null <<<"${SYSTEM}" || fail "mock router unreachable"
ok "connected to $(jq -r '.hostname' <<<"${SYSTEM}") ($(jq -r '.version' <<<"${SYSTEM}"))"

step "BGP configuration"
CONFIG="$(request GET "/routers/${ROUTER_ID}/bgp")"
jq -e '.configured == true' >/dev/null <<<"${CONFIG}" || fail "expected seeded BGP config"
ok "read BGP config: $(jq '.neighbors | length' <<<"${CONFIG}") neighbors, $(jq '.networks | length' <<<"${CONFIG}") networks"

request PUT "/routers/${ROUTER_ID}/bgp/global" \
  '{"system_as":64512,"router_id":"10.255.0.1","log_neighbor_changes":true}' >/dev/null
ok "updated global BGP settings"

step "Prefix-list policy"
PREFIX_LISTS="$(request GET "/routers/${ROUTER_ID}/prefix-lists")"
jq -e '.total >= 3' >/dev/null <<<"${PREFIX_LISTS}" \
  || fail "expected seeded prefix lists: ${PREFIX_LISTS}"
jq -e '.items[] | select(.family == "ipv4" and .name == "TRANSIT-IN" and .in_use == true)' \
  >/dev/null <<<"${PREFIX_LISTS}" || fail "TRANSIT-IN should be in use"
ok "read $(jq -r '.total' <<<"${PREFIX_LISTS}") seeded prefix lists"

request POST "/routers/${ROUTER_ID}/prefix-lists" \
  '{"name":"SMOKE-PL","family":"ipv4","description":"Smoke IPv4 policy"}' >/dev/null
request POST "/routers/${ROUTER_ID}/prefix-lists" \
  '{"name":"SMOKE-PL6","family":"ipv6","description":"Smoke IPv6 policy"}' >/dev/null
request POST "/routers/${ROUTER_ID}/prefix-lists/ipv4/SMOKE-PL/rules" \
  '{"number":10,"action":"permit","prefix":"203.0.113.0/24","ge":24,"le":32,"description":"Customer /24"}' >/dev/null
request POST "/routers/${ROUTER_ID}/prefix-lists/ipv4/SMOKE-PL/rules" \
  '{"number":20,"action":"deny","prefix":"10.0.0.0/8","le":32}' >/dev/null
request POST "/routers/${ROUTER_ID}/prefix-lists/ipv6/SMOKE-PL6/rules" \
  '{"number":10,"action":"permit","prefix":"2001:db8:100::/48","ge":48,"le":64}' >/dev/null
UPDATED_PL="$(request PUT "/routers/${ROUTER_ID}/prefix-lists/ipv4/SMOKE-PL/rules/10" \
  '{"action":"permit","prefix":"203.0.113.0/24","ge":25,"le":32,"description":"Customer /25+"}')"
jq -e '.rules[] | select(.number == 10) | .ge == 25 and .description == "Customer /25+"' \
  >/dev/null <<<"${UPDATED_PL}" || fail "prefix-list rule update was not reflected"
expect_error POST "/routers/${ROUTER_ID}/prefix-lists/ipv4/SMOKE-PL/rules" 409 prefix_list_rule_duplicate \
  '{"number":30,"action":"permit","prefix":"203.0.113.0/24","ge":25,"le":32}'
expect_error POST "/routers/${ROUTER_ID}/prefix-lists/ipv4/SMOKE-PL/rules" 422 validation_error \
  '{"number":40,"action":"permit","prefix":"203.0.113.0/24","ge":23}'
ok "created/updated prefix-list rules; duplicate and bad ge/le rejected"


step "OSPF policy"
OSPF2="$(request GET "/routers/${ROUTER_ID}/ospf/v2")"
jq -e '.configured == true and (.areas | length) >= 2 and (.interfaces | length) >= 2 and (.redistributions | length) >= 1' \
  >/dev/null <<<"${OSPF2}" || fail "expected seeded OSPFv2 configuration: ${OSPF2}"
jq -e '.global.router_id == "10.255.0.1" and .global.log_adjacency_changes == "detail"' \
  >/dev/null <<<"${OSPF2}" || fail "seeded OSPFv2 global settings missing"
ok "read seeded OSPFv2 (areas, interfaces, redistribution)"

UPDATED_OSPF_GLOBAL="$(request PUT "/routers/${ROUTER_ID}/ospf/v2/global" '{
  "router_id":"10.255.0.9",
  "log_adjacency_changes":"normal",
  "auto_cost_reference_bandwidth":2000,
  "default_information_originate":false,
  "default_information_always":false,
  "distance_global":120
}')"
jq -e '.global.router_id == "10.255.0.9" and .global.log_adjacency_changes == "normal" and .global.auto_cost_reference_bandwidth == 2000 and .global.default_information_originate == false and .global.distance_global == 120' \
  >/dev/null <<<"${UPDATED_OSPF_GLOBAL}" || fail "OSPF global update was not reflected"

request POST "/routers/${ROUTER_ID}/ospf/v2/areas" \
  '{"area_id":"2","area_type":"nssa","no_summary":true}' >/dev/null
expect_error POST "/routers/${ROUTER_ID}/ospf/v2/areas" 409 ospf_area_exists \
  '{"area_id":"0.0.0.2"}'
UPDATED_AREA="$(request PUT "/routers/${ROUTER_ID}/ospf/v2/areas/0.0.0.2" \
  '{"area_type":"stub","no_summary":false}')"
jq -e '.areas[] | select(.area_id == "0.0.0.2") | .area_type == "stub" and .no_summary == false' \
  >/dev/null <<<"${UPDATED_AREA}" || fail "OSPF area update was not reflected"

request POST "/routers/${ROUTER_ID}/ospf/v2/interfaces" '{
  "name":"eth9",
  "area_id":"0.0.0.2",
  "network_type":"point-to-point",
  "cost":20,
  "hello_interval":10,
  "dead_interval":40,
  "priority":1,
  "passive":false,
  "bfd":true,
  "mtu_ignore":false
}' >/dev/null
expect_error POST "/routers/${ROUTER_ID}/ospf/v2/interfaces" 409 ospf_interface_exists '{
  "name":"eth9","area_id":"0.0.0.2"
}'
expect_error POST "/routers/${ROUTER_ID}/ospf/v2/interfaces" 422 ospf_area_not_found '{
  "name":"eth8","area_id":"0.0.0.99"
}'
UPDATED_IF="$(request PUT "/routers/${ROUTER_ID}/ospf/v2/interfaces/eth9" '{
  "area_id":"0.0.0.2",
  "network_type":"broadcast",
  "cost":30,
  "hello_interval":10,
  "dead_interval":40,
  "priority":2,
  "passive":true,
  "bfd":false,
  "mtu_ignore":true
}')"
jq -e '.interfaces[] | select(.name == "eth9") | .area_id == "0.0.0.2" and .network_type == "broadcast" and .cost == 30 and .priority == 2 and .passive == true and .bfd == false and .mtu_ignore == true' \
  >/dev/null <<<"${UPDATED_IF}" || fail "OSPF interface update was not reflected"
expect_error DELETE "/routers/${ROUTER_ID}/ospf/v2/areas/0.0.0.2" 409 ospf_area_in_use
ok "created/updated OSPF area+interface; conflicts, missing area and in-use deletion enforced"

request POST "/routers/${ROUTER_ID}/route-maps" \
  '{"name":"SMOKE-OSPF-RM","description":"Smoke OSPF redistribution"}' >/dev/null
request POST "/routers/${ROUTER_ID}/ospf/v2/redistribute" \
  '{"source":"static","metric":50,"metric_type":2,"route_map":"SMOKE-OSPF-RM"}' >/dev/null
expect_error DELETE "/routers/${ROUTER_ID}/route-maps/SMOKE-OSPF-RM" 409 route_map_in_use
UPDATED_REDIST="$(request PUT "/routers/${ROUTER_ID}/ospf/v2/redistribute/static" \
  '{"metric":60,"metric_type":1,"route_map":null}')"
jq -e '.redistributions[] | select(.source == "static") | .metric == 60 and .metric_type == 1 and .route_map == null' \
  >/dev/null <<<"${UPDATED_REDIST}" || fail "OSPF redistribution update was not reflected"
request DELETE "/routers/${ROUTER_ID}/ospf/v2/redistribute/static" >/dev/null
request DELETE "/routers/${ROUTER_ID}/route-maps/SMOKE-OSPF-RM" >/dev/null
expect_error POST "/routers/${ROUTER_ID}/ospf/v2/redistribute" 422 route_map_not_found \
  '{"source":"kernel","route_map":"NO-SUCH-MAP"}'
ok "OSPF redistribution CRUD and route-map in_use detection enforced"

request DELETE "/routers/${ROUTER_ID}/ospf/v2/interfaces/eth9" >/dev/null
request DELETE "/routers/${ROUTER_ID}/ospf/v2/areas/0.0.0.2" >/dev/null

OSPF3="$(request GET "/routers/${ROUTER_ID}/ospf/v3")"
jq -e '.configured == true and (.areas | length) >= 1 and (.interfaces | length) >= 2' \
  >/dev/null <<<"${OSPF3}" || fail "expected seeded OSPFv3 configuration: ${OSPF3}"
request POST "/routers/${ROUTER_ID}/ospf/v3/areas" \
  '{"area_id":"3","area_type":"stub","no_summary":true}' >/dev/null
request POST "/routers/${ROUTER_ID}/ospf/v3/interfaces" '{
  "name":"eth9","area_id":"0.0.0.3","network_type":"broadcast","cost":10
}' >/dev/null
jq -e '.interfaces[] | select(.name == "eth9") | .area_id == "0.0.0.3" and .network_type == "broadcast"' \
  >/dev/null <<<"$(request GET "/routers/${ROUTER_ID}/ospf/v3")" || fail "OSPFv3 interface create failed"
expect_error POST "/routers/${ROUTER_ID}/ospf/v3/interfaces" 422 validation_error '{
  "name":"eth8","area_id":"0.0.0.3","network_type":"non-broadcast"
}'
request DELETE "/routers/${ROUTER_ID}/ospf/v3/interfaces/eth9" >/dev/null
request DELETE "/routers/${ROUTER_ID}/ospf/v3/areas/0.0.0.3" >/dev/null
ok "OSPFv3 area/interface CRUD and version-specific network types enforced"

STATUS2="$(request GET "/routers/${ROUTER_ID}/ospf/v2/status")"
jq -e '.configured == true and .total_neighbors >= 2 and .full_neighbors >= 2' \
  >/dev/null <<<"${STATUS2}" || fail "unexpected OSPFv2 status: ${STATUS2}"
STATUS3="$(request GET "/routers/${ROUTER_ID}/ospf/v3/status")"
jq -e '.configured == true and .total_neighbors >= 2 and .full_neighbors >= 1' \
  >/dev/null <<<"${STATUS3}" || fail "unexpected OSPFv3 status: ${STATUS3}"
ok "OSPFv2/v3 neighbor status parsed"



step "Static routes"
STATIC_ROUTES="$(request GET "/routers/${ROUTER_ID}/static-routes")"
jq -e '.total >= 9 and ([.items[] | select(.family == "ipv4")] | length) >= 5 and ([.items[] | select(.family == "ipv6")] | length) >= 4' \
  >/dev/null <<<"${STATIC_ROUTES}" || fail "expected seeded static routes: ${STATIC_ROUTES}"
ok "read $(jq -r '.total' <<<"${STATIC_ROUTES}") seeded static routes"

STATIC_CREATED="$(request POST "/routers/${ROUTER_ID}/static-routes" '{
  "family":"ipv4",
  "prefix":"10.99.0.0/24",
  "description":"Smoke static route",
  "blackhole":false,
  "reject":false,
  "distance":null,
  "tag":null,
  "next_hops":[
    {"address":"192.0.2.99","interface":"eth9","distance":10,"enabled":true},
    {"address":null,"interface":"eth10","distance":null,"enabled":false}
  ]
}')"
jq -e '.prefix == "10.99.0.0/24" and (.next_hops | length) == 2 and .next_hops[1].interface == "eth10" and .next_hops[1].enabled == false' \
  >/dev/null <<<"${STATIC_CREATED}" || fail "static route create failed: ${STATIC_CREATED}"
expect_error POST "/routers/${ROUTER_ID}/static-routes" 409 static_route_exists '{
  "family":"ipv4","prefix":"10.99.0.0/24","next_hops":[{"address":"192.0.2.1"}]
}'
STATIC_DETAIL="$(request GET "/routers/${ROUTER_ID}/static-routes/ipv4/10.99.0.0/24")"
jq -e '.next_hops[0].address == "192.0.2.99" and .next_hops[0].distance == 10' \
  >/dev/null <<<"${STATIC_DETAIL}" || fail "static route detail mismatch: ${STATIC_DETAIL}"

STATIC_BLACKHOLE="$(request PUT "/routers/${ROUTER_ID}/static-routes/ipv4/10.99.0.0/24" '{
  "description":"Smoke blackhole",
  "blackhole":true,
  "reject":false,
  "distance":200,
  "tag":100,
  "next_hops":[]
}')"
jq -e '.blackhole == true and .reject == false and .distance == 200 and .tag == 100 and (.next_hops | length) == 0' \
  >/dev/null <<<"${STATIC_BLACKHOLE}" || fail "static route blackhole transition failed: ${STATIC_BLACKHOLE}"

request POST "/routers/${ROUTER_ID}/static-routes" '{
  "family":"ipv6","prefix":"2001:db8:99::/64","description":"Smoke IPv6",
  "next_hops":[{"address":"2001:db8:ffff::99","distance":5,"enabled":true}]
}' >/dev/null
expect_error POST "/routers/${ROUTER_ID}/static-routes" 422 validation_error '{
  "family":"ipv4","prefix":"10.99.1.1/24","next_hops":[{"address":"192.0.2.1"}]
}'
expect_error POST "/routers/${ROUTER_ID}/static-routes" 422 validation_error '{
  "family":"ipv4","prefix":"10.99.2.0/24","blackhole":true,"next_hops":[{"address":"192.0.2.1"}]
}'
expect_error POST "/routers/${ROUTER_ID}/static-routes" 422 validation_error '{
  "family":"ipv4","prefix":"10.99.3.0/24","next_hops":[]
}'
expect_error POST "/routers/${ROUTER_ID}/static-routes" 422 validation_error '{
  "family":"ipv4","prefix":"10.99.4.0/24","next_hops":[{"address":"192.0.2.1"},{"address":"192.0.2.1"}]
}'
ok "created/updated static routes; duplicate, host-bits, type and next-hop validation enforced"

request PUT "/routers/${ROUTER_ID}/static-routes/ipv4/10.99.0.0/24" '{
  "description":"Smoke reject",
  "blackhole":false,
  "reject":true,
  "distance":250,
  "tag":200,
  "next_hops":[]
}' >/dev/null
jq -e '.reject == true and .blackhole == false and .distance == 250 and .tag == 200' \
  >/dev/null <<<"$(request GET "/routers/${ROUTER_ID}/static-routes/ipv4/10.99.0.0/24")" \
  || fail "static route reject transition failed"
request DELETE "/routers/${ROUTER_ID}/static-routes/ipv4/10.99.0.0/24" >/dev/null
request DELETE "/routers/${ROUTER_ID}/static-routes/ipv6/2001:db8:99::/64" >/dev/null
ok "static route type transition and deletion"

step "WireGuard VPN"
WG_LIST="$(request GET "/routers/${ROUTER_ID}/wireguard")"
jq -e '.total >= 1 and (.items | map(.name) | index("wg0") != null)' \
  >/dev/null <<<"${WG_LIST}" || fail "expected seeded WireGuard interface: ${WG_LIST}"
WG0="$(request GET "/routers/${ROUTER_ID}/wireguard/wg0")"
jq -e '.public_key != null and .peer_count >= 2 and (.peers | length) >= 2 and (has("private_key") | not)' \
  >/dev/null <<<"${WG0}" || fail "seeded WireGuard interface incomplete: ${WG0}"
jq -e 'all(.peers[]; (has("preshared_key") | not))' >/dev/null <<<"${WG0}" \
  || fail "preshared key leaked in interface detail"
ok "read seeded WireGuard interface and peers (no secret key material)"

WG_KEYS="$(request POST "/routers/${ROUTER_ID}/wireguard/keypair" '{}')"
WG_PRIV="$(jq -r '.private_key' <<<"${WG_KEYS}")"
WG_PUB="$(jq -r '.public_key' <<<"${WG_KEYS}")"
jq -e '(.private_key | length) == 44 and (.public_key | length) == 44' \
  >/dev/null <<<"${WG_KEYS}" || fail "keypair endpoint returned malformed keys"
WG_PSK="$(request POST "/routers/${ROUTER_ID}/wireguard/preshared-key" '{}' | jq -r '.preshared_key')"
[ "${#WG_PSK}" -eq 44 ] || fail "preshared-key endpoint returned a malformed key"

WG_CREATED="$(request POST "/routers/${ROUTER_ID}/wireguard" "$(jq -nc \
  --arg key "${WG_PRIV}" \
  '{name:"wg9",description:"Smoke WireGuard tunnel",addresses:["10.99.0.1/24"],port:51999,mtu:1420,enabled:true,private_key:$key}')")"
jq -e --arg pub "${WG_PUB}" '.name == "wg9" and .public_key == $pub and .peer_count == 0 and (has("private_key") | not)' \
  >/dev/null <<<"${WG_CREATED}" || fail "WireGuard interface create failed: ${WG_CREATED}"
expect_error POST "/routers/${ROUTER_ID}/wireguard" 409 wireguard_interface_exists "$(jq -nc \
  --arg key "${WG_PRIV}" \
  '{name:"wg9",addresses:["10.99.0.1/24"],private_key:$key}')"
WG_UPDATED="$(request PUT "/routers/${ROUTER_ID}/wireguard/wg9" '{
  "description":"Smoke WireGuard tunnel (edited)",
  "addresses":["10.99.0.1/24","2001:db8:99::1/64"],
  "port":51998,
  "mtu":1400,
  "enabled":false
}')"
jq -e '.description == "Smoke WireGuard tunnel (edited)" and (.addresses | length) == 2 and .port == 51998 and .mtu == 1400 and .enabled == false' \
  >/dev/null <<<"${WG_UPDATED}" || fail "WireGuard interface update was not reflected"
ok "created/updated WireGuard interface; duplicate refused"

PEER_KEYS="$(request POST "/routers/${ROUTER_ID}/wireguard/keypair" '{}')"
PEER_PUB="$(jq -r '.public_key' <<<"${PEER_KEYS}")"
WG_PEER="$(request POST "/routers/${ROUTER_ID}/wireguard/wg9/peers" "$(jq -nc \
  --arg pub "${PEER_PUB}" --arg psk "${WG_PSK}" \
  '{name:"smoke-peer",description:"Smoke branch",public_key:$pub,allowed_ips:["192.168.99.0/24"],endpoint:"198.51.100.99",endpoint_port:51820,persistent_keepalive:25,preshared_key:$psk,enabled:true}')")"
jq -e '.peers[] | select(.name == "smoke-peer") | .has_preshared_key == true and .endpoint == "198.51.100.99" and .endpoint_port == 51820 and (has("preshared_key") | not)' \
  >/dev/null <<<"${WG_PEER}" || fail "WireGuard peer create failed: ${WG_PEER}"
expect_error POST "/routers/${ROUTER_ID}/wireguard/wg9/peers" 409 wireguard_peer_exists "$(jq -nc \
  --arg pub "${PEER_PUB}" \
  '{name:"smoke-peer",public_key:$pub,allowed_ips:["192.168.100.0/24"]}')"
CONFLICT_PUB="$(request POST "/routers/${ROUTER_ID}/wireguard/keypair" '{}' | jq -r '.public_key')"
expect_error POST "/routers/${ROUTER_ID}/wireguard/wg9/peers" 422 wireguard_allowed_ips_conflict "$(jq -nc \
  --arg pub "${CONFLICT_PUB}" \
  '{name:"smoke-ip-conflict",public_key:$pub,allowed_ips:["192.168.99.0/24"]}')"
expect_error POST "/routers/${ROUTER_ID}/wireguard/wg9/peers" 422 wireguard_public_key_conflict "$(jq -nc \
  --arg pub "${PEER_PUB}" \
  '{name:"smoke-key-conflict",public_key:$pub,allowed_ips:["192.168.100.0/24"]}')"

WG_PEER_UPDATED="$(request PUT "/routers/${ROUTER_ID}/wireguard/wg9/peers/smoke-peer" "$(jq -nc \
  --arg pub "${PEER_PUB}" \
  '{description:"Smoke branch (edited)",public_key:$pub,allowed_ips:["192.168.99.0/24"],endpoint:"branch.example.net",endpoint_port:51820,persistent_keepalive:30,enabled:true}')")"
jq -e '.peers[] | select(.name == "smoke-peer") | .endpoint == "branch.example.net" and .persistent_keepalive == 30 and .has_preshared_key == true' \
  >/dev/null <<<"${WG_PEER_UPDATED}" || fail "WireGuard peer update did not preserve the omitted preshared key"
WG_PEER_PSK_REMOVED="$(request PUT "/routers/${ROUTER_ID}/wireguard/wg9/peers/smoke-peer" "$(jq -nc \
  --arg pub "${PEER_PUB}" \
  '{description:"Smoke branch (edited)",public_key:$pub,allowed_ips:["192.168.99.0/24"],endpoint:"branch.example.net",endpoint_port:51820,persistent_keepalive:30,preshared_key:null,enabled:true}')")"
jq -e '.peers[] | select(.name == "smoke-peer") | .has_preshared_key == false' \
  >/dev/null <<<"${WG_PEER_PSK_REMOVED}" || fail "WireGuard preshared key removal was not reflected"
ok "created/updated peer; duplicate alias/IP/public-key conflicts and preshared-key tri-state enforced"

WG_STATUS="$(request GET "/routers/${ROUTER_ID}/wireguard/wg0/status")"
jq -e '.configured == true and .listening_port == 51820 and (.peers | length) >= 2' \
  >/dev/null <<<"${WG_STATUS}" || fail "WireGuard status parse failed: ${WG_STATUS}"
ok "parsed WireGuard live peer status"

BAD_WG_KEY="not-a-valid-wireguard-secret"
BAD_WG_RESPONSE="$(curl -sS -X PUT -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg key "${BAD_WG_KEY}" '{private_key:$key}')" \
  "${API}/routers/${ROUTER_ID}/wireguard/wg9/private-key")"
jq -e '.error.code == "validation_error"' >/dev/null <<<"${BAD_WG_RESPONSE}" \
  || fail "expected a validation error for an invalid private key: ${BAD_WG_RESPONSE}"
if grep -q "${BAD_WG_KEY}" <<<"${BAD_WG_RESPONSE}"; then
  fail "private key was echoed back in the validation error"
fi

ROTATE_KEYS="$(request POST "/routers/${ROUTER_ID}/wireguard/keypair" '{}')"
ROTATE_PRIV="$(jq -r '.private_key' <<<"${ROTATE_KEYS}")"
ROTATE_PUB="$(jq -r '.public_key' <<<"${ROTATE_KEYS}")"
WG_ROTATED="$(request PUT "/routers/${ROUTER_ID}/wireguard/wg9/private-key" "$(jq -nc --arg key "${ROTATE_PRIV}" '{private_key:$key}')")"
jq -e --arg pub "${ROTATE_PUB}" '.public_key == $pub and (has("private_key") | not)' \
  >/dev/null <<<"${WG_ROTATED}" || fail "WireGuard private key rotation failed"

request DELETE "/routers/${ROUTER_ID}/wireguard/wg9/peers/smoke-peer" >/dev/null
request DELETE "/routers/${ROUTER_ID}/wireguard/wg9" >/dev/null
ok "rotated/deleted WireGuard keys and interface; invalid private key redacted"

step "Route-map policy"
ROUTE_MAPS="$(request GET "/routers/${ROUTER_ID}/route-maps")"
jq -e '.total >= 2' >/dev/null <<<"${ROUTE_MAPS}" || fail "expected seeded route maps: ${ROUTE_MAPS}"
ok "read $(jq -r '.total' <<<"${ROUTE_MAPS}") seeded route maps"

request POST "/routers/${ROUTER_ID}/route-maps" \
  '{"name":"SMOKE-IN","description":"Smoke inbound policy"}' >/dev/null
request POST "/routers/${ROUTER_ID}/route-maps" \
  '{"name":"SMOKE-OUT","description":"Smoke outbound policy"}' >/dev/null
ok "created temporary route maps"

request POST "/routers/${ROUTER_ID}/route-maps/SMOKE-IN/rules" "$(jq -nc '{
  number:10,
  action:"permit",
  description:"Allow smoke prefix",
  match:{ipv4_prefix_list:"SMOKE-PL", origin:"igp"},
  set:{local_preference:150, metric:"+10", community_action:"add", community_values:["64512:999"]},
  on_match:"next"
}')" >/dev/null
request POST "/routers/${ROUTER_ID}/route-maps/SMOKE-IN/rules" "$(jq -nc '{
  number:20,
  action:"deny",
  description:"Deny the rest"
}')" >/dev/null
UPDATED_RULE="$(request PUT "/routers/${ROUTER_ID}/route-maps/SMOKE-IN/rules/10" "$(jq -nc '{
  action:"permit",
  description:"Allow smoke prefix (edited)",
  match:{ipv4_prefix_list:"SMOKE-PL", origin:"igp"},
  set:{local_preference:175, metric:"+10", as_path_prepend:[64512], community_action:"replace", community_values:["64512:999"]},
  on_match:"goto",
  goto_rule:20,
  call:null,
  continue_rule:null
}')")"
jq -e '.rules[] | select(.number == 10) | .set.local_preference == 175 and .on_match == "goto" and .goto_rule == 20' \
  >/dev/null <<<"${UPDATED_RULE}" || fail "rule update was not reflected"
request POST "/routers/${ROUTER_ID}/route-maps/SMOKE-OUT/rules" "$(jq -nc '{
  number:10,
  action:"permit",
  description:"Prepend our AS",
  set:{as_path_prepend:[64512], metric_type:"type-1"},
  on_match:"next"
}')" >/dev/null
ok "created and updated route-map rules"

expect_error POST "/routers/${ROUTER_ID}/route-maps/SMOKE-IN/rules" 422 prefix_list_not_found \
  '{"number":99,"action":"permit","match":{"ipv4_prefix_list":"MISSING-PL"}}'
expect_error DELETE "/routers/${ROUTER_ID}/prefix-lists/ipv4/SMOKE-PL" 409 prefix_list_in_use
ok "prefix-list reference existence and in-use deletion enforced"

NEIGHBOR="$(request POST "/routers/${ROUTER_ID}/bgp/neighbors" "$(jq -nc '{
  address:"203.0.113.9",
  remote_as:65099,
  description:"smoke peer",
  ebgp_multihop:2,
  timers:{keepalive:30,holdtime:90},
  address_families:{"ipv4-unicast":{
    next_hop_self:true,
    soft_reconfiguration_inbound:true,
    route_map_import:"SMOKE-IN",
    route_map_export:"SMOKE-OUT"
  }}
}')")"
jq -e '.neighbors | map(.address) | index("203.0.113.9") != null' >/dev/null <<<"${NEIGHBOR}" \
  || fail "neighbor was not created"
jq -e '.neighbors[] | select(.address == "203.0.113.9") | .address_families["ipv4-unicast"].route_map_import == "SMOKE-IN"' \
  >/dev/null <<<"${NEIGHBOR}" || fail "route-map import binding missing"
jq -e '.neighbors[] | select(.address == "203.0.113.9") | .address_families["ipv4-unicast"].route_map_export == "SMOKE-OUT"' \
  >/dev/null <<<"${NEIGHBOR}" || fail "route-map export binding missing"
ok "created neighbor 203.0.113.9 with import/export route maps"

expect_error DELETE "/routers/${ROUTER_ID}/route-maps/SMOKE-IN" 409 route_map_in_use
ok "in-use route map deletion refused with used_by details"

request PATCH "/routers/${ROUTER_ID}/bgp/neighbors/203.0.113.9" \
  '{"description":"smoke peer (edited)","shutdown":true}' >/dev/null

request PATCH "/routers/${ROUTER_ID}/bgp/neighbors/203.0.113.9" \
  '{"address_families":{"ipv4-unicast":{"next_hop_self":true,"soft_reconfiguration_inbound":true,"route_map_import":null,"route_map_export":null}}}' >/dev/null
DETACHED="$(request GET "/routers/${ROUTER_ID}/bgp")"
jq -e '.neighbors[] | select(.address == "203.0.113.9") | .address_families["ipv4-unicast"].route_map_import == null' \
  >/dev/null <<<"${DETACHED}" || fail "route-map import was not cleared"
request DELETE "/routers/${ROUTER_ID}/route-maps/SMOKE-IN" >/dev/null
request DELETE "/routers/${ROUTER_ID}/route-maps/SMOKE-OUT" >/dev/null
ok "patched neighbor, detached policy and removed temporary route maps"

request DELETE "/routers/${ROUTER_ID}/prefix-lists/ipv4/SMOKE-PL" >/dev/null
request DELETE "/routers/${ROUTER_ID}/prefix-lists/ipv6/SMOKE-PL6" >/dev/null
ok "removed temporary prefix lists"

request POST "/routers/${ROUTER_ID}/bgp/networks" \
  '{"af":"ipv4-unicast","prefix":"198.51.100.0/24"}' >/dev/null
request POST "/routers/${ROUTER_ID}/bgp/peer-groups" \
  '{"name":"smoke-group","remote_as":65099,"description":"smoke group"}' >/dev/null
ok "added network and peer group"

step "BGP status"
STATUS="$(request GET "/routers/${ROUTER_ID}/bgp/status")"
jq -e '.configured == true and .total_peers > 0' >/dev/null <<<"${STATUS}" \
  || fail "unexpected status: ${STATUS}"
ok "status: $(jq -r '.established_peers' <<<"${STATUS}")/$(jq -r '.total_peers' <<<"${STATUS}") peers established"

step "Audit trail"
AUDIT="$(request GET "/audit?limit=100")"
jq -e '.items | map(.action) | index("bgp.neighbor.create") != null' >/dev/null <<<"${AUDIT}" \
  || fail "audit entry missing"
jq -e '.items | map(.action) | index("route_map.rule.create") != null' >/dev/null <<<"${AUDIT}" \
  || fail "route-map audit entry missing"
jq -e '.items | map(.action) | index("prefix_list.rule.create") != null' >/dev/null <<<"${AUDIT}" \
  || fail "prefix-list audit entry missing"
jq -e '.items | map(.action) | index("ospf.interface.create") != null' >/dev/null <<<"${AUDIT}" \
  || fail "OSPF audit entry missing"
jq -e '.items | map(.action) | index("wireguard.interface.create") != null' >/dev/null <<<"${AUDIT}" \
  || fail "WireGuard audit entry missing"
jq -e '.items | map(.action) | index("static_route.create") != null' >/dev/null <<<"${AUDIT}" \
  || fail "static-route audit entry missing"
jq -e --arg secret "${WG_PRIV}" 'all(.items[]; (((.details // {}) | tostring) | contains($secret)) | not)'   >/dev/null <<<"${AUDIT}" || fail "WireGuard private key leaked into the audit trail"
jq -e --arg secret "${WG_PSK}" 'all(.items[]; (((.details // {}) | tostring) | contains($secret)) | not)'   >/dev/null <<<"${AUDIT}" || fail "WireGuard preshared key leaked into the audit trail"
ok "audit contains BGP, route-map, prefix-list, OSPF, static-route and WireGuard mutations without key material"

if [[ "${CHECK_STATIC:-1}" == "1" ]]; then
  step "Static frontend"
  for path in / /login/ /bgp/ /bgp/neighbors/ /route-maps/ /prefix-lists/ /ospf/ /static-routes/ /vpn/ /routers/; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' -H 'Accept: text/html' "${BASE_URL}${path}")"
    [[ "${code}" == "200" ]] || fail "static ${path} returned ${code}"
  done
  ok "static export serves deep links"
fi

step "Cleanup"
request DELETE "/routers/${ROUTER_ID}" >/dev/null
ROUTER_ID=""
ok "temporary router removed"

printf '\n\033[1;32mSmoke test passed.\033[0m\n'
