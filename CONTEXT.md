# GharChalo: Team Context

> **Prepared by:** Sachin · **Last updated:** 25 Nov 2026
> **For:** the teammates picking up **Flagsmith** and **Infra/NudgeBee**
> **Source of truth for scope:** `../GharChalo_Hackathon_Roadmap.pdf` (P0 / P1 / P2 priorities)

This file tells you what exists, how to run it, what you must not break, and exactly where your part plugs in.

---

## 1. Status at a glance

| Area | Status | Notes |
|---|---|---|
| Voice (Sarvam STT + extraction) | ✅ Done, tested live | Hindi works end to end with a real key |
| Station aliases | ✅ Done | 32 stations / 11 cities, Hindi/Kannada/Tamil spellings |
| Seeded data (trains, buses, travellers) | ✅ Done | Deterministic; SQLite and Postgres both verified |
| `/search` (direct, nearby stations, cab estimate) | ✅ Done | |
| `/match` + accept (co-travellers) | ✅ Done | Every offer is logged to `match_events` |
| Multi-leg journeys (train/bus/cab) | ✅ Done (stretch, built early) | Timing rules tested on all city pairs |
| Frontend (React) | ✅ Done | Speak/Type, tabs, picks, sort, mobile |
| Backend tests | ✅ 98 passing | `pytest` in `api/` |
| **Flagsmith** | ⏳ **Not started in code** | Dashboard setup in progress (Sachin). See §8 |
| **`/metrics` (Prometheus)** | ❌ Not built | Needed by infra. See §9 |
| Docker Compose (whole stack) | ✅ Done, verified | `docker compose up --build` → http://localhost:8080 |
| Helm chart + local-cluster script | ✅ Done (lint/render verified, not yet deployed to a cluster) | `deploy/k8s-up.sh`. See §9 |
| k6 storm, Grafana, NudgeBee | ❌ Not started | See §9 |
| Bulbul TTS | ❌ Not built (optional) | `tatkal_level` 2 assumes it exists. See §8.4 |
| Git repo | ✅ https://github.com/sachin9536/gharchalo | |

---

## 2. Run it locally

**Fastest (Docker only, ≈2 minutes):**
```bash
cp api/.env.example api/.env    # optional: add SARVAM_API_KEY for voice
docker compose up --build       # then open http://localhost:8080
```
**Kubernetes:** `deploy/k8s-up.sh` (kind / minikube / Docker Desktop), then the port-forward it prints.

**For development with hot reload:**


**Requirements:** Python 3.11+ (tested on 3.14), a recent Node (tested on 26), and optionally Docker for Postgres.

```bash
# API
cd api
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env              # add SARVAM_API_KEY (ask Sachin); see §6 for other settings
# Quickest database: SQLite. Put this line in .env:   DATABASE_URL=sqlite:///gharchalo.db
.venv/bin/python seed.py          # DROPS and refills all tables
.venv/bin/uvicorn main:app --reload --port 8000
.venv/bin/python -m pytest -q     # 97 tests, no Sarvam key needed (Sarvam is mocked)

# Web (second terminal)
cd web && npm install && npm run dev      # http://localhost:5173, proxies /api/* -> :8000
```

**Postgres instead of SQLite** (needed for the DB-pool incident later):
```bash
docker run -d --name gharchalo-pg -p 5432:5432 \
  -e POSTGRES_USER=gharchalo -e POSTGRES_PASSWORD=gharchalo -e POSTGRES_DB=gharchalo postgres:16
# Wait ~5 s for first-time init, remove DATABASE_URL from .env (Postgres is the default), then:
.venv/bin/python seed.py
```

**Check it works:** open http://localhost:5173, pick **Type → Bengaluru → Hyderabad → Fri 27 → Find ways home**.

---

## 3. Architecture

