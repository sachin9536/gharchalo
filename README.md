# GharChalo

Voice → transcript → journey JSON (Sarvam), then search/match/Flagsmith/k6/NudgeBee per
`../GharChalo_Hackathon_Roadmap.pdf`.

## Quick start (Docker, one command)

```bash
cp api/.env.example api/.env    # optional: add SARVAM_API_KEY for voice (typed search works without it)
docker compose up --build       # Postgres + seed + API + web
# open http://localhost:8080
```

**Voice answers 502 behind a corporate proxy?** Run `deploy/trust-corporate-ca.sh` once, then `docker compose up -d --build` (details in `CONTEXT.md`).

`docker compose down` stops it; `docker compose down -v` also wipes the database. Restarts never reseed
(`seed.py --if-empty`). Use another port with `WEB_PORT=9090 docker compose up`.

## Kubernetes (kind / minikube / Docker Desktop)

```bash
deploy/k8s-up.sh                 # builds images, loads them into the local cluster, installs the Helm chart
kubectl -n gharchalo port-forward svc/gharchalo-web 8080:80     # -> http://localhost:8080
deploy/k8s-down.sh               # remove everything
```

The script picks up `SARVAM_API_KEY` from `api/.env` and stores it as a Kubernetes Secret. It refuses
to run against a non-local cluster. No cluster yet? `brew install kind` (the script then creates one)
or `minikube start`. Chart: `deploy/helm/gharchalo` (values documented in `values.yaml`; incident knobs:
`api.resources.limits.memory`, `api.dbPool.size` / `maxOverflow`).

## Run for development (hot reload)

```bash
# API (Python 3.11+; this machine uses 3.14)
cd api
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # then paste SARVAM_API_KEY
.venv/bin/python scripts/smoke_sarvam.py [clip.wav]   # verify the key + model names first
.venv/bin/uvicorn main:app --reload --port 8000
.venv/bin/python -m pytest -q   # no key needed (Sarvam is mocked)

# Web
cd web && npm install && npm run dev      # http://localhost:5173, proxies /api -> :8000
```

## Voice flow (what exists)

`web` records → converts to 16 kHz mono WAV in the browser → `POST /api/voice` →
`sarvam.transcribe` → `sarvam.extract_journey` (city words + ISO date only) →
`journey.build_journey` maps cities to station codes through `stations.py` aliases.

| Endpoint | Purpose |
|---|---|
| `POST /voice` | audio → `{transcript, language_code, journey, source}` |
| `POST /journey/parse` | `{text}` → same shape (used after the user fixes the transcript) |
| `GET /search?origin=SBC&dest=HYB&date=2026-11-27&max_station_distance_km=15` | trains + buses from the preferred station; nearby-station train alternatives when it has no seats; shared-cab fare estimate. Add `include_connections=true`, or have no direct seats, to also get multi-leg journeys (train/bus/shared cab, `api/connections.py`; timing rules in its docstring). Always `source: "simulated"` |
| `GET /stations` | each city's main station (typed-search form) |
| `GET /healthz` | liveness, and whether a Sarvam key is configured |

Data: `python seed.py` drops and refills the database (SQLite via `DATABASE_URL=sqlite:///gharchalo.db`,
or Postgres, the default). Deterministic; see the docstring in `api/seed.py` for the scripted
Bengaluru → Hyderabad demo on 27 Nov 2026.

`X-Load-Test: 1` on `/voice` returns a canned journey after ~0.8 s and never calls Sarvam.
Sarvam failures map to 502; a Sarvam 429 maps to 503.

## Handoff points

- **B:** replace `STATIONS` in `api/stations.py` with the `stations` table (keep `resolve()`);
  add trains/matches to `VoiceResponse` in `api/main.py` and show them in `web/src/App.tsx`.
- **C:** `/healthz` exists; `/metrics` does not yet.
