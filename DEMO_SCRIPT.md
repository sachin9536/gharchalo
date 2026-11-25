# GharChalo: Demo Video Script

> Target: **~6 minutes** core (the roadmap's 5-minute flow plus the rollback). Optional extras at the end.
> Everything shown is simulated data; say so once at the start and the UI labels it everywhere.

---

## 0. Before you hit record (not on video, ~10 min)

**Terminals** (big font, dark theme, no secrets on screen; never open `.env`, `.env.local` or `credentials.txt` while recording):

```bash
# T1: API (no --reload while recording)
cd ~/festivehacks-2026/gharchalo/api && .venv/bin/uvicorn main:app --port 8000

# T2: web app
cd ~/festivehacks-2026/gharchalo/web && npm run dev                     # http://localhost:5173

# T3: Flagsmith (already running? `docker ps` shows gharchalo-flagsmith-*)
cd ~/festivehacks-2026/gharchalo
docker compose -f deploy/flagsmith/docker-compose.yml up -d
python3 deploy/flagsmith/bootstrap.py                                   # must end "Done", 0 changes on a re-run

# T4: cluster (minikube)
minikube status                                                         # Running
kubectl -n gharchalo get pods                                           # api, web, postgres, loadgen Running
deploy/release.sh status                                                # live 1.4.0, all 200
kubectl -n gharchalo port-forward svc/gharchalo-web 8080:80             # cluster copy of the app
```

**Flagsmith dashboard (http://localhost:8090), reset these values:**

| Flag | Value for the start |
|---|---|
| `tatkal_level` | `0` |
| `interaction_mode` | `voice` |
| `sarvam_fault_mode` | `none` |
| `route_fault_sbc_hyb` | off |
| `tatkal_countdown` (environment) | off |

**Browser tabs, in this order:**
1. http://localhost:5173 (main app)
2. http://localhost:5173/?as=demo-5km · 3. `?as=demo-15km` · 4. `?as=demo-30km`
5. http://localhost:5173/?as=demo-beta
6. http://localhost:8090 (Flagsmith, logged in, project GharChalo › Development › Features)
7. http://localhost:8080 (the cluster copy)
8. NudgeBee dashboard (your friend's account, cluster visible)

**Sanity check:** in tab 1 say the demo sentence once; if Sarvam is slow or your network blocks it, use **"No microphone? Try an example"**.
Record a **backup clip** of the voice scene in case the live mic fails.

---

## Scene 1: The problem (0:00–0:20)

Tab 1, the welcome screen.
> "Every Diwali and Chhath, Tatkal tickets sell out in minutes and people still need to get home. GharChalo finds every way home:
> trains, buses, nearby stations, journeys with changes, and shared cabs. All data here is simulated."

---

## Scene 2: Voice in Hindi (Sarvam) (0:20–1:20)

Tab 1 → **Speak** → tap the mic → say:
**"Mujhe 27 November ko Bangalore se Hyderabad jaana hai. Train nahi mili toh shared cab dekhna."**

Show, in order:
1. The steps strip: Listen → Understand → Find options.
2. **We understood**: Hindi transcript, `Bengaluru (SBC)` heard as "बैंगलोर", date, "Train, then shared cab".
3. The **spoken reply** plays automatically in Hindi (Sarvam Bulbul). Point at the EN / हिं toggle.
> "Sarvam turns Hinglish speech into a structured journey. Station codes come from our alias table, never from the model.
> And it answers back in the traveller's language."

---

## Scene 3: Finding a way home (1:20–2:30)

Still tab 1, scroll the results.
1. **Guide line**: "No direct train or bus has seats…" (all SBC trains waitlisted).
2. **Waitlist chance** chips: `WL 118 · ~26% may confirm`, `WL 46 · ~40%` (hover: "rough estimate, simulated").
3. **Nearby dates** strip: Fri 27 sold out, Sat 28 has seats from ₹345. (Don't click yet.)
4. Tab **📍 Nearby stations**: trains with seats from Cantonment (3.7 km) and Baiyappanahalli (11.3 km).
5. Tab **🚕 Shared cab**: co-travellers with what each costs (km from your station, a day later…), **Share a cab** button.
6. Type → **Bengaluru → Jaipur** (popular route): **journeys with changes** appear automatically, open one: the coloured timeline (train → shared cab).
> "When trains are full we look at nearby stations, other days, connections and co-travellers, and we check the timing of every change."

---

## Scene 4: Flagsmith, the control plane (2:30–4:00)

**4a. Experiment B, live cohorts (30 s).** Tabs 2–4 side by side, each searching Bengaluru → Hyderabad, 27 Nov:
`demo-5km` sees 1 nearby station, `demo-15km` 2, `demo-30km` 3.
> "Flagsmith assigns each traveller a cohort: how far we look for another station."

**4b. Experiment A, fair degradation (45 s).** Tab 6 → `tatkal_level` → **3** → save. Back in tab 1 search **30 Nov** (~10 s):
banner "Peak Tatkal load (Level 3)", `cached` tag, co-traveller matching paused, Read aloud paused.
Now search **27 Nov** (within 48 h): normal service, no banner.
> "Under Tatkal load we degrade step by step, but people travelling within 48 hours keep full service: that's the urgent_travellers segment."
Set `tatkal_level` back to **0**.

**4c. Gradual release (30 s).** Tab 5 (`demo-beta`): the **⏰ Tatkal countdown** card. Tab 1: likely no card (25% rollout).
Tab 6 → `tatkal_countdown` → turn **ON** for the environment → tab 1 shows it within ~10 s → turn it **off**.
> "A new feature goes to a sticky 25% of travellers who travel this week, then to everyone with one switch, and off again instantly."

**4d. Experiments (15 s).** Tab 6 → **Experiments**: "Station reach" and "Matching: exact vs flexible" running.
Tab 1 header → **Experiments** page.
> "Every exposure and conversion is recorded. These runs use synthetic visitors, so we show the pipeline, not a winner."

---

## Scene 5: A bad release and NudgeBee rollback (4:00–5:40)

**5a. Healthy (10 s).** T4: `deploy/release.sh status` → live **1.4.0**, all 200. Tab 7 (cluster app) search Bengaluru → Hyderabad: works.

**5b. Ship the bad release (20 s).**
```bash
deploy/release.sh v2
deploy/release.sh status        # SBC -> HYB 500, HYB -> SBC 500, SBC -> NDLS 200
```
Tab 7: Bengaluru → Hyderabad now shows **Search failed**; Bengaluru → Delhi still works.
> "Release 1.5.0 ships express surge pricing. The load generator keeps traffic flowing, and one corridor starts failing."

**5c. NudgeBee investigates (40 s).** Tab 8 → NuBi: **"Why is gharchalo-api returning 500 errors?"**
Show its findings: pod logs with `ZeroDivisionError … express_surge_pricing (release 1.5.0)`, and the rollout history
(`1.5.0: Express surge pricing`, deployed minutes ago, errors since). Approve the **rollback** it proposes.
*(If NuBi does not offer a rollback button, run `kubectl -n gharchalo rollout undo deployment/gharchalo-api` on camera as the approved action.)*

**5d. Recovered (20 s).**
```bash
deploy/release.sh reconcile     # make Helm agree, so the next deploy can't bring 1.5.0 back
deploy/release.sh status        # live 1.4.0, all 200
```
Tab 7: Bengaluru → Hyderabad works again.
> "NudgeBee tied the errors to the release, a human approved the rollback, and we reconcile Helm so the bug can't come back."

---

## Scene 6: Close (5:40–6:00)

> "Sarvam lets people speak in their language. Flagsmith controls experiments, fair degradation and releases without deploys.
> NudgeBee finds what broke and rolls it back. Everything you saw is simulated data on our own laptop cluster."

---

## Optional extras (record separately if time allows)

| Extra | How |
|---|---|
| Sarvam outage drill | Flagsmith `sarvam_fault_mode` = `429` → voice fails → set `interaction_mode` = `text_only` → Speak tab disabled, typed search works → reset both |
| Matching benchmark | Experiments page → "Matching benchmark" table; change `matching_config.flex_pickup_km` to 30 in Flagsmith → Bidadi finds co-travellers |
| Share links | Copy link / WhatsApp buttons in the route bar |
| Load under Tatkal | `deploy/storm/run.sh --peak-rps 40` → summary table (simulated load) |

## Things not to claim on video

- That a variant "won" an experiment (synthetic visitors behave identically).
- Real IRCTC availability, real fares or real traffic numbers.
- That NudgeBee rolled back on its own, unless it actually did in the recording; it is human-approved.
- The memory (OOM) incident: built, but not yet recorded end to end.

## After recording

Reset Flagsmith values (table in section 0), `deploy/release.sh status` shows 1.4.0, stop the port-forward (Ctrl+C).
