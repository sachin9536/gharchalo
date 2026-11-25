#!/usr/bin/env bash
# Behind a corporate VPN/proxy that re-signs HTTPS, containers fail to reach Sarvam with
#   "CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain"
# (the voice button then answers 502). Your Mac trusts the proxy's root certificate; containers don't.
# This script finds that root certificate and makes Docker Compose (and deploy/k8s-up.sh) trust it.
#
#   deploy/trust-corporate-ca.sh [host]      # default host: api.sarvam.ai
#   docker compose up -d --build
set -euo pipefail
cd "$(dirname "$0")/.."

host="${1:-api.sarvam.ai}"
command -v openssl >/dev/null || { echo "openssl is required"; exit 1; }
mkdir -p certs
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Every certificate the network presents for this host, in order (leaf first, root last).
openssl s_client -showcerts -servername "$host" -connect "$host:443" </dev/null 2>/dev/null \
  | awk -v dir="$tmp" '/BEGIN CERTIFICATE/{n++; f=sprintf("%s/cert-%02d.pem", dir, n); inside=1} inside{print > f} /END CERTIFICATE/{inside=0; close(f)}' || true  # s_client exits non-zero on some builds even when it worked
last="$(ls "$tmp"/cert-*.pem 2>/dev/null | tail -1 || true)"
[[ -n "$last" ]] || { echo "Could not read a certificate from $host:443. Are you online?"; exit 1; }

subject="$(openssl x509 -in "$last" -noout -subject | sed 's/^subject= *//')"
issuer="$(openssl x509 -in "$last" -noout -issuer | sed 's/^issuer= *//')"
echo "Last certificate in the chain: $subject"
if [[ "$subject" != "$issuer" ]]; then
  echo "That certificate is not self-signed (a root), so the network does not send its root."
  echo "Ask IT for the root CA as a .pem file, save it as certs/corp-ca.pem, then re-run docker compose."
  exit 1
fi

cp "$last" certs/corp-ca.pem
echo "Saved certs/corp-ca.pem (git-ignored)."

# docker compose reads ./.env for ${...} substitution in docker-compose.yml.
touch .env
if ! grep -q '^CONTAINER_CA_BUNDLE=' .env; then
  echo 'CONTAINER_CA_BUNDLE=/certs/corp-ca.pem' >> .env
  echo "Added CONTAINER_CA_BUNDLE to ./.env"
fi
echo
echo "Now restart:  docker compose up -d --build"
echo "Kubernetes:   deploy/k8s-up.sh   (it picks up certs/corp-ca.pem automatically)"
