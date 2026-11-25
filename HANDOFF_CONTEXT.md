# GharChalo — Handoff Context (for AI / Teammates)

> **Update (Sachin, 25 Nov):** sections B–D below are committed (`8016488`) and were then hardened: the buggy release now
> fails for real (`api/surge_pricing.py`, genuine traceback, no "rollback" hint in the log), releases carry a version and
> change-cause, and `deploy/release.sh` switches releases and **reconciles Helm after a kubectl/NudgeBee rollback** (otherwise the
> next `helm upgrade --reuse-values` ships the bug again). Prefer `deploy/release.sh v2` over `kubectl set env` for the demo.
> Current state of everything: `CONTEXT.md` §9.1 and `PROJECT_INVENTORY.md`.


> **Last updated:** 25 Nov 2026  
> **Repo root:** `c:\Users\HP\Desktop\BIEC\gharchalo`  
> **Current branch:** `main` (PR `#1 feature/flagsmith` merged at `7dc425c`, plus uncommitted local changes for the load generator, buggy rollback feature, and alerting manifests)  
> **Source of truth:** `GharChalo_Hackathon_Roadmap.pdf` and `CONTEXT.md`

---

## 1. What Has Been Built & Changed

### A. Flagsmith Integration (Merged in `7dc425c`, plus minor logging/test updates)
* **Backend (`api/`):**
  * `api/flags.py` — Single wrapper around the Flagsmith Python SDK using **local evaluation** (`enable_local_evaluation=True`, polling every `FLAGSMITH_REFRESH_SECONDS`, default `10s`) so load tests make **zero per-request network calls** to Flagsmith. Includes safe defaults (matching prior hardcoded behavior), value clamping, `DEMO_NOW` support for the 48-hour urgency window, `FLAGSMITH_API_URL` for self-hosting, and `FLAGSMITH_OFFLINE_FILE` for no-WiFi stage fallback.
  * `api/cache.py` — In-process TTL cache (`TTLCache`) for `/search` at `tatkal_level == 3` (Redis is out of scope per roadmap).
  * `api/metrics.py` — Prometheus metrics exported on `GET /metrics`:
    * `gharchalo_http_requests_total{method,path,status}`
    * `gharchalo_http_request_duration_seconds`
    * `gharchalo_request_duration_by_urgency_seconds{endpoint,urgent}` & `gharchalo_request_errors_by_urgency_total`
    * `gharchalo_tatkal_level` (gauge)
    * `gharchalo_search_served_total{served_from="live|cache"}`
    * `gharchalo_alternatives_shown_total{cohort_km}` & `gharchalo_alternatives_selected_total{cohort_km}`
    * `gharchalo_matches_offered_total{strategy}`, `gharchalo_matches_accepted_total{strategy}`, `gharchalo_match_paused_total`
  * `api/models.py` — Added `SearchEvent` and `AlternativeSelection` tables for Experiment B logging (auto-created on startup via `lifespan`).
  * `api/main.py`, `api/search.py`, `api/matching.py`, `api/config.py`, `api/requirements.txt`, `api/.env.example`:
    * Reads `X-User-Id` header on all requests as the Flagsmith identity.
    * **Experiment A (`tatkal_level` 0–3 + `urgent_travellers` segment):**
      * `0`: normal service (urgent users traveling within 48h stay at level 0 via Flagsmith segment override).
      * `1`: UI poll interval widens (`tatkal_config.poll_s_l1 = 120s`); on-demand `include_connections` ignored.
      * `2`: multi-leg planner skipped (`connections_paused: true`).
      * `3`: `/search` served from 30s TTL cache (`served_from: "cache"`), `/match` returns HTTP `200` with `paused: true, match_id: null` (no DB writes, doesn't inflate 5xx).
    * **Experiment B (`max_station_distance_km` multivariate 5 / 15 / 30 km):**
      * Server assigns cohort per user; `POST /search/{search_id}/select` records selection + `extra_km`.
    * **Optional matching A/B:** `matching_strategy` (`exact` / `time_window`) + `matching_config` JSON.
    * **P1 flags:** `interaction_mode` (`voice` | `text_only` — blocks `/voice` and `/journey/parse` with HTTP `409` while typed `/search` keeps working), `route_fault_sbc_hyb` (boolean 500 on `SBC ↔ HYB`), `sarvam_fault_mode` (`none` | `429` | `timeout` | `error` — simulates Sarvam outage without consuming real quota).
    * **New endpoints:** `GET /config`, `GET /metrics`, `POST /search/{search_id}/select`, `GET /experiments/summary`. `/healthz` now reports `flagsmith` status and `express_surge_pricing`.
* **Frontend (`web/src/`):**
  * `user.ts` — Supports `?as=<id>` URL query param for side-by-side cohort demos (`?as=demo-5km`, `?as=demo-15km`, `?as=demo-30km`).
  * `api.ts` — Attaches `X-User-Id` on every request; adds `fetchConfig`, `selectAlternative`, and updated response types.
  * `App.tsx`, `Results.tsx`, `CabMatches.tsx`, `Connections.tsx`, `App.css` — Live `/config` polling, Tatkal demand banners, `cached` badge, `X km cohort` badge + **Choose this** button on nearby alternatives, paused matching/connections states, and `text_only` fallback UI (disables Speak tab and hides transcript re-parse so Sarvam isn't called).
* **Tests & Docs:**
  * `api/tests/test_flags.py` — 6 pytest tests covering `/healthz`, `DEMO_NOW` urgency, Experiment B cohorts/selection/summary, Experiment A levels 2 & 3 + urgent override, `/config` + `/metrics`, and P1 fault flags. **All 6 verified passing inside `gharchalo-api:local`.**
  * `FLAGSMITH_SETUP.md` — Dashboard setup & live demo guide.

---

### B. Continuous k6 Load Generator (Uncommitted — ready to commit)
* **Files:**
  * `deploy/helm/gharchalo/templates/loadgen.yaml` + `loadgen:` block in `deploy/helm/gharchalo/values.yaml`
  * `deploy/loadgen.yaml` (standalone manifest for `namespace: gharchalo`)
* **Behavior:**
  * Runs `grafana/k6:0.54.0` continuously (5-minute looping windows) inside the `gharchalo` namespace targeting `http://gharchalo-api:8000`.
  * **Always sends `X-Load-Test: 1`** on every request (bypasses real Sarvam API and excludes loadgen from Experiment B `SearchEvent` rows).
  * **Traffic mix:** 70% `GET /search` (`SBC→HYB`, `HYB→SBC`, `SBC→NDLS`, `NDLS→HYB`, plus 25% heavy multi-leg `SBC→JP&include_connections=true`), 20% `POST /match` (Postgres writes), 10% `POST /voice` (stubbed).
  * **Urgency split:** 20% `2026-11-27` (urgent) / 80% `2026-11-30` (non-urgent) with stable `X-User-Id: loadgen-vu-<VU>`.

---

### C. Intentional Buggy Feature for NudgeBee Approval-Gated Rollback (Uncommitted)
* **Files:** `api/config.py`, `api/main.py`, `deploy/helm/gharchalo/values.yaml`, `deploy/helm/gharchalo/templates/api.yaml`
* **Mechanism:**
  * Env var `ENABLE_EXPRESS_SURGE_PRICING` (Helm value `api.expressSurgePricing.enabled`, default `false`).
  * When `true` on `gharchalo-api`: `GET /search` for **`SBC ↔ HYB` (both directions)** logs `express_surge_pricing v2 failed on <origin> -> <dest>: ZeroDivisionError: surge denominator is 0 (deployment regression; rollback gharchalo-api to recover)` and returns **HTTP 500**. All other routes (`SBC → NDLS`, `NDLS → HYB`, `SBC → JP`), `/match`, and `/voice` remain **200 OK**.
  * Rolling back the Deployment (`kubectl -n gharchalo rollout undo deployment/gharchalo-api`) restores the previous healthy Revision (`ENABLE_EXPRESS_SURGE_PRICING=false`) and errors drop to 0%.

---

### D. Alerting & NudgeBee Wiring (Uncommitted)
* **Files:**
  * `deploy/nudgebee-alerts.yaml` — `PrometheusRule` (`GharChaloHigh5xxErrorRate`, fires after `15s` when `sum(rate(gharchalo_http_requests_total{status=~"5.."}[1m])) > 0.05`) + `AlertmanagerConfig` (`nudgebee-webhook`, forwards alerts to `http://nudgebee-agent-runner.nudgebee-agent.svc/api/alerts`).
  * `deploy/alertmanager-nudgebee-values.yaml` — Optional Helm values for Alertmanager.
  * `deploy/nudgebee-install.sh` — Downloaded official NudgeBee agent installer script.

---

## 2. Current Live Cluster State (Windows 11 + Docker Desktop + Minikube)

* **Installed CLIs:**
  * `docker` (`C:\Program Files\Docker\Docker\resources\bin\docker.exe`, Engine 29.9.3)
  * `kubectl` (`C:\Program Files\Docker\Docker\resources\bin\kubectl.exe` & WinGet Links)
  * `minikube` (`C:\Users\HP\bin\minikube.exe`, v1.39.0)
  * `helm` (WinGet package `Helm.Helm`, v4.3.2)
* **Cluster:** `minikube` (`--driver=docker --cpus=2 --memory=3072`), context `minikube`.
* **Namespace `gharchalo`:**
  * `gharchalo-api` — Currently on **Revision 3** (`ENABLE_EXPRESS_SURGE_PRICING=true`), actively returning **500** on `SBC ↔ HYB` and **200** on all other routes. **Revision 2** is the healthy rollback target (`ENABLE_EXPRESS_SURGE_PRICING=false`).
  * `gharchalo-loadgen` — `1/1 Running`, continuously hitting `gharchalo-api:8000`.
  * `gharchalo-postgres` — `1/1 Running` (uses `emptyDir`; seeded).
  * `gharchalo-web` — `1/1 Running`.
  * `ServiceMonitor/gharchalo-api` — Applied in `gharchalo` (`release: nudgebee-prometheus`), scraping `/metrics` every `15s`.
* **Namespace `nudgebee-agent`:**
  * `nudgebee-agent-runner`, `nudgebee-agent-forwarder`, `nudgebee-agent-node-agent` — Running and connected to `https://app.nudgebee.com`. Runner auto-discovered in-cluster Prometheus (`http://nudgebee-prometheus-kube-p-prometheus.nudgebee-agent.svc.cluster.local:9090`).
  * `nudgebee-prometheus` (`kube-prometheus-stack` with 2Gi PVC) — Prometheus, Grafana (`admin`/`admin`), Alertmanager, kube-state-metrics, node-exporter all `Running`.
  * `nudgebee-loki` (`loki-stack` with 2Gi PVC) — `nudgebee-loki-0` and `promtail` `Running`.
  * `PrometheusRule/gharchalo-api-alerts` & `AlertmanagerConfig/nudgebee-webhook` — Applied in `nudgebee-agent`.

---

## 3. Important Gotchas & Safeguards

1. **Minikube 2 CPU / 3 GB RAM ceiling:** Running the full observability stack + NudgeBee + GharChalo inside 3 GB is tight. Avoid heavy `helm upgrade nudgebee-prometheus` calls (they can time out `etcd`). Use lightweight `kubectl apply` or `kubectl set env` instead.
2. **NudgeBee Telemetry UI DNS error:** Do **not** enter `*.svc` URLs into NudgeBee's cloud/external integration form (NudgeBee Cloud DNS `10.100.0.10` cannot resolve local minikube `.svc` names). The in-cluster `nudgebee-agent-runner` already auto-discovered Prometheus. Only enter `.svc` URLs if routing **via the cluster agent**.
3. **Seeded station codes are Indian Railway codes, not airport codes:** Use `SBC`, `HYB`, `NDLS`, `JP` (not `MAA`, `DEL`, `BOM`).
4. **Never send loadgen traffic to real Sarvam:** Always keep `X-Load-Test: 1` on `/voice` in `loadgen.yaml`.
5. **Flagsmith key not yet configured in cluster:** `gharchalo-api` currently runs with safe defaults (`flagsmith: "defaults"`). To enable live Flagsmith in the cluster, pass `FLAGSMITH_SERVER_KEY` (and `DEMO_NOW=2026-11-25T10:00`, `ALLOW_FLAG_OVERRIDE=0`) via `api.extraEnv` in Helm or a K8s Secret.
6. **Cleanup item:** An accidental untracked folder `cUsersHPDesktopflagsmith-local` (from running Windows backslash paths in Git Bash) may still exist in the repo root — delete it before committing.
7. **Secrets:** Never commit `api/.env`, Sarvam keys, Flagsmith `ser.` keys, or NudgeBee auth tokens.

---

## 4. Quick Commands for Next Steps

```powershell
# Roll back the buggy Revision 3 -> healthy Revision 2 (or approve in NudgeBee UI)
kubectl -n gharchalo rollout undo deployment/gharchalo-api

# Re-trigger the buggy Revision for a live demo
kubectl -n gharchalo set env deployment/gharchalo-api ENABLE_EXPRESS_SURGE_PRICING=true

# Trigger Page 5 Core Incident (TatkalStorm + OOMKilled / DB Pool Exhaustion)
kubectl -n gharchalo set env deployment/gharchalo-loadgen VUS=30 SLEEP_MS=50
helm upgrade gharchalo deploy/helm/gharchalo -n gharchalo --reuse-values `
  --set api.resources.limits.memory=128Mi --set api.dbPool.size=2 --set api.dbPool.maxOverflow=0

# Open GharChalo UI and Grafana locally
kubectl -n gharchalo port-forward svc/gharchalo-web 8080:80          # http://localhost:8080
kubectl -n nudgebee-agent port-forward svc/nudgebee-prometheus-grafana 3000:80  # http://localhost:3000 (admin/admin)

# Commit all new work (after removing any accidental folders)
git add api/config.py api/main.py api/tests/test_flags.py deploy/
git commit -m "Add continuous k6 loadgen, buggy release rollback demo, and NudgeBee alerting"
```
