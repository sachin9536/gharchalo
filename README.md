# GharChalo 🪔 — every way home this festive season

> **Speak your journey in Hindi, Hinglish or English. GharChalo finds every way home — even when every train says "waitlisted".**
>
> Built for **FestiveHacks 2026** with **Sarvam AI**, **Flagsmith** and **NudgeBee**.

---

## The problem: the busiest journey of the year breaks at 10:00 AM

Every Diwali, Chhath and Pongal, millions of students and workers try to go home at the same time. For most of them the
journey starts with the same three minutes of panic:

- **Tatkal booking opens the day before travel, and seats sell out within minutes.** What is left is a red "WL 118" and no idea
  whether it will ever confirm.
- **The answer is often one step away, but nobody shows it.** A train with free seats may leave from a station 10 km away. There
  may be seats tomorrow, or a train-plus-bus route through another city. Three strangers may be making the exact same trip and
  could share a cab for a quarter of the price.
- **Booking tools assume you can read English and fill in dense forms.** Many of the people travelling home would much rather
  just *say* where they want to go, in their own language.
- **The systems themselves buckle.** The 10:00 AM spike is the moment a travel service is most needed and most likely to fail,
  and a bad release on that morning strands people who had no other way to plan.

GharChalo tackles all four: **one conversation instead of ten searches, every alternative instead of a dead end, your language
instead of a form, and an app engineered to stay up — and recover fast — during the rush.**

---

## What GharChalo does

A traveller taps the mic and says:

> *"Mujhe 27 November ko Bangalore se Hyderabad jaana hai. Train nahi mili toh shared cab dekhna."*
> ("I need to go from Bangalore to Hyderabad on 27 November. If there's no train, look for a shared cab.")

GharChalo understands the request, searches everything, and **reads the best option back in Hindi**:

| | What the traveller sees |
|---|---|
| 🎙 **Understood** | Bengaluru (KSR) → Hyderabad, Fri 27 Nov, "train, then shared cab" — with the transcript to fix if it misheard |
| 🚆 **Trains & buses** | Every option from their station, sortable, filterable, with **Cheapest / Fastest** badges |
| 📊 **Waitlist chance** | `WL 46 · ~40% may confirm` — a clear estimate instead of a bare number |
| 📍 **Nearby stations** | "No seats from KSR, but a train **with seats** leaves Bengaluru Cantonment, 3.7 km away" |
| 📅 **Nearby dates** | Fri 27 sold out · **Sat 28: 3 options with seats from ₹345** — one tap to switch |
| 🔀 **Journeys with changes** | When nothing runs direct (e.g. Bengaluru → Jaipur): train to Kota + shared cab, with every connection's timing checked |
| 🚕 **Shared cab** | Co-travellers going the same way, what each match costs you (km from your station, a day earlier, an hour later) and the fare split |
| ⏰ **Tatkal countdown** | "Tatkal for this journey opens in 14h 22m" + a calendar reminder |
| 🔊 **Spoken reply** | The quickest way home, read aloud in Hindi or English |
| ⚡ **Quick picks** | "Quickest way home", "Cheapest with seats", "Split a cab" — the decision in three cards |

It also works without a microphone: a typed search with one-tap dates, popular routes, recent searches and shareable links
(WhatsApp / copy link).

---

## Engineered for Tatkal hour

The product is only half the story. The other half is **staying useful when everyone hits it at once**, and **recovering in
minutes when something breaks**.

### 1. Fair degradation, controlled live (Flagsmith)

A single remote-config value, `tatkal_level`, moves the whole system down a ladder as load rises — **without a deploy**:

| Level | What changes | Protects |
|---|---|---|
| 0 | Normal service | — |
| 1 | Results refresh every 120 s instead of 30 s | Request volume |
| 2 | Multi-leg planning and spoken replies pause | CPU and Sarvam quota |
| 3 | Search served from a 30-second cache; co-traveller matching pauses | The database |

**The fairness rule:** travellers whose journey is within 48 hours fall into the `urgent_travellers` segment and **always keep
level 0**. When capacity is scarce, the person travelling tomorrow is served first — not whoever refreshes fastest.

### 2. Experiments that answer real product questions (Flagsmith)

- **How far should we look for another station?** Travellers get a sticky cohort — 5, 15 or 30 km — and we measure how many
  choose an alternative station.
- **Exact or flexible matching?** Exact = your station, your day, overlapping time; flexible = nearby stations, a day either side,
  a wider window. We measure how many accept a cab group, and record what flexibility cost them.

