#!/usr/bin/env bash
# Remove the release and its namespace (the seeded data goes with it).
set -euo pipefail
NAMESPACE="${NAMESPACE:-gharchalo}"
RELEASE="${RELEASE:-gharchalo}"
helm uninstall "$RELEASE" -n "$NAMESPACE" || true
kubectl delete namespace "$NAMESPACE" --ignore-not-found
