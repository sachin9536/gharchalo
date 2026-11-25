# GharChalo: Project Inventory

> **What this is:** the single list of everything that exists in this repo, so the team can track it.
> **Kept by:** Sachin · **Last updated:** 25 Nov 2026 · **Backend tests:** 176 passing (`cd api && .venv/bin/python -m pytest -q`)
> How to run things: `CONTEXT.md`. Flagsmith walkthrough: `FLAGSMITH_SETUP.md`.
>
> Status key: ✅ built and verified · 🟡 built, partly verified (say how) · ⏳ not built

All railway data, fares, travellers and load are **simulated**. Never present them as real.

---

## 1. Product features (what a traveller sees)

| Feature | Status | Where | Notes |
|---|---|---|---|
| Voice search (Hindi, Hinglish, English…) | ✅ | `api/sarvam.py`, `web/src/useRecorder.ts`, `wav.ts` | Sarvam Saaras STT + `sarvam-105b` extraction. Station codes come from aliases, never from the model |
| Fix-the-transcript-and-retry | ✅ | `POST /journey/parse` | |
| Typed search (swap, date chips, recent searches) | ✅ | `web/src/TypedSearch.tsx`, `recent.ts` | Works without a microphone or Sarvam |
| Welcome screen + popular routes | ✅ | `web/src/Welcome.tsx` | |
| Trains and buses from your station | ✅ | `GET /search`, `api/search.py` | Sort, "seats only" and time-of-day filters, Cheapest/Fastest badges |
| Trains with seats from nearby stations | ✅ | `api/search.py` | Distance limit = Flagsmith cohort (Experiment B) |
| Journeys with changes (train + bus + cab) | ✅ | `api/connections.py`, `web/src/Connections.tsx` | Timing rules tested on all 110 city pairs; coloured timeline bar |
| Shared cab: fare estimate + co-travellers | ✅ | `POST /match`, `api/matching.py`, `web/src/CabMatches.tsx` | Exact vs flexible matching (A/B), each match shows its cost (km / days / time) |
| **Seats on nearby dates** | ✅ | `GET /search/dates`, `web/src/DateStrip.tsx` | ±3 days; tap a day to search it; agrees with `/search` on every day (tested) |
| **Waitlist confirmation chance** | ✅ | `api/waitlist.py` | Rule of thumb on simulated data, labelled as an estimate, not a prediction |
| **Spoken reply (Sarvam Bulbul)** | ✅ | `POST /speak`, `web/src/ReadAloud.tsx`, `speech.ts` | Auto after voice search; EN/हिं toggle; cached; real call verified |
| Quickest / Cheapest / Split-a-cab pick cards | ✅ | `web/src/Results.tsx` | |
| Share by WhatsApp / copy link | ✅ | `web/src/urlstate.ts` | Search lives in the URL; keeps `?as=` demo identity |
| Experiments page | ✅ | `web/src/Experiments.tsx`, `stats.ts` | Real vs simulated visitors kept apart; 95% ranges + significance verdict |
| Fare split / expense settle-up | ⏳ | | Original problem-statement feature, not built yet |
| Tatkal countdown + calendar reminder | ✅ | `web/src/TatkalCountdown.tsx` | **Released behind the `tatkal_countdown` flag** (25% of travellers within a week) |
| Watchlist / seat alerts | ⏳ | | Out of the roadmap's scope |

---

## 2. Flagsmith (sponsor) — everything

**Server:** self-hosted at http://localhost:8090 (`deploy/flagsmith/docker-compose.yml`), configured by **`deploy/flagsmith/bootstrap.py`**
(idempotent: a second run changes nothing). Login is written to the git-ignored `deploy/flagsmith/credentials.txt`.
**App side:** `api/flags.py` (local evaluation, safe defaults, fail-fast when Flagsmith is down), `api/experiment_events.py`
(exposures + conversions). Core integration merged from **Bhavesh's** `feature/flagsmith` branch.

### 2.1 Features (9)

| Flag | Type | Default | What it controls | Tag in the dashboard |
|---|---|---|---|---|
| `tatkal_level` | number | `0` | **Experiment A** ladder: 1 slower refresh · 2 multi-leg planning **and spoken replies** off · 3 cached search, matching paused | Experiment A |
| `tatkal_config` | JSON | `{"cache_ttl_s":30,"poll_s_l0":30,"poll_s_l1":120}` | Tuning for the ladder | Experiment A |
| `max_station_distance_km` | multivariate | control `15`, `reach_5km` 33%, `reach_30km` 33% | **Experiment B**: how far to look for another station | Experiment B |
| `matching_strategy` | multivariate | control `exact`, `flexible` (= `time_window`) 50% | **Matching A/B** | Matching A/B |
| `matching_config` | JSON | `max_matches 8, exact_pickup_km 0, flex_pickup_km 15, date_flex_days 1, time_window_min 120` | The numbers behind exact/flexible | Matching A/B |
| `interaction_mode` | string | `voice` | `text_only` = Sarvam fallback (voice and spoken replies off) | Config |
| `route_fault_sbc_hyb` | boolean | off | Incident: 500s on Bengaluru ↔ Hyderabad only | Incident switch |
| `sarvam_fault_mode` | string | `none` | Incident: simulated Sarvam `429` / `timeout` / `error` | Incident switch |
| `tatkal_countdown` | boolean (release toggle) | off | **Gradual release** of the Tatkal countdown: segment `tatkal_countdown_beta` = sticky 25% of visitors travelling in 1–7 days; environment ON = everyone; OFF = kill switch | Release |

