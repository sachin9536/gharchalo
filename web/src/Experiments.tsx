import { useEffect, useState } from 'react'
import { fetchExperiments, fetchMatchingBenchmark, type ExperimentsSummary, type ExperimentVisitors, type MatchingBenchmark } from './api'
import { inr } from './format'
import { MIN_PER_GROUP, percent, verdict, wilson, type Verdict } from './stats'

const TABS: { id: ExperimentVisitors; label: string }[] = [
  { id: 'live', label: 'Real visitors' },
  { id: 'simulated', label: 'Simulated visitors' },
  { id: 'all', label: 'Both combined' },
]

type Outcome = { key: string; data?: ExperimentsSummary; error?: string }

/** A rate with its 95% confidence range, drawn as a bar so small samples look uncertain. */
function RateBar({ successes, n }: { successes: number; n: number }) {
  if (n === 0) return <span className="muted">no data</span>
  const rate = successes / n
  const ci = wilson(successes, n)
  return (
    <div className="ratebar" title={`${successes} of ${n}`}>
      <div className="ratebar-track">
        {ci && <div className="ratebar-ci" style={{ left: `${ci[0] * 100}%`, width: `${(ci[1] - ci[0]) * 100}%` }} />}
        <div className="ratebar-dot" style={{ left: `${rate * 100}%` }} />
      </div>
      <span>
        <strong>{percent(rate)}</strong>
        {ci && (
          <span className="muted small">
            {' '}
            ({percent(ci[0])}–{percent(ci[1])})
          </span>
        )}
      </span>
    </div>
  )
}

function VerdictChip({ v }: { v: Verdict }) {
  return <span className={`verdict ${v.kind}`}>{v.text}</span>
}

const successes = (rate: number | null, n: number) => (rate === null ? 0 : Math.round(rate * n))

