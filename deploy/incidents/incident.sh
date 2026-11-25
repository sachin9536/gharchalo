#!/usr/bin/env bash
# Planted, reversible incidents for the NudgeBee RCA demo (roadmap section 4).
#
#   deploy/incidents/incident.sh oom        # leaky release + 128Mi memory limit: OOMKilled under the Tatkal spike
#   deploy/incidents/incident.sh db-pool    # 2 database connections, no overflow: 503s under load
#   deploy/incidents/incident.sh fix        # restore memory and the connection pool
#   deploy/incidents/incident.sh status     # pods, restarts, last termination reason, recent events
#
# Then: deploy/storm/run.sh   (load), ask NudgeBee for the root cause, apply `fix`, run the storm again.
set -euo pipefail
cd "$(dirname "$0")/../.."

NAMESPACE="${NAMESPACE:-gharchalo}"
RELEASE="${RELEASE:-gharchalo}"
CHART=deploy/helm/gharchalo

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

upgrade() {
  # --reuse-values keeps everything deploy/k8s-up.sh set (Sarvam secret, CA bundle, ...).
  helm upgrade "$RELEASE" "$CHART" -n "$NAMESPACE" --reuse-values ${HELM_FORCE[@]+"${HELM_FORCE[@]}"} "$@" >/dev/null
  kubectl -n "$NAMESPACE" rollout status deploy/"$RELEASE"-api --timeout=180s
}

status() {
  echo "== pods"
  kubectl -n "$NAMESPACE" get pods -l app.kubernetes.io/component=api \
    -o custom-columns='POD:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount,LAST-TERMINATED:.status.containerStatuses[0].lastState.terminated.reason,LIMIT:.spec.containers[0].resources.limits.memory'
  echo "== api settings"
  kubectl -n "$NAMESPACE" get deploy "$RELEASE"-api -o jsonpath='{range .spec.template.spec.containers[0].env[*]}{.name}={.value}{"\n"}{end}' | grep -E '^(DB_POOL|FAULT_)' || true
  echo "== recent warning events"
  kubectl -n "$NAMESPACE" get events --field-selector type=Warning --sort-by=.lastTimestamp 2>/dev/null | tail -8 || true
}

case "${1:-}" in
  oom)
    # The app's memory is flat under load, so a lower limit alone never crashes it. The planted fault
    # (FAULT_UNBOUNDED_SEARCH_LOG, see api/config.py) keeps every search response, so memory climbs with
    # traffic. requests must not exceed limits, so both are lowered.
    upgrade --set api.resources.limits.memory="${MEMORY_LIMIT:-128Mi}" --set api.resources.requests.memory=64Mi \
            --set 'api.extraEnv[0].name=FAULT_UNBOUNDED_SEARCH_LOG' --set-string 'api.extraEnv[0].value=1'
    echo "Incident ON: leaky release, memory limit ${MEMORY_LIMIT:-128Mi}. Now run deploy/storm/run.sh"
    ;;
  db-pool)
    upgrade --set api.dbPool.size=2 --set api.dbPool.maxOverflow=0 --set api.dbPool.timeoutSeconds=3
    echo "Incident ON: 2 database connections, no overflow, 3 s wait. Now run deploy/storm/run.sh"
    ;;
  fix)
    upgrade --set api.resources.limits.memory=512Mi --set api.resources.requests.memory=256Mi \
            --set api.dbPool.size=10 --set api.dbPool.maxOverflow=10 --set api.dbPool.timeoutSeconds=10 \
            --set 'api.extraEnv=null'
    echo "Fixed: leak removed, memory 512Mi, connection pool 10 + 10 overflow."
    ;;
  status) status ;;
  *) sed -n '2,11p' "$0"; exit 1 ;;
esac