Every feature has a description in the dashboard explaining it.

### 2.2 Segment, identities, experiments, metrics

| Item | Details |
|---|---|
| Segment `urgent_travellers` | trait `travels_within_48h = true` → override `tatkal_level = 0` (fair degradation) |
| Segment `tatkal_countdown_beta` | `PERCENTAGE_SPLIT 25` AND `days_until_travel` 1–7 → `tatkal_countdown` ON (verified: 26.5% of visitors, 0% outside the window, sticky) |
| Traits sent per request | `travels_within_48h`, `days_until_travel`, `lang` |
| Demo identities (pinned by identity override, outside experiments) | `demo-5km`, `demo-15km`, `demo-30km` (1 / 2 / 3 nearby stations), `demo-exact`, `demo-flex` (1 vs 6 co-travellers), `demo-beta` (always sees released features). Open the app with `?as=<identity>` |
| Native experiment 1 | **Station reach** on `max_station_distance_km`, metric `alternative_selected`, running |
| Native experiment 2 | **Matching: exact vs flexible** on `matching_strategy`, metric `match_accepted`, running |
| Experiment metrics | `alternative_selected`, `match_accepted` (occurrence, up) |
| Events warehouse | Postgres, `source: flagsmith_database` (Flagsmith's own DB), connected |
| Flag analytics | On (`FLAGSMITH_ANALYTICS=1`); charts fill after Flagsmith's aggregation |
| Experiment events from the app | `$flag_exposure` when a flag shaped what a visitor saw; conversions on choose-station / accept-group. Pinned identities, manual overrides and load-test traffic are never counted |
| Live tuning | Change any value in the dashboard → the app follows within ~10 s (verified for `tatkal_level`, `matching_config`) |
| Offline backup | `api/flagsmith_env.json` (git-ignored) for no-Wi-Fi demos (`FLAGSMITH_OFFLINE_FILE`) |

> **Honesty rule:** the experiments are named `[demo data]`. Simulated visitors behave identically in every variant, so any
> "chance to win" Flagsmith computes from them is noise. Don't say a variant won.

### 2.3 Flagsmith-related endpoints and settings

`GET /config` (flags for the current visitor, polled by the UI) · `GET /experiments/summary?source=live|simulated|all` ·
`GET /experiments/matching-benchmark` · `POST /search/{id}/select` (Experiment B conversion) ·
settings `FLAGSMITH_SERVER_KEY`, `FLAGSMITH_API_URL`, `FLAGSMITH_REFRESH_SECONDS`, `FLAGSMITH_OFFLINE_FILE`, `FLAGSMITH_ANALYTICS`,
`FLAGSMITH_EVENTS`, `FLAGSMITH_EVENTS_URL`, `FLAGSMITH_TIMEOUT_SECONDS`, `ALLOW_FLAG_OVERRIDE`, `DEMO_NOW`.

---

## 3. Sarvam (sponsor)

| Use | Endpoint / API | Status |
|---|---|---|
| Speech to text | Saaras (`saaras:v3`), `POST /voice` | ✅ live |
| Journey extraction | chat `sarvam-105b` (`sarvam-m` is retired) | ✅ live |
| Spoken reply | Bulbul (server default model/voice; `bulbul:v3`, `bulbul:v4-flash` exist), `POST /speak` | ✅ live |
| Load-test bypass | `X-Load-Test: 1` → canned journey / silence, never real Sarvam | ✅ tested |
| Outage drills | `sarvam_fault_mode`, `interaction_mode=text_only` (Flagsmith) | ✅ tested |
| Corporate-proxy TLS | OS trust store; `SARVAM_CA_BUNDLE` / `deploy/trust-corporate-ca.sh` for containers | ✅ |

---

## 4. NudgeBee (sponsor) and incidents

| Item | Status | Where |
|---|---|---|
| NudgeBee agent on local minikube | ✅ connected (`relay connected`) | `CONTEXT.md` §14, `deploy/nudgebee/trust-corporate-ca.values.yaml` |
| Traffic generator (TatkalStorm) | ✅ | `api/scripts/tatkal_storm.py`, run in-cluster with `deploy/storm/run.sh` |
| Healthy baseline under load | ✅ 1,987/1,987 OK at 40 req/s, p50 3–6 ms (voice stub adds 0.8 s by design) | |
| Memory incident (leaky release + 128Mi) | 🟡 built and switched on; the crash under load not yet observed end to end | `deploy/incidents/incident.sh oom` / `fix`, planted fault `FAULT_UNBOUNDED_SEARCH_LOG` |
| DB-pool incident | 🟡 knob exists; queries are too fast for 2 connections to exhaust at demo load | `incident.sh db-pool` |
| **Bad release 1.5.0 + rollback** | ✅ verified end to end: 500s only on Bengaluru ↔ Hyderabad, genuine traceback tagged with the release, kubectl and Helm rollbacks, Helm reconcile | `deploy/release.sh`, `api/surge_pricing.py` (Bhavesh's design, hardened) |
| Continuous k6 load generator | ✅ in the chart (`loadgen.enabled`, on by default) | `deploy/helm/gharchalo/templates/loadgen.yaml` (Bhavesh) |
| 5xx alert → NudgeBee | 🟡 rule and webhook ready; needs kube-prometheus-stack (on Bhavesh's cluster only) | `deploy/nudgebee-alerts.yaml` (Bhavesh) |
| NudgeBee RCA captured | ⏳ | Ask NuBi in the dashboard once the incident fires |
| Prometheus / Grafana in the cluster | ⏳ | The NudgeBee install disabled its bundled Prometheus |

---

## 5. Experiments and simulation tooling

| Tool | What it does |
|---|---|
| `deploy/experiments/simulate.py` | Synthetic visitors (`sim-…`) through the real API; scenarios `distance`, `matching`, `degradation`. Degradation changes `tatkal_level` live and restores it |
| `api/benchmark.py` | Deterministic exact-vs-flexible benchmark on 9 fixed requests (also `GET /experiments/matching-benchmark`) |
| `web/src/stats.ts` + `npm run check:stats` | Wilson intervals, two-proportion test, "not enough data below 30 per group" |
| `/experiments/summary` | Per-cohort / per-strategy numbers, real and simulated kept apart; earlier-rules offers excluded, not blended |

---

## 6. API endpoints (14)

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Liveness, Sarvam configured, Flagsmith source |
| GET | `/metrics` | Prometheus metrics (`gharchalo_*`: requests, latency, latency by urgency, search source, alternatives shown/selected, matches offered/accepted/paused, tatkal level) |
| GET | `/config` | The current visitor's flags |
| POST | `/voice` | Audio → transcript → journey |
| POST | `/journey/parse` | Text → journey |
| POST | `/speak` | Text → WAV (Bulbul) |
| GET | `/stations` | Each city's main station |
| GET | `/search` | Direct options, nearby alternatives, cab estimate, journeys with changes, waitlist chances |
| GET | `/search/dates` | Availability ±N days |
| POST | `/search/{id}/select` | Visitor chose a nearby station (Experiment B) |
| POST | `/match` | Co-travellers (exact / flexible) |
| POST | `/match/{id}/accept` | Visitor accepted a group |
| GET | `/experiments/summary` | Experiment read-out |
| GET | `/experiments/matching-benchmark` | Matching benchmark |

---

## 7. Infrastructure and deployment

| Item | Status | Where |
|---|---|---|
| Docker images (API, web+nginx) | ✅ | `api/Dockerfile`, `web/Dockerfile`; local secrets excluded by `.dockerignore` |
| Docker Compose (whole stack) | ✅ verified | `docker-compose.yml` → http://localhost:8080 |
| Helm chart | ✅ deployed on minikube | `deploy/helm/gharchalo` |
| One-command local cluster deploy | ✅ | `deploy/k8s-up.sh` / `k8s-down.sh` |
| Corporate CA for containers | ✅ | `deploy/trust-corporate-ca.sh` → `certs/corp-ca.pem` (git-ignored) |
| Self-hosted Flagsmith | ✅ | `deploy/flagsmith/` |
| Schema top-up without reseeding | ✅ | `api/db.py::ensure_columns` at start-up |

---

## 8. Data

32 stations in 11 cities · 1,587 trains · 613 buses · 300 travellers · 26 Nov – 1 Dec 2026 · deterministic seed (`api/seed.py`,
`--if-empty` for containers). Demo route **Bengaluru → Hyderabad, Fri 27 Nov**: trains from SBC waitlisted, seats from stations
3.7 / 11.3 / 28.1 km away, buses with seats, 1 exact / 6 flexible co-travellers.

---

## 9. Known gaps and open items

- [ ] Capture a NudgeBee RCA of the memory incident (run `incident.sh oom`, `storm/run.sh`, ask NuBi, then `incident.sh fix`)
- [ ] Fare split (product)
- [ ] Prometheus + Grafana dashboard in the cluster
- [ ] Your local SQLite holds an older seed (1,204 services); `python seed.py` aligns it but wipes experiment events
- [ ] Rotate the NudgeBee install keys after the hackathon (they were shared in chat)
- [ ] Flagsmith audit log is empty on the free local plan
