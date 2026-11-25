# Flagsmith Setup & Live Demo Guide

All Flagsmith code is already wired in the backend (`api/flags.py`, `api/main.py`, `api/cache.py`, `api/metrics.py`) and frontend (`web/src/`). Follow these steps to connect it to your Flagsmith project.

---

## 0. Fastest: run Flagsmith locally and configure it automatically

No Flagsmith account needed. This starts your own Flagsmith and creates everything below for you (project,
8 features, the `urgent_travellers` segment and its override, a server key, and three pinned demo identities):

```bash
docker compose -f deploy/flagsmith/docker-compose.yml up -d     # first start takes a few minutes
python3 deploy/flagsmith/bootstrap.py                           # safe to re-run, creates only what is missing
```

Then restart the API. Dashboard: **http://localhost:8090** (login is saved in `deploy/flagsmith/credentials.txt`).
The script writes the server key to `api/.env.local` (git-ignored, read before `api/.env`; your `.env` is never touched)
and an offline copy of the environment to `api/flagsmith_env.json`.

Demo identities are pinned with identity overrides, so `?as=demo-5km` / `demo-15km` / `demo-30km` show exactly
**1 / 2 / 3** nearby stations on Bengaluru → Hyderabad, 27 Nov.

Gotchas: the Flagsmith container serves on 8000 (mapped to 8090 here); the app's Docker Compose stack cannot reach
`localhost:8090`, so run the API directly for Flagsmith demos; tests ignore Flagsmith entirely (`api/tests/conftest.py`).

To use a hosted Flagsmith instead, skip this section and follow sections 1-3.

---

## 0b. Experiments page, simulator, and what you can honestly claim

**Experiments page:** open the app's header link *Experiments* (or `/#experiments`). It reads `GET /experiments/summary`
and shows Experiment B (cohorts), the exact-vs-flexible matching A/B and Experiment A (Tatkal degradation), each with
sample sizes, a 95% range and a significance verdict. Tabs keep **real visitors** and **simulated visitors** apart
(`/experiments/summary?source=live|simulated|all`; simulated = identity starting `sim-`).

**Demo identities** (set by `bootstrap.py`; use as `?as=...`): `demo-5km`, `demo-15km`, `demo-30km` (1/2/3 nearby stations)
and `demo-exact`, `demo-flex` (1 vs 6 co-travellers on Bengaluru → Hyderabad, 27 Nov, evening). Changing `matching_config` in
the dashboard (see 0c) changes the results within ~10 s.

**Simulator:** `python3 deploy/experiments/simulate.py` sends synthetic visitors through the real API (`--scenario
distance|matching|degradation|all`, `--visitors N`). Visitors choose **identically in every variant**, so differences between
variants are noise by design: it validates the pipeline and says nothing about real travellers. The degradation scenario is
different: it changes `tatkal_level` in Flagsmith (0, 1, 3), measures the app's real behaviour (cache share, paused matching,
latency, who stays at level 0) and restores the original level. Latency is local-machine latency.
Remove simulated rows: `sqlite3 api/gharchalo.db "delete from match_events where user_id like 'sim-%'; delete from alternative_selections where search_event_id in (select id from search_events where user_id like 'sim-%'); delete from search_events where user_id like 'sim-%';"`

**Flagsmith's own dashboard:** flag-evaluation analytics are on (`FLAGSMITH_ANALYTICS=1`); per-flag charts fill in after
Flagsmith's scheduled aggregation (a bucket interval, up to tens of minutes). The Audit Log shows every flag change.
Flagsmith's native *Experiments* tab works locally too (see 0d). Only the managed `flagsmith` warehouse type stays "pending connection" on a self-hosted server; a `postgres` warehouse with `source: flagsmith_database` stores events in Flagsmith's own database and is connected.

**Say:** "Flagsmith assigned cohorts and strategies, we recorded every event, and the read-out reports sample sizes and
confidence ranges. We exercised it with synthetic visitors, and measured Tatkal degradation on our own system."
**Don't say:** that travellers preferred a variant, or that a simulated run is a real experiment result.