```
Browser (React + Vite, :5173)
  │  /api/* proxied by Vite (no CORS)
  ▼
FastAPI (:8000)
  ├─ POST /voice ─────────► Sarvam STT (saaras) ─► Sarvam chat (sarvam-105b) ─► journey.py (aliases, validation)
  ├─ POST /journey/parse ─► Sarvam chat only (text in)
  ├─ GET  /search ────────► search.py ─► connections.py (multi-leg, only when needed)
  ├─ POST /match, /match/{id}/accept ─► matching.py ─► match_events table
  ├─ GET  /stations, /healthz
  ▼
SQLAlchemy ─► Postgres (default) or SQLite
```

**Key design rules:**
- **The model never chooses station codes.** Sarvam returns the city words the speaker used, and `stations.py` maps them to codes.
- **All data is simulated.** Every search and match response carries `source: "simulated"` and the UI labels it. Train numbers start with `9` and operators are invented.
- **Load tests never reach Sarvam.** A request with the header `X-Load-Test: 1` gets a canned journey after about 0.8 s.

---

## 4. Repo map

```
api/
  main.py          routes + error mapping (start here)
  config.py        every setting, read from env / api/.env
  sarvam.py        Sarvam HTTP client (STT + chat), uses OS trust store for TLS
  journey.py       raw extraction -> validated Journey (missing/warnings)
  stations.py      alias resolution (reads seed_data.STATIONS)
  seed_data.py     stations, routes, name pools, DEMO_DATE   <- edit here to change the data
  seed.py          deterministic generator; scripted demo described in its docstring
  models.py        tables: stations, services, travellers, match_events
  db.py            engine; pool size/overflow/timeout from env (fault knobs)
  search.py        /search logic (direct, nearby alternatives, cab estimate)
  connections.py   multi-leg planner; timing rules in the docstring
  matching.py      co-traveller strategies (exact / time_window)
  fares.py, geo.py, schemas.py   small shared helpers
  scripts/smoke_sarvam.py        check a real Sarvam key + model names
  tests/           97 tests (seed, search, match, connections, voice)
web/src/
  App.tsx          page layout, voice flow, search state
  TypedSearch.tsx  typed form (swap, date chips, popular routes)
  Results.tsx      tabs, picks, direct + nearby lists, cab card
  Connections.tsx  multi-leg journeys
  CabMatches.tsx   co-traveller list + accept
  api.ts           typed API client (mirrors the backend models)
  user.ts          anonymous stable user id (localStorage) <- Flagsmith identity
  demo.ts          demo dates, popular routes, example phrases
  useRecorder.ts, wav.ts   mic recording + browser-side WAV conversion
```

---

## 5. API contract (do not change shapes without telling the team)

| Method | Path | Input | Output (key fields) |
|---|---|---|---|
| POST | `/voice` | multipart `file`; optional header `X-Load-Test: 1` | `{transcript, language_code, journey, source: "sarvam"\|"stub"}` |
| POST | `/journey/parse` | `{text}` | same as `/voice` |
| GET | `/search` | `origin, dest, date, max_station_distance_km (0–30, default 15), include_connections (bool)` | `{source, options[], preferred_station_has_train_seats, alternatives[], more_alternatives_beyond_limit, cab{}, connections[], connections_reason}` |
| POST | `/match` | `{user_id, origin, dest, date, window_start, window_end, strategy: "exact"\|"time_window"}` | `{match_id, strategy, offered, suggested_group_size, matches[]}` |
| POST | `/match/{id}/accept` | none | `{match_id, accepted}` |
| GET | `/stations` | none | each city's main station |
| GET | `/healthz` | none | `{status, sarvam_configured}` |

**Journey JSON** (Sarvam extraction → backend):
```json
{ "origin": {"spoken": "बैंगलोर", "code": "SBC", "name": "KSR Bengaluru City"},
  "destination": {"spoken": "हैदराबाद", "code": "HYB", "name": "Hyderabad Deccan (Nampally)"},
  "date": "2026-11-27", "fallback_mode": "train|shared_cab|any", "language": "hi",
  "missing": [], "warnings": [] }
```

**Error codes:**

