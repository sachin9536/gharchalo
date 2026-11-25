# GharChalo: Team Context

> **Prepared by:** Sachin · **Last updated:** 25 Nov 2026
> **For:** everyone on the team (product, Flagsmith, infra/NudgeBee)
> **Scope:** `GharChalo_Hackathon_Roadmap.pdf` (P0 / P1 / P2) · **What exists:** `PROJECT_INVENTORY.md` · **Flagsmith walkthrough:** `FLAGSMITH_SETUP.md`

How to run everything, the rules, and the traps we already fell into. The full feature list lives in `PROJECT_INVENTORY.md`.

---

## 1. Status at a glance

| Area | Status |
|---|---|
| Product: voice + typed search, direct / nearby / multi-leg journeys, co-travellers | ✅ |
| Product: seats on nearby dates, waitlist chance, spoken reply (Bulbul) | ✅ (new) |
| Flagsmith: 8 flags, segment, 2 native experiments, events, analytics, demo identities | ✅ self-hosted, auto-configured |
| Experiments page, simulator, matching benchmark | ✅ |
| Docker Compose, Helm chart on minikube | ✅ deployed and verified |
| NudgeBee agent | ✅ connected on minikube |
| TatkalStorm traffic generator + planted incidents | ✅ built · RCA not captured yet |
| Prometheus / Grafana dashboards | ⏳ (`/metrics` exists; nothing scrapes it in the cluster yet) |
| Backend tests | ✅ 176 passing |

---

## 2. Run it

**Docker only (≈2 minutes):**
```bash
cp api/.env.example api/.env    # optional: add SARVAM_API_KEY for voice and spoken replies
docker compose up --build       # http://localhost:8080
```
Behind a corporate proxy, voice may answer 502 inside containers: run `deploy/trust-corporate-ca.sh` once (see §10).

**Kubernetes (minikube / kind / Docker Desktop):** `deploy/k8s-up.sh`, then
`kubectl -n gharchalo port-forward svc/gharchalo-web 8080:80`.

**Development with hot reload** (Python 3.11+, recent Node):
```bash
cd api
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                      # SARVAM_API_KEY; DATABASE_URL=sqlite:///gharchalo.db for quick dev
.venv/bin/python seed.py                  # DROPS and refills all tables
.venv/bin/uvicorn main:app --reload --port 8000
.venv/bin/python -m pytest -q             # 176 tests, no Sarvam key or Flagsmith needed

cd web && npm install && npm run dev      # http://localhost:5173 (proxies /api/* to :8000)
```

**Flagsmith locally** (optional; the app runs on safe defaults without it):
```bash
docker compose -f deploy/flagsmith/docker-compose.yml up -d    # dashboard http://localhost:8090
python3 deploy/flagsmith/bootstrap.py                          # creates everything; safe to re-run
```
Then restart the API. `/healthz` reports `"flagsmith": "flagsmith"`.

**Check it works:** http://localhost:5173 → Type → Bengaluru → Hyderabad → Fri 27 → *Find ways home*.

---

## 3. Architecture

```
Browser (React + Vite)
  │  /api/*  (Vite proxy in dev, nginx in Docker/Kubernetes)
  ▼
FastAPI
  ├─ /voice, /journey/parse ─► Sarvam STT + chat ─► journey.py (aliases, validation)
  ├─ /speak ─────────────────► Sarvam Bulbul (cached; off at Tatkal level 2 / text-only)
  ├─ /search, /search/dates ─► search.py ─► connections.py (multi-leg) · waitlist.py
  ├─ /match, /match/{id}/accept ─► matching.py (exact / flexible)
  ├─ /config, /experiments/* ─► flags.py (Flagsmith local evaluation) · experiment_events.py
  └─ /metrics, /healthz
  ▼
SQLAlchemy ─► Postgres (default) or SQLite
Flagsmith (self-hosted, :8090) ◄─ local evaluation + exposure/conversion events
```

**Design rules:**
- **The model never chooses station codes.** Sarvam returns city words; `stations.py` maps them.
- **All data is simulated** and labelled so (`source: "simulated"`).
- **Load tests never reach Sarvam:** `X-Load-Test: 1` gets a canned journey or silence.
- **Flagsmith can never break the app:** local evaluation, safe defaults, 2 s timeout and no retries when it is down.
- **Analytics never break a request:** experiment events are buffered and best-effort.

---

## 4. Repo map

