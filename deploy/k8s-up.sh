#!/usr/bin/env bash
# Build the images, load them into a LOCAL cluster (kind / minikube / Docker Desktop)
# and install or upgrade the Helm chart. Extra args go to helm, e.g.:
#   deploy/k8s-up.sh --set api.resources.limits.memory=128Mi
set -euo pipefail
cd "$(dirname "$0")/.."

NAMESPACE="${NAMESPACE:-gharchalo}"
RELEASE="${RELEASE:-gharchalo}"
KIND_CLUSTER="${KIND_CLUSTER:-gharchalo}"

# Helm 4 applies changes server-side: after `kubectl rollout undo` (what NudgeBee does), kubectl owns
# the rolled-back fields and every Helm upgrade fails with a conflict. --force-conflicts lets Helm take
# them back. Helm 3 has no such flag (and no such conflict), so it is only added on Helm 4.
HELM_FORCE=()
if helm version --short 2>/dev/null | grep -q '^v4'; then HELM_FORCE=(--force-conflicts); fi

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing tool: $1"; exit 1; }; }
need docker; need kubectl; need helm

ctx="$(kubectl config current-context 2>/dev/null || true)"
if [[ -z "$ctx" ]]; then
  if command -v kind >/dev/null 2>&1; then
    kind create cluster --name "$KIND_CLUSTER"
    ctx="kind-$KIND_CLUSTER"
  else
    echo "No Kubernetes context. Install kind (brew install kind) or start minikube (minikube start)."
    exit 1
  fi
fi
echo "==> Kubernetes context: $ctx"

case "$ctx" in
  kind-*|minikube|docker-desktop|orbstack) ;;
  *)
    echo "Refusing to deploy: '$ctx' is not a local cluster this script knows."
    echo "Switch context (kubectl config use-context ...) or push images to a registry and use helm directly."
    exit 1
    ;;
esac

echo "==> Building images"
docker compose build api web

echo "==> Loading images into the cluster"
case "$ctx" in
  kind-*) kind load docker-image gharchalo-api:local gharchalo-web:local --name "${ctx#kind-}" ;;
  minikube) minikube image load gharchalo-api:local && minikube image load gharchalo-web:local ;;
  *) echo "    (shares the Docker image store, nothing to load)" ;;
esac

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

extra=()
key="$(grep -E '^SARVAM_API_KEY=' api/.env 2>/dev/null | head -1 | cut -d= -f2- || true)"
if [[ -n "$key" ]]; then
  kubectl -n "$NAMESPACE" create secret generic gharchalo-sarvam \
    --from-literal=SARVAM_API_KEY="$key" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  extra+=(--set api.sarvam.existingSecret=gharchalo-sarvam)
  echo "==> Sarvam key found in api/.env: voice enabled"
else
  echo "==> No SARVAM_API_KEY in api/.env: voice disabled (typed search works)"
fi

if [[ -f certs/corp-ca.pem ]]; then
  extra+=(--set-file api.caBundle=certs/corp-ca.pem)
  echo "==> certs/corp-ca.pem found: the API will trust your network's root CA"
fi

echo "==> Installing chart"
helm upgrade --install "$RELEASE" deploy/helm/gharchalo -n "$NAMESPACE" --wait --timeout 5m ${HELM_FORCE[@]+"${HELM_FORCE[@]}"} \
  ${extra[@]+"${extra[@]}"} "$@"

# The image tag stays "local", so restart to pick up freshly built images.
kubectl -n "$NAMESPACE" rollout restart deployment -l "app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component in (api,web)" >/dev/null
kubectl -n "$NAMESPACE" rollout status deployment -l "app.kubernetes.io/instance=$RELEASE" --timeout 3m

# Mirrors gharchalo.fullname in the chart's _helpers.tpl.
if [[ "$RELEASE" == *gharchalo* ]]; then fullname="$RELEASE"; else fullname="$RELEASE-gharchalo"; fi
echo
echo "Done. Open the app with:"
echo "  kubectl -n $NAMESPACE port-forward svc/$fullname-web 8080:80   ->  http://localhost:8080"
