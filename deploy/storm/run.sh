#!/usr/bin/env bash
# Run TatkalStorm inside the cluster as a Job and stream its output.
# Extra arguments go to api/scripts/tatkal_storm.py, e.g.:
#   deploy/storm/run.sh --peak-rps 80 --sustain-s 180
set -euo pipefail
cd "$(dirname "$0")/../.."

NAMESPACE="${NAMESPACE:-gharchalo}"
API_URL="${API_URL:-http://gharchalo-api:8000}"

ctx="$(kubectl config current-context)"
case "$ctx" in
  kind-*|minikube|docker-desktop|orbstack|hackathon) ;;
  *) echo "Refusing to run: '$ctx' is not a local cluster."; exit 1 ;;
esac

args=""
for a in "$@"; do args="$args, \"$a\""; done

kubectl -n "$NAMESPACE" delete job tatkal-storm --ignore-not-found --wait=true >/dev/null
kubectl apply -f - <<YAML
apiVersion: batch/v1
kind: Job
metadata:
  name: tatkal-storm
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: tatkal-storm
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 3600
  template:
    metadata:
      labels:
        app.kubernetes.io/name: tatkal-storm
    spec:
      restartPolicy: Never
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
      containers:
        - name: storm
          image: gharchalo-api:local
          imagePullPolicy: IfNotPresent
          command: ["python", "scripts/tatkal_storm.py", "--base", "$API_URL"$args]
          resources:
            requests: {cpu: 100m, memory: 64Mi}
            limits: {memory: 256Mi}
YAML
echo "Waiting for the storm pod..."
kubectl -n "$NAMESPACE" wait --for=condition=Ready pod -l app.kubernetes.io/name=tatkal-storm --timeout=120s >/dev/null 2>&1 || true
kubectl -n "$NAMESPACE" logs -f job/tatkal-storm