```
api/
  main.py              routes, error mapping, Tatkal ladder, experiment read-outs (start here)
  config.py            every setting (env / api/.env / api/.env.local)
  flags.py             Flagsmith client, per-visitor flags, safe defaults
  experiment_events.py exposures + conversions for Flagsmith's Experiments tab
  sarvam.py            STT, extraction, text-to-speech
  search.py            /search, /search/dates, cab estimate, waitlist chances
  waitlist.py          waitlist confirmation rule of thumb
  connections.py       multi-leg planner (timing rules in the docstring)
  matching.py          exact / flexible co-traveller matching
  benchmark.py         deterministic matching benchmark
  cache.py, metrics.py Tatkal level-3 cache, Prometheus metrics
  journey.py, stations.py, seed.py, seed_data.py, models.py, db.py, fares.py, geo.py, schemas.py
  scripts/             smoke_sarvam.py, tatkal_storm.py
  tests/               176 tests
web/src/
  App.tsx              layout, voice flow, search state, Flagsmith banners
  Results.tsx          tabs, picks, filters, date strip, read aloud, nearby stations, cab
  Experiments.tsx      the experiments page (stats.ts for intervals and tests)
  TypedSearch, Welcome, Connections, CabMatches, DateStrip, ReadAloud (components)
  api.ts               typed API client · user.ts identity (+ ?as= demo identity) · urlstate.ts shareable URLs
deploy/
  k8s-up.sh, k8s-down.sh, trust-corporate-ca.sh
  helm/gharchalo/      chart (api, web, postgres, seed job, CA bundle)
  flagsmith/           self-hosted Flagsmith + bootstrap.py
  experiments/         simulate.py
  storm/run.sh         TatkalStorm as an in-cluster Job
  incidents/incident.sh planted incidents on/off
  nudgebee/            agent values for corporate-proxy networks
```

---

## 5. API contract (tell the team before changing a shape)

The full list of 14 endpoints is in `PROJECT_INVENTORY.md` §6. The ones other code relies on:

| Method | Path | Key fields |
|---|---|---|
| GET | `/search` | `options[]` (with `confirm_chance` on waitlisted trains), `alternatives[]`, `cab`, `connections[]`, `tatkal_level`, `served_from`, `search_id` |
| GET | `/search/dates` | `days[]`: `options`, `with_seats`, `trains_with_seats`, `buses_with_seats`, `cheapest_with_seats` |
| POST | `/match` | `strategy`, `offered`, `matches[]` (each with `pickup_km`, `day_shift`, `time_gap_min`), `paused` |
| POST | `/speak` | `{text, language, date}` → `audio/wav` |
| GET | `/config` | `tatkal_level`, `poll_s`, `interaction_mode`, `cohort_km`, `matching_strategy`, `urgent` |

Identity: the browser sends `X-User-Id` (anonymous, stable; `?as=demo-5km` pins a demo identity).

**Error codes:** 400 bad input · 404 unknown station/match · 409 a deliberate "off" (text-only mode, Tatkal-paused spoken
replies, accepting an empty offer) · 413 audio too large · 422 validation / no speech · 502 Sarvam failure ·
**503** Sarvam rate limit, or database unavailable / pool exhausted.

---