| Code | Meaning |
|---|---|
| 400 | Bad input (empty audio or text, same-city search) |
| 404 | Unknown station or match |
| 409 | Accepting an offer that had no matches |
| 413 | Audio upload too large |
| 422 | Validation error, or no speech detected |
| 502 | Sarvam failure |
| **503** | **Sarvam rate limit (429), or database unavailable / connection pool exhausted** |

Infra should alert on the 503s.

---

## 6. Configuration (`api/.env`, all optional except the key)

| Variable | Default | Purpose |
|---|---|---|
| `SARVAM_API_KEY` | none | Required for voice. **Never commit it.** |
| `SARVAM_CHAT_MODEL` | `sarvam-105b` | `sarvam-m` is deprecated |
| `SARVAM_STT_MODEL` | `saaras:v3` | |
| `SARVAM_TIMEOUT_SECONDS` | `30` | Raise it if the 105B model times out |
| `SARVAM_CA_BUNDLE` | none | Path to a PEM file, only if a corporate proxy re-signs TLS and the OS keychain doesn't trust it |
| `DATABASE_URL` | Postgres on localhost | `sqlite:///gharchalo.db` for quick dev |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `10` | **Fault knob:** set to `2` / `0` for the DB-pool incident |
| `DB_POOL_TIMEOUT_SECONDS` | `10` | How long a request waits for a connection before it returns 503 |
| `LOAD_TEST_STUB_DELAY_SECONDS` | `0.8` | Fake Sarvam latency for `X-Load-Test` requests |
| `MAX_AUDIO_BYTES` | 10 MB | |

---

## 7. The seeded data and the scripted demo

- **Volume:** 32 stations, **1,587 trains, 613 buses, 300 travellers**. It covers **26 Nov – 1 Dec 2026** only, and other dates return empty results.
- **Repeatable:** seeding is deterministic, so the same data comes out every time. That matters for repeatable storms.
- **Changing the dates:** if the hackathon dates differ, change `DEMO_DATE`, `DEFAULT_START_DATE` and `DEFAULT_DAYS` in `seed_data.py`, plus `DEMO_DATE` and `SEED_DATES` in `web/src/demo.ts`.

**Demo route: Bengaluru → Hyderabad, Fri 27 Nov.** Tests check every point below.

| What | Value |
|---|---|
| Trains from KSR Bengaluru City (SBC) | All waitlisted |
| Trains with seats from nearby stations | BNC **3.7 km**, SMVB **11.3 km**, BID **28.1 km**. The 5 / 15 / 30 km cohorts see **1 / 2 / 3** of them |
| Buses from SBC | Have seats (₹1,200–₹1,450) |
| Shared cab estimate | ~625 km, ~₹8,125 per cab |
| Co-travellers, evening 18:00–22:00 | **3** exact matches, **6** with the flexible strategy |

**Multi-leg journeys:**
- 68 of 110 city pairs have one.
- Bengaluru → Jaipur has no direct service, so connections appear automatically. Example: a train to Kota, then a shared cab.

---

## 8. Handoff: Flagsmith (the "Best use of Flagsmith" prize)

### 8.1 Dashboard (Sachin is setting this up; confirm the names before coding)

**Server-side environment key** (starts with `ser.`): put it in `api/.env` as `FLAGSMITH_SERVER_KEY`. Use **local evaluation**, so flag checks make no network call per request.

**Features:**

| Feature | Type | Value |
|---|---|---|
| `tatkal_level` | Remote config, number | `0` |
| `max_station_distance_km` | Multivariate | `15` control, plus `5` and `30` at 33% each |
| `matching_strategy` | Multivariate | `exact` control, `time_window` 50% |
| `matching_config` | Remote config, JSON | `{"time_window_min":120,"date_flex_days":1,"max_matches":8}` |
| `interaction_mode` | Remote config, string | `voice` (P1: `text_only` fallback) |

**Segment `urgent_travellers`:**
- Rule: trait `travels_within_48h == true`.
- **Segment override:** `tatkal_level = 0`.

