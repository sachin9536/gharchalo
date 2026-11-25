#!/usr/bin/env bash
# Releases of gharchalo-api, for the NudgeBee rollback demo (roadmap incident 2).
#
#   deploy/release.sh v1          # 1.4.0 Baseline (healthy)
#   deploy/release.sh v2          # 1.5.0 Express surge pricing (buggy: 500s on Bengaluru <-> Hyderabad)
#   deploy/release.sh status      # what is live, rollout history, a live error check
#   deploy/release.sh rollback    # human rollback: Helm back to the previous revision
#   deploy/release.sh reconcile   # after NudgeBee / `kubectl rollout undo`: make Helm match what is live
#
# A release is a Deployment revision, not a runtime toggle: rolling back restores the previous pods.
# Why `reconcile` exists: `kubectl rollout undo` changes the Deployment but not Helm's record, so the
# next `helm upgrade --reuse-values` (incident.sh, a re-deploy) would silently ship the buggy release
# again. Run `reconcile` after any rollback that did not go through Helm.
set -euo pipefail
cd "$(dirname "$0")/.."

NAMESPACE="${NAMESPACE:-gharchalo}"
RELEASE="${RELEASE:-gharchalo}"
CHART=deploy/helm/gharchalo
DEPLOY="deploy/${RELEASE}-api"

# Helm 4 applies changes server-side: after `kubectl rollout undo` (what NudgeBee does), kubectl owns
# the rolled-back fields and every Helm upgrade fails with a conflict. --force-conflicts lets Helm take
# them back. Helm 3 has no such flag (and no such conflict), so it is only added on Helm 4.
HELM_FORCE=()
if helm version --short 2>/dev/null | grep -q '^v4'; then HELM_FORCE=(--force-conflicts); fi

ctx="$(kubectl config current-context)"
case "$ctx" in
  kind-*|minikube|docker-desktop|orbstack|hackathon) ;;
  *) echo "Refusing to run: '$ctx' is not a local cluster."; exit 1 ;;
esac

ship() {  # version, notes, surge-pricing on/off
  helm upgrade "$RELEASE" "$CHART" -n "$NAMESPACE" --reuse-values ${HELM_FORCE[@]+"${HELM_FORCE[@]}"} \
    --set "api.release.version=$1" --set-string "api.release.notes=$2" \
    --set "api.expressSurgePricing.enabled=$3" >/dev/null
  kubectl -n "$NAMESPACE" rollout status "$DEPLOY" --timeout=180s
  echo "Live: $1 ($2)"
}

live_env() {  # value of an env var on the live Deployment
  kubectl -n "$NAMESPACE" get "$DEPLOY" -o jsonpath="{.spec.template.spec.containers[0].env[?(@.name==\"$1\")].value}"
}

check() {  # a few requests from inside the API pod: the faulty corridor and a healthy control route
  kubectl -n "$NAMESPACE" exec -i "$DEPLOY" -- python - <<'PY'
import urllib.error, urllib.request
def codes(path, n=5):
    out = []
    for _ in range(n):
        try:
            with urllib.request.urlopen(urllib.request.Request("http://localhost:8000" + path, headers={"X-Load-Test": "1"}), timeout=10) as r:
                out.append(r.status)
        except urllib.error.HTTPError as e:
            out.append(e.code)
    return out
print("  SBC -> HYB  :", codes("/search?origin=SBC&dest=HYB&date=2026-11-30"))
print("  HYB -> SBC  :", codes("/search?origin=HYB&dest=SBC&date=2026-11-30"))
print("  SBC -> NDLS :", codes("/search?origin=SBC&dest=NDLS&date=2026-11-30"), "(control route)")
PY
}

case "${1:-}" in
  v1) ship "1.4.0" "Baseline" false ;;
  v2) ship "1.5.0" "Express surge pricing" true ;;
  status)
    echo "== live release: $(live_env RELEASE_VERSION) (express surge pricing: $(live_env ENABLE_EXPRESS_SURGE_PRICING))"
    echo "== Helm thinks: $(helm get values "$RELEASE" -n "$NAMESPACE" -o json | python3 -c 'import json,sys; a=json.load(sys.stdin).get("api",{}); r=a.get("release",{}); print(r.get("version","1.4.0 (default)"), "(express surge pricing:", str(a.get("expressSurgePricing",{}).get("enabled",False)).lower() + ")")')"
    echo "== rollout history"
    kubectl -n "$NAMESPACE" rollout history "$DEPLOY" | tail -n +2
    echo "== live check"
    check
    ;;
  rollback)
    # Back to the previous RELEASE, not merely the previous Helm revision: re-shipping the same
    # version (or a kubectl rollback in between) leaves several revisions of the same release.
    current="$(live_env RELEASE_VERSION)"
    target=""
    for rev in $(helm history "$RELEASE" -n "$NAMESPACE" -o json | python3 -c 'import json,sys; print(" ".join(str(r["revision"]) for r in reversed(json.load(sys.stdin))))'); do
      version="$(helm get values "$RELEASE" -n "$NAMESPACE" --revision "$rev" -o json | python3 -c 'import json,sys; print((json.load(sys.stdin).get("api") or {}).get("release",{}).get("version","1.4.0"))')"
      if [[ "$version" != "$current" ]]; then target="$rev"; break; fi
    done
    if [[ -z "$target" ]]; then echo "No earlier release than $current in Helm's history."; exit 1; fi
    helm rollback "$RELEASE" "$target" -n "$NAMESPACE" ${HELM_FORCE[@]+"${HELM_FORCE[@]}"} >/dev/null
    kubectl -n "$NAMESPACE" rollout status "$DEPLOY" --timeout=180s
    echo "Rolled back from $current to Helm revision $target. Live: $(live_env RELEASE_VERSION)"
    ;;
  reconcile)
    version="$(live_env RELEASE_VERSION)"
    surge="$(live_env ENABLE_EXPRESS_SURGE_PRICING)"
    cause="$(kubectl -n "$NAMESPACE" get "$DEPLOY" -o jsonpath='{.metadata.annotations.kubernetes\.io/change-cause}')"
    notes="${cause#*: }"
    echo "Live Deployment: $version, express surge pricing $surge. Recording that in Helm..."
    helm upgrade "$RELEASE" "$CHART" -n "$NAMESPACE" --reuse-values ${HELM_FORCE[@]+"${HELM_FORCE[@]}"} \
      --set "api.release.version=${version:-1.4.0}" --set-string "api.release.notes=${notes:-Baseline}" \
      --set "api.expressSurgePricing.enabled=${surge:-false}" >/dev/null
    kubectl -n "$NAMESPACE" rollout status "$DEPLOY" --timeout=180s
    echo "Helm now matches the live release."
    ;;
  *) sed -n '2,15p' "$0"; exit 1 ;;
esac