## 6. Configuration (`api/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `SARVAM_API_KEY` | none | Voice and spoken replies. **Never commit it** |
| `SARVAM_CHAT_MODEL` / `SARVAM_STT_MODEL` | `sarvam-105b` / `saaras:v3` | `sarvam-m` is retired |
| `SARVAM_TTS_MODEL` / `SARVAM_TTS_SPEAKER` | Sarvam's defaults | e.g. `bulbul:v3` / `priya` |
| `TTS_MAX_CHARS` | `500` | Longer text is cut |
| `SARVAM_TIMEOUT_SECONDS` | `30` | |
| `SARVAM_CA_BUNDLE` | none | Corporate root CA (PEM), added to the system CAs |
| `DATABASE_URL` | Postgres on localhost | `sqlite:///gharchalo.db` for quick dev |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT_SECONDS` | `10` / `10` / `10` | DB-pool incident knobs |
| `FLAGSMITH_SERVER_KEY`, `FLAGSMITH_API_URL` | none | Written to `api/.env.local` by `bootstrap.py` |
| `FLAGSMITH_REFRESH_SECONDS` | `10` | How fast dashboard changes land |
| `FLAGSMITH_TIMEOUT_SECONDS` | `2` | Fail fast when Flagsmith is down |
| `FLAGSMITH_ANALYTICS` / `FLAGSMITH_EVENTS` | `1` / `1` | Flag charts / experiment events |
| `FLAGSMITH_OFFLINE_FILE` | none | `flagsmith_env.json` for no-Wi-Fi demos |
| `ALLOW_FLAG_OVERRIDE` | `1` | Demo override buttons (km cohort, matching strategy) |
| `DEMO_NOW` | real time | Pins "today" (urgency, waitlist chance) for a predictable demo |
| `FAULT_UNBOUNDED_SEARCH_LOG` | `0` | **Planted memory leak** for the incident demo |
| `LOAD_TEST_STUB_DELAY_SECONDS` | `0.8` | Fake Sarvam latency for load tests |

`api/.env.local` (written by `bootstrap.py`) is read before `api/.env`. Both are git-ignored and excluded from images.

---

## 7. Data and the scripted demo

32 stations · 1,587 trains · 613 buses · 300 travellers · **26 Nov – 1 Dec 2026** only · deterministic. To move dates, change
`DEMO_DATE`, `DEFAULT_START_DATE`, `DEFAULT_DAYS` in `seed_data.py` and `DEMO_DATE`, `SEED_DATES` in `web/src/demo.ts`.

**Bengaluru → Hyderabad, Fri 27 Nov** (tests pin all of this):

| What | Value |
|---|---|
| Trains from KSR Bengaluru City (SBC) | All waitlisted (WL 118 SL ≈ 26%, WL 46 3A ≈ 40% may confirm) |
| Train seats from nearby stations | BNC 3.7 km, SMVB 11.3 km, BID 28.1 km → 5 / 15 / 30 km cohorts see 1 / 2 / 3 |
| Buses from SBC | Seats available |
| Nearby days | Seats on 26, 28, 29, 30 Nov |
| Co-travellers, evening | 1 exact, 6 flexible |
| Bengaluru → Jaipur | No direct service: journeys with changes appear automatically |

---

## 8. Flagsmith

Everything (flags, segment, identities, experiments, events, how to read the numbers) is listed in `PROJECT_INVENTORY.md` §2 and
walked through in `FLAGSMITH_SETUP.md` (§0 setup, §0b experiments page and simulator, §0c matching A/B, §0d the Flagsmith UI).

Things that surprise people:
- **A flag inside a running experiment ignores edits in the Features tab.** Change it from the **Experiments** tab (this hit
  `max_station_distance_km` when it was moved from 15 to 20 and back).
- **`tatkal_level` 2 also turns off spoken replies**, except for travellers within 48 hours (they stay at level 0).
- **Pinned demo identities** never take part in experiments (identity overrides are hand-picked by design).
- **Experiment numbers from the simulator are noise:** its visitors behave identically in every variant.

---

## 9. Infra, NudgeBee and the incident demo

```bash
deploy/k8s-up.sh                          # build, load into minikube, install/upgrade the chart
deploy/storm/run.sh                       # TatkalStorm Job; extra args go to the script (e.g. --peak-rps 80)
deploy/incidents/incident.sh oom          # leaky release + 128Mi memory limit
deploy/incidents/incident.sh status       # restarts, last termination reason (OOMKilled), warning events
deploy/incidents/incident.sh fix          # remove the leak, 512Mi, healthy pool
```

**Why a planted leak:** the app's memory is flat under load (75–82 MiB at 80 req/s), so a lower limit alone never crashed it.
`FAULT_UNBOUNDED_SEARCH_LOG` keeps every search response, so memory climbs with traffic and Kubernetes kills the container.

**Demo flow:** healthy storm (baseline) → `incident.sh oom` → storm → NudgeBee shows the OOMKilled restarts → ask NuBi for the root
cause → `incident.sh fix` → storm again → compare. **Status:** the healthy baseline is measured (1,987/1,987 OK at 40 req/s,
p50 3–6 ms); the incident run and the RCA are still to be captured.

The NudgeBee agent setup on a corporate network is in §14. NudgeBee sees the whole cluster.

### 9.1 Bad release and rollback (roadmap incident 2)

A release is a **Deployment revision**, not a runtime toggle. Release `1.5.0 "Express surge pricing"` ships a real bug
(`api/surge_pricing.py`: the new festival corridor's capacity is 0, so the multiplier divides by zero): `GET /search`
Bengaluru ↔ Hyderabad returns 500 in both directions, every other route stays 200, and the API log carries the genuine traceback
tagged `release 1.5.0`, with no hint about the fix. `kubectl rollout history deployment/gharchalo-api` names every release
(`1.4.0: Baseline`, `1.5.0: Express surge pricing`); responses carry `X-Release`, and `/healthz` reports `release`.

```bash
deploy/release.sh v2          # ship the buggy 1.5.0 (the k6 loadgen in the chart produces the 500s continuously)
deploy/release.sh status      # live vs Helm, rollout history, corridor and control-route check
# NudgeBee investigates (pod logs + rollout history) and rolls back = `kubectl rollout undo deployment/gharchalo-api`
deploy/release.sh reconcile   # REQUIRED after a kubectl/NudgeBee rollback: make Helm agree with what is live
deploy/release.sh rollback    # the human path: back to the previous *release* through Helm
```

Two traps, both verified and handled:
- **Helm drift.** `kubectl rollout undo` changes the Deployment, not Helm's record. Without `reconcile`, the next
  `helm upgrade --reuse-values` (incident.sh, a re-deploy) silently ships 1.5.0 again.
- **Helm 4 server-side apply.** After a kubectl rollback, kubectl owns those fields and every Helm upgrade fails with a conflict.
  `k8s-up.sh`, `release.sh` and `incident.sh` pass `--force-conflicts` on Helm 4 (not on Helm 3, which has no such conflict).
- `release.sh rollback` targets the last revision with a **different version**: `helm rollback` alone goes to the previous
  revision, which can be the same buggy release.

The Flagsmith flag `route_fault_sbc_hyb` is the *other* recovery path (feature disable, no deploy); the release switch is the
rollback path. The k6 loadgen's visitors are `sim-loadgen-vu-*` and send no Flagsmith exposures.

**Automatic alerting** (`deploy/nudgebee-alerts.yaml`: 5xx-rate PrometheusRule → Alertmanager → NudgeBee runner) needs
kube-prometheus-stack, which runs on Bhavesh's cluster but not on Sachin's (the NudgeBee install there disabled Prometheus).
Without it, ask NuBi directly; it reads pod logs and deployment history either way.

---

## 10. Gotchas we already hit

- **Corporate proxy (Palo Alto SSL inspection):** anything that does not use the Mac's keychain fails with
  `certificate verify failed` / `x509: unknown authority`: Sarvam from containers (502), minikube image pulls, the NudgeBee runner.
  Fix: `deploy/trust-corporate-ca.sh` saves the root to `certs/corp-ca.pem` (git-ignored); Compose, the Helm chart and the
  NudgeBee values file use it.
- **Local secrets in images:** `api/.env.local` was once copied into the API image and made every request in the cluster ~1.2 s
  slow (it pointed at a Flagsmith on `localhost` that does not exist there). `.dockerignore` now excludes `.env*`.
- **`sarvam-m` is retired** (use `sarvam-105b`); `scripts/smoke_sarvam.py` prints Sarvam's own error.
- **`.env` is read at start-up only:** restart uvicorn after editing it.
- **`seed.py` drops all tables** unless given `--if-empty` (containers always use it).
- **Postgres first start** needs a few seconds before it accepts connections.
- **React StrictMode in dev** runs effects twice: dev experiment counts are inflated.

---

## 11. Rules (roadmap; non-negotiable)

- No IRCTC scraping, no booking, no stored credentials.
- Label every simulated number as simulated; never present load as real railway traffic.
- Generate load only against our own infrastructure. Faults stay controlled and reversible.
- Remediation is human-approved unless automation was actually tested.
- Never commit keys: Sarvam, Flagsmith server key, NudgeBee install keys.

---

## 12. Open items

See `PROJECT_INVENTORY.md` §9 (NudgeBee RCA, fare split, Tatkal countdown, Prometheus/Grafana, key rotation).

---

## 13. Experiments and honest reporting

The **Experiments** page (header link, `/#experiments`) and Flagsmith's own **Experiments** tab both show the two experiments.
`deploy/experiments/simulate.py` adds clearly labelled synthetic visitors (`sim-…`), kept apart from real ones everywhere.
**Say:** Flagsmith assigned the variants, every event was recorded, and the read-out shows sample sizes and confidence ranges;
Tatkal degradation was measured on our own system. **Don't say:** that travellers preferred a variant.