Both run as native **Flagsmith experiments** (exposure + conversion events), and GharChalo's own **Experiments page** shows sample
sizes, 95% confidence ranges and a plain-language verdict — refusing to call a winner below 30 visitors per group.

### 3. Safe releases (Flagsmith)

New features ship dark and roll out gradually. The Tatkal countdown is released to **a sticky 25% of travellers who travel in the
next 1–7 days**; one switch releases it to everyone, and switching it off is an instant kill switch.

### 4. A bad release, diagnosed and rolled back (NudgeBee)

We ship release **1.5.0 "Express surge pricing"** with a realistic bug: the new festival corridor's capacity was entered as 0, so
the price calculation divides by zero. **Only Bengaluru ↔ Hyderabad breaks** (HTTP 500, both directions); every other route stays
healthy — exactly the kind of partial outage that is hard to spot in a dashboard.

1. A continuous **k6 load generator** keeps realistic traffic flowing, so the errors appear the way they would on a Tatkal morning.
2. **NudgeBee's AI SRE** reads the pod logs (a genuine `ZeroDivisionError` traceback tagged `release 1.5.0`), the Kubernetes
   events and the rollout history (`1.5.0: Express surge pricing`, deployed minutes ago) and ties the failures to the release.
3. A **human approves the rollback**; the Deployment returns to `1.4.0`.
4. **`deploy/release.sh reconcile`** then brings Helm back in line — otherwise the next routine deploy would silently ship the
   bug again (and Helm 4 would refuse to upgrade at all). We found and fixed both traps while testing.

### 5. Graceful fallbacks (Flagsmith + Sarvam)

If Sarvam is rate-limited or down, one flag (`interaction_mode = text_only`) disables voice and spoken replies while typed search
keeps working. Simulated outage switches (`sarvam_fault_mode`, `route_fault_sbc_hyb`) let us drill this without burning quota.

---

## How each sponsor is used

### 🗣 Sarvam AI — talk to it in your language
- **Saaras speech-to-text** turns code-mixed Hinglish/Hindi into Devanagari text.
- **`sarvam-105b`** extracts origin, destination, date ("kal", "parso", dates without a year) and fallback preference as JSON.
  City words are mapped to station codes by our alias table — **the model never invents a station code**.
- **Bulbul text-to-speech** reads the answer back (Hindi / English), cached so repeats cost no quota.
- Load-test traffic never touches the real API; spoken replies pause under peak load.

### 🎛 Flagsmith — the live control plane
- 9 flags: the Tatkal ladder and its tuning, two experiments, matching thresholds as JSON, a release toggle, the text-only
  fallback and incident switches.
- Segments on identity traits (`travels_within_48h`, `days_until_travel`, `lang`), segment overrides, percentage splits.
- Local evaluation in the Python SDK: **zero network calls per request**, safe defaults, a 2-second fail-fast if Flagsmith is down.
- Native experiments fed by exposure/conversion events; flag analytics; demo identities pinned with identity overrides.
- A self-hosted Flagsmith configured **end to end by one idempotent script** — flags, segments, experiments, metrics, events
  warehouse, tags and descriptions, so the dashboard explains itself.

### 🐝 NudgeBee — the AI SRE on call
- Agent installed in the Kubernetes cluster, connected through NudgeBee's relay (no inbound access to the cluster needed).
- Investigates the bad-release incident from logs, events and rollout history; recommends the rollback; a human approves.
- Alert rules (5xx rate → Alertmanager → NudgeBee) and a planted memory-leak incident (OOMKilled under the Tatkal spike) are
  prepared for automatic detection.

---

## Architecture

```
Browser (React + TypeScript, Vite)
   │  /api/*   (Vite proxy in dev · nginx in Docker/Kubernetes)
   ▼
FastAPI ────────────────────────────────────────────────────────────────┐
 ├─ /voice, /journey/parse ──► Sarvam Saaras + sarvam-105b ─► aliases  │
 ├─ /speak ──────────────────► Sarvam Bulbul (cached)                   │
 ├─ /search, /search/dates ──► search · multi-leg planner · waitlist   │   Flagsmith (self-hosted)
 ├─ /match ──────────────────► exact / flexible co-traveller matching  │◄─ local evaluation,
 ├─ /config, /experiments/* ─► per-traveller flags, experiment read-outs│   exposure + conversion events
 └─ /metrics, /healthz ──────► Prometheus metrics, release identity    │
   ▼                                                                    │
PostgreSQL (or SQLite for quick dev)                                    │
                                                                        │
Kubernetes (minikube) ── Helm chart ── k6 load generator ── NudgeBee agent ──► NudgeBee (AI SRE)
```