---

## 0c. Exact vs flexible matching: how the A/B works

`matching_strategy` (Flagsmith, 50/50) decides which rule-set a visitor gets; `matching_config` (JSON) holds the numbers:

| | Exact | Flexible |
|---|---|---|
| Pickup | your station (`exact_pickup_km`, default 0) | within `flex_pickup_km` (15) |
| Day | your day | ± `date_flex_days` (1) |
| Time | windows overlap | windows within `time_window_min` (120) of each other, per side |
| Both | same origin and destination *city*; at most `max_matches` (8) | |

Every match reports what it cost you (`pickup_km`, `day_shift`, `time_gap_min`), and every offer stores the averages plus the
group size, so the Experiments page can show acceptance **and** the price of flexibility.
Offers made before this rule-set existed are excluded from the A/B (counted, never blended). A pre-existing database is topped
up with the new columns on start-up; nothing is reseeded.

**Benchmark:** `GET /experiments/matching-benchmark`, or `cd api && .venv/bin/python benchmark.py`. The same nine requests run
through both strategies on the synthetic traveller pool (deterministic, writes nothing, follows the live `matching_config`).
It measures the algorithm, not people, and its size depends on how the pool was seeded.

---

## 0d. What to show in the Flagsmith UI (http://localhost:8090)

`bootstrap.py` fills the dashboard in so it explains itself. Log in with the account in `deploy/flagsmith/credentials.txt`, project
**GharChalo**, environment **Development**.

| Where | What is there |
|---|---|
| **Features** | 8 flags, each with a **description** and a **tag**: *Experiment A*, *Experiment B*, *Matching A/B*, *Incident switch*, *Config*. Filter by tag. |
| **Experiments** | **Station reach** (`max_station_distance_km`: control, `reach_5km`, `reach_30km`, metric `alternative_selected`) and **Matching: exact vs flexible** (`matching_strategy`: control, `flexible`, metric `match_accepted`). Both running. |
| **Identities** | `demo-5km`, `demo-15km`, `demo-30km`, `demo-exact`, `demo-flex`: pinned by identity override, so they stay outside the experiments. |
| **Segments** | `urgent_travellers` (`travels_within_48h = true`) with its `tatkal_level = 0` override. |
| **Audit Log** | Records changes when the plan keeps it (empty on the free local plan). |

**How events reach the Experiments tab:** the app sends an *exposure* (`$flag_exposure`, with the variant key) when a flag really shaped
what a visitor saw, and a *conversion* (`alternative_selected`, `match_accepted`) when they act. They go through the SDK's buffered sender
to `/api/v1/events` and are stored in Flagsmith's own database. Visitors pinned by an identity override, manual demo overrides and
load-test traffic are never exposed. Switch off with `FLAGSMITH_EVENTS=0`; `FLAGSMITH_EVENTS_URL` overrides the destination.
Synthetic visitors carry `metadata.simulated = true`.

**Reading the results honestly:** Flagsmith reports a lift, a confidence interval and a "chance to win". The simulator's visitors behave
identically in every variant, so on simulated data those numbers are noise: ignore any "chance to win" you see there (the experiments are
named `[demo data]` for this reason). Results appear after you press refresh in the tab, or via
`POST /environments/<key>/experiments/<id>/results/refresh/`. Flagsmith needs at least 50 visitors and 5 conversions per variant before it
shows inference.

**Note on the control value:** `max_station_distance_km` is whatever its base value is in the dashboard (it was changed to 20 at some point);
the script reads it and never overwrites it. The demo identity `demo-15km` is pinned to 15 km explicitly.

**Clear experiment events:** `docker exec flagsmith_postgres psql -U postgres -d flagsmith -c "delete from experimentation_sdkexperimentationevent;"`

---

## 1. Install dependencies (when online)

```bash
cd api
.venv/Scripts/pip install -r requirements.txt
```

```bash
cd web
npm install
```

---

## 2. Configure the Flagsmith Dashboard (≈10 minutes)

