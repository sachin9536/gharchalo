# Flagsmith Setup & Live Demo Guide

All Flagsmith code is already wired in the backend (`api/flags.py`, `api/main.py`, `api/cache.py`, `api/metrics.py`) and frontend (`web/src/`). Follow these steps to connect it to your Flagsmith project.

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