---

## Run it

### Fastest: Docker (≈2 minutes)
```bash
git clone https://github.com/sachin9536/gharchalo && cd gharchalo
cp api/.env.example api/.env       # optional: add SARVAM_API_KEY for voice and spoken replies
docker compose up --build          # → http://localhost:8080
```
Typed search, results, matching and journeys with changes work without any key. Behind a corporate HTTPS proxy, run
`deploy/trust-corporate-ca.sh` once if voice answers 502 inside containers.

### Development (hot reload)
```bash
cd api
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                       # SARVAM_API_KEY; DATABASE_URL=sqlite:///gharchalo.db for quick dev
.venv/bin/python seed.py                   # loads the simulated data (drops existing tables)
.venv/bin/uvicorn main:app --reload --port 8000
.venv/bin/python -m pytest -q              # 180+ tests, no keys needed

cd ../web && npm install && npm run dev    # → http://localhost:5173
```

### Flagsmith (optional — the app runs on safe defaults without it)
```bash
docker compose -f deploy/flagsmith/docker-compose.yml up -d    # dashboard → http://localhost:8090
python3 deploy/flagsmith/bootstrap.py                          # creates everything; safe to re-run
```
Restart the API; `/healthz` then reports `"flagsmith": "flagsmith"`. Try `http://localhost:5173/?as=demo-5km` (and `demo-15km`,
`demo-30km`, `demo-exact`, `demo-flex`, `demo-beta`) to see each cohort side by side.

### Kubernetes, load and incidents
```bash
deploy/k8s-up.sh                              # build, load into minikube/kind, install the Helm chart (incl. k6 loadgen)
kubectl -n gharchalo port-forward svc/gharchalo-web 8080:80

deploy/release.sh v2                          # ship the buggy release 1.5.0
deploy/release.sh status                      # live vs Helm, rollout history, corridor check
deploy/release.sh reconcile                   # after a NudgeBee / kubectl rollback
deploy/release.sh rollback                    # human rollback to the previous release

deploy/storm/run.sh --peak-rps 40             # TatkalStorm traffic spike (in-cluster job)
deploy/incidents/incident.sh oom | fix        # planted memory-leak incident on / off
```

The full walkthrough of the demo is in [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md).

---

## Project at a glance

| | |
|---|---|
| **Product** | Voice + typed search · waitlist chance · nearby stations · nearby dates · journeys with changes · shared-cab matching · spoken replies · Tatkal countdown · share links · Experiments page |
| **Data** | 32 stations in 11 cities · 1,587 trains · 613 buses · 300 travellers · 26 Nov – 1 Dec 2026 · deterministic seed |
| **API** | 14 endpoints, Prometheus metrics, release identity on every response |
| **Quality** | 180+ backend tests; property tests check every journey with changes on all 110 city pairs |
| **Ops** | Docker Compose · Helm chart · k6 load generator · release switch with Helm reconcile · planted incidents · NudgeBee agent |

More detail: [`PROJECT_INVENTORY.md`](PROJECT_INVENTORY.md) (everything that exists, with status) · [`CONTEXT.md`](CONTEXT.md)
(how to run and the traps we hit) · [`FLAGSMITH_SETUP.md`](FLAGSMITH_SETUP.md) (every Flagsmith piece, step by step).

---

## Where it goes next

These ideas are designed but **not built yet** (or not yet verified end to end):

- **Settle-up for shared cabs** — record who paid and split the bill via UPI.
- **Seat alerts** — watch a sold-out train and get notified when seats or a Tatkal window open.
- **Automatic incident detection everywhere** — Prometheus + Alertmanager on every cluster, so a 5xx spike pages NudgeBee
  without anyone asking (alert rules are written; today the investigation is started by asking NudgeBee).
- **Recorded OOM diagnosis** — the memory-leak incident is built; capturing NudgeBee's root-cause analysis of it is next.
- **Interface in more languages** — the app already listens and speaks in Hindi; its screens are next.
- **Real availability** — partnering with authorised data providers instead of simulated data.

---

## Honest by design

- **Indian Railways offers no public availability API and scraping IRCTC is not allowed**, so every train, bus, fare and
  traveller here is realistic **simulated** data, and the app says so on every screen.
- Load figures come from **our own laptop cluster**, never presented as real railway traffic.
- Experiment results from synthetic visitors are labelled as such — we show the pipeline, never a fake winner.
- Faults are planted deliberately, reversible, and rolled back with human approval.

---

<p align="center"><b>The product helps people get home. The engineering makes sure it still works on the morning they need it most.</b></p>