**Still unverified:** whether the free tier includes segment overrides, multivariate flags and the audit log.

### 8.2 Where it plugs in

| Flag | Current temporary control | Replace with |
|---|---|---|
| `max_station_distance_km` | Query param on `GET /search` (`main.py` → `search_journeys`); the UI's 5/15/30 km buttons in `Results.tsx`, driven by `maxKm` state in `App.tsx` | Read per identity on the server; remove the buttons (or keep a demo-only override) |
| `matching_strategy` | `strategy` field on `POST /match`; the UI buttons in `CabMatches.tsx` | Read per identity; `matching.find_matches` already accepts `strategy` |
| `matching_config` | `matching.DEFAULT_CONFIG` | Pass the flag JSON as `config=` to `find_matches` (it merges over the defaults) |
| `tatkal_level` | Not implemented | See §8.4 |

### 8.3 Identity

- **Identifier:** the browser sends an anonymous stable id (`web/src/user.ts`, localStorage key `gharchalo.userId`). It's already sent as `user_id` on `/match`.
- **`/search`:** it does not send an id yet. Add a `user_id` param or header so the distance cohort is per user.
- **Trait `travels_within_48h`:** compute it on the server from the journey date.
- **Trait `lang`:** comes from the journey's `language`. Optional.
- **Safe defaults:** always give each flag a default (the current hardcoded values), so the app works when Flagsmith is unreachable.

### 8.4 `tatkal_level` (experiment A) ladder, and the gaps

| Level | Roadmap behaviour | Reality today |
|---|---|---|
| 1 | Poll every 120 s | ⚠️ **The frontend does not poll at all.** Either add polling or pick a different level-1 action |
| 2 | Skip TTS | ⚠️ **TTS isn't built.** Build a minimal Bulbul reply, or redefine level 2 (e.g. skip multi-leg planning, which is CPU-heavy) |
| 3 | Serve `/search` from a 30 s cache; pause `/match` | Not built; straightforward in `search.py` / `main.py` |

Urgent travellers (the segment override) must stay at level 0.

### 8.5 Experiment B logging (not built)

The roadmap wants these per cohort: alternatives shown, alternatives selected, selection rate, extra distance and abandonment.
- **Today:** only `match_events` exists (offers and accepts per strategy).
- **Needed:** a table or log for search impressions and a "select alternative" action. There is no select button on alternatives yet.

---

## 9. Handoff: Infra + NudgeBee

### 9.1 Needed from the app (not built yet; whoever gets there first)

- [ ] **`/metrics`** in Prometheus format. Suggested: `prometheus-fastapi-instrumentator` for request rate, latency and status. Add counters for:
  - `matches_offered_total{strategy}` and `matches_accepted_total{strategy}`
  - `search_source_total{source}` (live or cache, once caching exists)
  - a `tatkal_level` gauge
- [x] **`api/Dockerfile`** and **`web/Dockerfile`** (nginx serves the build and proxies `/api/*` to the API; `API_UPSTREAM` sets the target).
- [x] **`docker-compose.yml`**: Postgres, a one-off `seed` service (`seed.py --if-empty --wait 60`, so restarts never wipe data), API, web on `:8080`.
- [x] **Helm chart `deploy/helm/gharchalo`**: api + web + Postgres Deployments/Services, `/healthz` probes, a post-install seed Job, secrets for the DB URL and the Sarvam key. `deploy/k8s-up.sh` / `k8s-down.sh` wrap it for local clusters.
- [ ] **Not yet:** a real cluster run (lint and render only so far), Prometheus scrape annotations (add them once `/metrics` exists), kube-prometheus-stack, NudgeBee agent.

### 9.2 Fault knobs (the planted incidents)