export default function Experiments() {
  const [visitors, setVisitors] = useState<ExperimentVisitors>('live')
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [tick, setTick] = useState(0)
  const [bench, setBench] = useState<MatchingBenchmark | null>(null)

  const key = `${visitors}|${tick}`
  const data = outcome?.key === key ? outcome.data : undefined
  const error = outcome?.key === key ? outcome.error : undefined
  // Keep showing the previous numbers while a refresh is in flight.
  const shown = data ?? outcome?.data

  useEffect(() => {
    const controller = new AbortController()
    fetchExperiments(visitors, controller.signal)
      .then((d) => setOutcome({ key, data: d }))
      .catch((e) => {
        if (e instanceof DOMException && e.name === 'AbortError') return
        setOutcome({ key, error: e instanceof Error ? e.message : String(e) })
      })
    return () => controller.abort()
  }, [visitors, tick, key])

  useEffect(() => {
    const controller = new AbortController()
    fetchMatchingBenchmark(controller.signal)
      .then(setBench)
      .catch(() => {
        // the benchmark is optional; the rest of the page still works
      })
    return () => controller.abort()
  }, [tick])

  useEffect(() => {
    const timer = window.setInterval(() => setTick((t) => t + 1), 10_000)
    return () => window.clearInterval(timer)
  }, [])

  const control = shown?.station_distance.find((c) => c.cohort_km === 15)
  const exact = shown?.matching.find((m) => m.strategy === 'exact')
  const flexible = shown?.matching.find((m) => m.strategy === 'time_window')
  const pop = shown?.population

  return (
    <div className="exp">
      <h2 className="exp-title">Experiments</h2>
      <p className="muted">
        Three Flagsmith experiments, read live from the app. Trains, buses and fares are always simulated; this page is about
        who saw which variant and what they did.
      </p>

      <div className="segmented exp-tabs" role="tablist" aria-label="Which visitors">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={visitors === t.id} className={visitors === t.id ? 'on' : ''} onClick={() => setVisitors(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {visitors === 'simulated' && (
        <p className="banner warn">
          <strong>Synthetic visitors.</strong> They choose identically in every variant, so any difference below is noise. This
          view proves the pipeline works at volume. It says nothing about what real travellers prefer.
        </p>
      )}
      {visitors === 'all' && (
        <p className="banner warn">
          Real and synthetic visitors are blended here. Use it to check totals, not to draw conclusions.
        </p>
      )}
      {error && <p className="error">Could not load the experiments: {error}</p>}
      {!shown && !error && <p className="working">Loading…</p>}

      {shown && pop && (
        <p className="muted small">
          Recorded so far: {pop.search_events.live} real and {pop.search_events.simulated} simulated searches;{' '}
          {pop.match_events.live} real and {pop.match_events.simulated} simulated match offers. Refreshes every 10 s.
        </p>
      )}

      {shown && (
        <>
          <section className="card">
            <div className="card-head">
              <h2>Experiment B: how far to look for another station</h2>
              <span className="tag soft">5 / 15 / 30 km cohorts</span>
            </div>
            <p className="muted small">
              Each visitor is assigned a cohort by Flagsmith (15 km is the control). We measure how many who were shown
              alternatives picked one.
            </p>
            {shown.station_distance.length === 0 ? (
              <p className="muted">No searches with nearby-station alternatives recorded for these visitors yet.</p>
            ) : (
              <div className="tablewrap">
                <table className="exp-table">
                  <thead>
                    <tr>
                      <th>Cohort</th>
                      <th>Saw alternatives</th>
                      <th>Picked one (95% range)</th>
                      <th>Avg extra distance</th>
                      <th>Versus the 15 km control</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.station_distance.map((c) => {
                      const n = c.searches_with_alternatives
                      const x = successes(c.selection_rate, n)
                      return (
                        <tr key={c.cohort_km}>
                          <td>
                            <strong>{c.cohort_km} km</strong>
                          </td>
                          <td>{n}</td>
                          <td>
                            <RateBar successes={x} n={n} />
                          </td>
                          <td>{c.avg_extra_km !== null ? `${c.avg_extra_km} km` : '–'}</td>
                          <td>
                            {c.cohort_km === 15 || !control ? (
                              <span className="muted">control</span>
                            ) : (
                              <VerdictChip
                                v={verdict(x, n, successes(control.selection_rate, control.searches_with_alternatives), control.searches_with_alternatives)}
                              />
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Matching: exact vs flexible</h2>
              <span className="tag soft">optional A/B</span>
            </div>
            <p className="muted small">
              <strong>Exact</strong> means your pickup station, your day and an overlapping time window.{' '}
              <strong>Flexible</strong> also accepts nearby pickup stations, a day either side and a wider time window. Every
              offer records what it cost the visitor (distance, days, time) and whether the group was accepted.
            </p>
            {shown.matching.length === 0 ? (
              <p className="muted">No co-traveller offers recorded for these visitors yet.</p>
            ) : (
              <div className="tablewrap">
                <table className="exp-table">
                  <thead>
                    <tr>
                      <th>Strategy</th>
                      <th>Offers with matches</th>
                      <th>Avg co-travellers</th>
                      <th>Avg pickup distance</th>
                      <th>Avg days off</th>
                      <th>Accepted (95% range)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.matching.map((m) => (
                      <tr key={m.strategy}>
                        <td>
                          <strong>{m.strategy === 'time_window' ? 'flexible' : m.strategy}</strong>
                        </td>
                        <td>{m.offers_with_matches}</td>
                        <td>{m.avg_matches_offered ?? '–'}</td>
                        <td>{m.avg_pickup_km !== null ? `${m.avg_pickup_km} km` : '–'}</td>
                        <td>{m.avg_day_shift ?? '–'}</td>
                        <td>
                          <RateBar successes={m.accepted} n={m.offers_with_matches} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {shown.matching_legacy_offers_excluded > 0 && (
              <p className="muted small">
                {shown.matching_legacy_offers_excluded} earlier offers made under the old matching rules are not counted here,
                so two different rule-sets are never blended.
              </p>
            )}
            {exact && flexible && (
              <p>
                Exact vs flexible:{' '}
                <VerdictChip v={verdict(exact.accepted, exact.offers_with_matches, flexible.accepted, flexible.offers_with_matches)} />
              </p>
            )}
          </section>

          {bench && (
            <section className="card">
              <div className="card-head">
                <h2>Matching benchmark: what flexibility finds, and what it costs</h2>
                <span className="tag soft">deterministic</span>
              </div>
              <p className="muted small">
                The same {bench.summary.scenarios} requests ({bench.route}) go through both strategies. Flexible reaches{' '}
                <strong>{bench.config.flex_pickup_km} km</strong>, <strong>±{bench.config.date_flex_days} day</strong> and{' '}
                <strong>±{bench.config.time_window_min} min</strong>, read live from Flagsmith's <code>matching_config</code>: change it
                there and this table follows. The traveller pool is synthetic, so the size of the numbers depends on how it was
                seeded; they describe the algorithm, not real travellers.
              </p>
              <div className="tablewrap">
                <table className="exp-table">
                  <thead>
                    <tr>
                      <th>Request</th>
                      <th>Exact finds</th>
                      <th>Flexible finds</th>
                      <th>Pickup away</th>
                      <th>Days off</th>
                      <th>Time apart</th>
                      <th>Cab fare each</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bench.scenarios.map((r) => (
                      <tr key={r.name}>
                        <td>
                          {r.name}
                          <div className="muted small">
                            {r.pickup.code} · {r.window}
                          </div>
                        </td>
                        <td>
                          <strong className={r.exact.found === 0 ? 'bad' : undefined}>{r.exact.found}</strong>
                        </td>
                        <td>
                          <strong className={r.flexible.found === 0 ? 'bad' : undefined}>{r.flexible.found}</strong>
                        </td>
                        <td>{r.flexible.avg_pickup_km !== null ? `${r.flexible.avg_pickup_km} km` : '–'}</td>
                        <td>{r.flexible.avg_day_shift ?? '–'}</td>
                        <td>{r.flexible.avg_time_gap_min !== null ? `${r.flexible.avg_time_gap_min} min` : '–'}</td>
                        <td>
                          {inr(r.exact.fare_each)} → <strong>{inr(r.flexible.fare_each)}</strong>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p>
                Across these requests flexible found <strong>{bench.summary.found_by_flexible}</strong> co-travellers against{' '}
                <strong>{bench.summary.found_by_exact}</strong> for exact, and rescued <strong>{bench.summary.rescued}</strong>{' '}
                request{bench.summary.rescued === 1 ? '' : 's'} where exact found nobody
                {bench.summary.still_empty > 0 && <> ({bench.summary.still_empty} stayed empty: nobody within reach)</>}. The{' '}
                {bench.summary.extra_matches} extra matches were on average{' '}
                <strong>{bench.summary.extra_avg_pickup_km} km</strong> away, <strong>{bench.summary.extra_avg_day_shift} days</strong>{' '}
                off and <strong>{bench.summary.extra_avg_time_gap_min} min</strong> apart.
                {bench.summary.avg_fare_saving_each !== null && (
                  <> A bigger group saved about {inr(bench.summary.avg_fare_saving_each)} each against a smaller one (or riding alone).</>
                )}
              </p>
            </section>
          )}

          <section className="card">
            <div className="card-head">
              <h2>Experiment A: Tatkal degradation</h2>
              <span className="tag soft">level {shown.degradation.current_level} now</span>
            </div>
            <p className="muted small">
              Flagsmith's <code>tatkal_level</code> trades freshness for capacity. Travellers within 48 hours stay at level 0.
            </p>
            <div className="shares">
              <div className="share">
                <strong>{shown.degradation.searches_live}</strong>
                <span className="muted small">live searches</span>
              </div>
              <div className="share">
                <strong>{shown.degradation.searches_cache}</strong>
                <span className="muted small">served from cache</span>
              </div>
              <div className="share">
                <strong>{percent(shown.degradation.cache_share)}</strong>
                <span className="muted small">cache share</span>
              </div>
              <div className="share">
                <strong>
                  {shown.degradation.matches_served} / {shown.degradation.matches_paused}
                </strong>
                <span className="muted small">matches served / paused</span>
              </div>
            </div>
            <p className="muted small">{shown.degradation.note}</p>
          </section>

          <section className="card">
            <h2>Reading these numbers</h2>
            <ul className="exp-notes">
              <li>
                The bar shows the observed rate, and the lighter band is the 95% range it could plausibly have. A wide band
                means the sample is small.
              </li>
              <li>
                Groups under {MIN_PER_GROUP} visitors are never called different. With few visitors, chance alone can make one
                group look far better.
              </li>
              <li>Flagsmith's own dashboard shows the audit log of every flag change, and per-flag evaluation charts.</li>
            </ul>
          </section>
        </>
      )}
    </div>
  )
}