Create a project called **GharChalo** (environments: `Development` and `Demo`).

### A. Create these 8 Features (exact names)

| Feature name | Type | Default value | Variations / Notes |
|---|---|---|---|
| `tatkal_level` | Remote config (number) | `0` | Experiment A ladder: `0`, `1`, `2`, `3` |
| `tatkal_config` | Remote config (JSON) | `{"cache_ttl_s":30,"poll_s_l0":30,"poll_s_l1":120}` | Live tuning for cache TTL & poll interval |
| `max_station_distance_km` | **Multivariate** | `15` (control, 34%) | Add variations `5` (33%) and `30` (33%) |
| `matching_strategy` | Multivariate *(optional)* | `exact` (50%) | Add variation `time_window` (50%) |
| `matching_config` | Remote config (JSON) | `{"time_window_min":120,"date_flex_days":1,"max_matches":8}` | Live tuning for flexible matching |
| `interaction_mode` | Remote config (string) | `voice` | Set to `text_only` for P1 Sarvam fallback |
| `route_fault_sbc_hyb` | Boolean (toggle) | **OFF** | P1 Incident 2: injects 500 on SBC ↔ HYB only |
| `sarvam_fault_mode` | Remote config (string) | `none` | P1 Incident 3: `none` \| `429` \| `timeout` \| `error` |

### B. Create the `urgent_travellers` Segment

1. Go to **Segments → Create Segment**, name it `urgent_travellers`.
2. Add rule: **`travels_within_48h` equals `true`** *(or `days_until_travel <= 2` so you can adjust the threshold live)*.
3. Open feature **`tatkal_level` → Segment Overrides** → add `urgent_travellers` with value **`0`**.

### C. Copy the Server-Side Key

1. Go to **Environment → Settings → Keys → Server-side Environment Keys**.
2. Create a key (starts with `ser.`).
3. Put it in `api/.env`:

```env
FLAGSMITH_SERVER_KEY=ser.your_key_here
FLAGSMITH_REFRESH_SECONDS=10
ALLOW_FLAG_OVERRIDE=0
DEMO_NOW=2026-11-25T10:00
```

> **Check it works:** start the API and open `http://localhost:8000/healthz`. It should return `"flagsmith": "flagsmith"`.

---

## 3. Optional: No-WiFi Stage Backup

Export your environment document once before the demo:

```bash
curl -H "x-environment-key: $FLAGSMITH_SERVER_KEY" \
  https://edge.api.flagsmith.com/api/v1/environment-document/ \
  -o api/flagsmith_env.json
```

If venue Wi-Fi drops, set `FLAGSMITH_OFFLINE_FILE=flagsmith_env.json` in `api/.env` and restart — every cohort and segment override still works locally.

---

## 4. Running the Live Demo (1:30–2:15 slot)

1. **Experiment B (cohorts):** Open three tabs side-by-side with `?as=demo-5km`, `?as=demo-15km`, `?as=demo-30km` (with identity overrides or trait segments in Flagsmith). Search **Bengaluru → Hyderabad, 27 Nov**: they see **1 / 2 / 3** nearby station options. Click **Choose this** on one and open `GET /experiments/summary` to show live selection & abandonment rates.
2. **Experiment A (Tatkal degradation + fairness):**
   - Set `tatkal_level` to **`3`** in Flagsmith. Within 10 seconds:
     - Search **30 Nov** (non-urgent): sees the Level 3 banner, `cached` badge on second search, and co-traveller matching paused.
     - Search **27 Nov** (urgent, within 48 h): `urgent_travellers` segment override keeps them at **Level 0** — live search and matching continue normally.
3. **P1 Incidents (if time):**
   - Toggle `route_fault_sbc_hyb` ON → SBC ↔ HYB returns 500 while Bengaluru → Chennai stays 200 → human turns it OFF.
   - Set `sarvam_fault_mode` to `429` → voice fails with 503 → human sets `interaction_mode` to `text_only` → Speak tab disables, typed search keeps working.