| Incident | Knob | Expected signal |
|---|---|---|
| Memory | Helm: `--set api.resources.limits.memory=128Mi` (fix: `512Mi`) | `OOMKilled` restarts |
| DB pool | Helm: `--set api.dbPool.size=2 --set api.dbPool.maxOverflow=0` (fix: `20` / `10`). Compose: `DB_POOL_SIZE=2 DB_MAX_OVERFLOW=0 docker compose up -d api` | 503s with `Database unavailable (TimeoutError)`, p95 up |

Pass Helm knobs straight through the script: `deploy/k8s-up.sh --set api.resources.limits.memory=128Mi`.

There is no app code to write for these; the knobs are config only.

### 9.3 Load test (TatkalStorm)

- **Sarvam:** send `X-Load-Test: 1` on every `/voice` request. **Never** send storm traffic to the real Sarvam API.
- **Suggested mix:** `/search` 70%, `/match` 20%, `/voice` (stubbed) 10%.
- **Demo route:** `origin=SBC&dest=HYB&date=2026-11-27`.
- **Hot spot:** `/search` with `include_connections=true`, or a route with no direct seats such as `SBC → JP`, runs the multi-leg planner. That costs a few ms of CPU each time, so use it to create load.
- **Writes:** `/match` writes a row on every call, which adds DB pressure.

### 9.4 NudgeBee

- **Inputs it needs:** a cluster connection, Prometheus and an LLM connection. Verify these first; it's the biggest unknown.
- **Minimum deliverable:** one credible diagnosis. OOMKilled alone is enough.
- **Don't overclaim:** don't say NuBi changed anything automatically unless that has been tested end to end.

---

## 10. Gotchas we already hit

- **TLS errors to Sarvam** (`CERTIFICATE_VERIFY_FAILED`): a corporate proxy re-signs HTTPS. The client already uses the OS trust store (`truststore`). If it still fails, set `SARVAM_CA_BUNDLE`.
- **`sarvam-m` is deprecated:** use `sarvam-105b`. `scripts/smoke_sarvam.py` prints Sarvam's own error when a model name is wrong.
- **Postgres first start:** the container needs a few seconds before it accepts connections. Seeding instantly fails with "server closed the connection".
- **`.env` is read at startup only:** restart uvicorn after editing it. `--reload` covers code, not `.env`.
- **`seed.py` drops all tables** unless you pass `--if-empty` (the containers always do). Never point the plain command at anything you care about.
- **Corporate proxy (Palo Alto SSL inspection) and Docker/Kubernetes:** containers don't trust the proxy's root certificate the way a Mac does, so `/voice` answers **502** (`CERTIFICATE_VERIFY_FAILED ... self-signed certificate in certificate chain`). Typed search is unaffected. Fix: run **`deploy/trust-corporate-ca.sh`** once (saves your network's root to the git-ignored `certs/corp-ca.pem` and sets `CONTAINER_CA_BUNDLE` in `./.env`), then `docker compose up -d --build`. `deploy/k8s-up.sh` picks the file up automatically. The certificate is added to the normal trusted CAs, so it also works off the corporate network.
- **React StrictMode in dev** runs effects twice, so dev logs duplicate `/match` offers. Don't read the dev experiment counts as real.

---

## 11. Rules (from the roadmap; non-negotiable)

- No IRCTC scraping, no booking, and no storing of anyone's credentials.
- Label every simulated number as simulated, and never present load numbers as real railway traffic.
- Generate load only against our own infrastructure.
- Keep faults controlled and reversible.
- Remediation is human-approved unless automation has actually been tested.
- **Hour 3:** if the core flow is broken, drop extras. **Hour 6:** feature freeze.

---

## 12. Open questions

- [ ] Flagsmith free-tier limits (segment overrides, multivariate, audit log)
- [ ] Which LLM NuBi needs, and who provides the key
- [ ] Can NudgeBee reach a local kind cluster, or do we need a cloud cluster?
- [ ] `tatkal_level` levels 1 and 2: add polling and TTS, or redefine them (§8.4)
- [ ] Real hackathon dates: do the seed dates need moving (§7)?
- [ ] Submission format (repo, video, live demo)