---

## 14. NudgeBee agent on minikube (corporate proxy)

Install with the command from the NudgeBee dashboard (it carries account keys: **never commit them**). Then, on a network that
re-signs HTTPS:

1. **Image pulls fail** (`ErrImagePull`): pull with the Mac's Docker and load into minikube.
   ```bash
   kubectl -n nudgebee-agent get deploy,ds -o jsonpath='{range .items[*]}{range .spec.template.spec.containers[*]}{.image}{"\n"}{end}{end}'
   docker pull <image> && minikube image load <image>        # for each image
   kubectl -n nudgebee-agent delete pod --all
   ```
2. **The runner cannot reach** `relay.nudgebee.com` / `collector.nudgebee.com`: give it the corporate root CA.
   ```bash
   kubectl -n nudgebee-agent create configmap corp-ca --from-file=corp-ca.pem=certs/corp-ca.pem
   helm upgrade nudgebee-agent nudgebee-agent/nudgebee-agent -n nudgebee-agent --reuse-values \
     -f deploy/nudgebee/trust-corporate-ca.values.yaml
   ```
   Success: `"relay connected"` in `kubectl -n nudgebee-agent logs deploy/nudgebee-agent-runner`.

The agent can read pod logs, events and ConfigMaps in every namespace (not Secrets) and can delete pods, patch deployments and
exec into pods. Prometheus, Loki and ClickHouse were not installed; NudgeBee works from Kubernetes events and the agent's data.
