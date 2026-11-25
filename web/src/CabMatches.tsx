import { useEffect, useState } from 'react'
import { acceptMatch, postMatch, type MatchResponse, type Strategy } from './api'
import { span } from './format'
import { getUserId } from './user'

const WINDOWS = [
  { label: 'Morning', start: '05:00', end: '12:00' },
  { label: 'Afternoon', start: '12:00', end: '18:00' },
  { label: 'Evening', start: '18:00', end: '22:00' },
  { label: 'Night', start: '22:00', end: '23:59' },
]
const DEFAULT_WINDOW = 2 // Evening: the scripted demo

type Outcome = { key: string; data?: MatchResponse; error?: string }

const hhmm = (t: string) => t.slice(0, 5)

function shortDate(iso: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

export default function CabMatches({
  origin,
  dest,
  date,
  shares,
  allowOverride,
}: {
  origin: string
  dest: string
  date: string
  shares: { people: number; per_person: number }[]
  allowOverride?: boolean
}) {
  const [windowIdx, setWindowIdx] = useState(DEFAULT_WINDOW)
  // null = let Flagsmith's matching_strategy decide per user.
  const [strategyOverride, setStrategyOverride] = useState<Strategy | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [accepted, setAccepted] = useState<number | null>(null)
  const [acceptError, setAcceptError] = useState<string | null>(null)

  const key = `${origin}|${dest}|${date}|${windowIdx}|${strategyOverride ?? 'auto'}`
  const settled = outcome?.key === key ? outcome : null

  useEffect(() => {
    const controller = new AbortController()
    const w = WINDOWS[windowIdx]
    // Each response is logged as an "offer" for the experiment metrics. In dev,
    // React StrictMode runs this effect twice, so dev counts are inflated.
    postMatch(
      {
        user_id: getUserId(),
        origin,
        dest,
        date,
        window_start: w.start,
        window_end: w.end,
        ...(strategyOverride ? { strategy: strategyOverride } : {}),
      },
      controller.signal,
    )
      .then((data) => setOutcome({ key, data }))
      .catch((e) => {
        if (e instanceof DOMException && e.name === 'AbortError') return
        setOutcome({ key, error: e instanceof Error ? e.message : String(e) })
      })
    return () => controller.abort()
  }, [key, origin, dest, date, windowIdx, strategyOverride])

  const data = settled?.data
  const activeStrategy = strategyOverride ?? data?.strategy
  const perPerson = data ? shares.find((s) => s.people === data.suggested_group_size)?.per_person : undefined
  const isAccepted = data !== undefined && data.match_id !== null && accepted === data.match_id

  const accept = async () => {
    if (!data || data.match_id === null) return
    setAcceptError(null)
    try {
      await acceptMatch(data.match_id)
      setAccepted(data.match_id)
    } catch (e) {
      setAcceptError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="matches">
      <h3>
        Co-travellers going your way
        {data && !data.paused && (
          <span className="tag soft">{data.strategy === 'time_window' ? 'flexible match' : 'exact match'}</span>
        )}
      </h3>
      <div className="match-controls">
        <span className="muted small">Leaving</span>
        {WINDOWS.map((w, i) => (
          <button key={w.label} className={`km ${i === windowIdx ? 'on' : ''}`} onClick={() => setWindowIdx(i)}>
            {w.label}
          </button>
        ))}
      </div>
      {allowOverride && (
        <div className="match-controls">
          <span className="muted small">Match</span>
          {(['exact', 'time_window'] as const).map((s) => (
            <button
              key={s}
              className={`km ${s === activeStrategy ? 'on' : ''}`}
              onClick={() => setStrategyOverride(s)}
            >
              {s === 'exact' ? 'Exact: your station, same day' : 'Flexible: nearby stations, ±1 day'}
            </button>
          ))}
          {strategyOverride && (
            <button className="link small" onClick={() => setStrategyOverride(null)}>
              Use Flagsmith
            </button>
          )}
        </div>
      )}

      {!settled && <p className="muted">Looking for co-travellers…</p>}
      {settled?.error && <p className="error">Matching failed: {settled.error}</p>}

      {data?.paused && (
        <p className="warn">
          Co-traveller matching is paused during peak Tatkal load (Level 3) to protect train search. Please try again in{' '}
          {data.retry_after_s ?? 60} seconds.
        </p>
      )}

      {data && !data.paused && data.matches.length === 0 && (
        <p className="muted">No co-travellers for this window yet. Try another time window.</p>
      )}

      {data && !data.paused && data.matches.length > 0 && (
        <>
          <p>
            <strong>{data.offered}</strong> co-traveller{data.offered > 1 ? 's' : ''} found.
            {perPerson !== undefined && (
              <>
                {' '}
                A cab for {data.suggested_group_size} is about <strong>₹{perPerson.toLocaleString('en-IN')}</strong> each.
              </>
            )}
          </p>
          <ul className="options">
            {data.matches.map((m) => (
              <li key={m.traveller_id} className="option">
                <span className="avatar" aria-hidden="true">
                  {m.name.charAt(0)}
                </span>
                <div className="option-main">
                  <strong>{m.name}</strong>
                  <div className="muted small">
                    {m.pickup.name} → {m.drop.name}
                  </div>
                  <div className="fit">
                    {m.shift === 'exact' ? (
                      <span className="chip ok">exact fit</span>
                    ) : (
                      <>
                        {m.pickup_km > 0 && <span className="chip dist">{m.pickup_km} km from your station</span>}
                        {m.day_shift !== 0 && (
                          <span className="chip dist">
                            {m.day_shift > 0 ? `${m.day_shift} day later` : `${-m.day_shift} day earlier`}
                          </span>
                        )}
                        {m.time_gap_min > 0 && <span className="chip dist">{span(m.time_gap_min)} apart</span>}
                      </>
                    )}
                  </div>
                </div>
                <div className="option-side muted small">
                  {m.date !== date && <div>{shortDate(m.date)}</div>}
                  {hhmm(m.window_start)}–{hhmm(m.window_end)}
                </div>
              </li>
            ))}
          </ul>
          {isAccepted ? (
            <p className="ok-note">Group request sent. They'll be told you're coming.</p>
          ) : (
            <button className="primary" onClick={() => void accept()}>
              Share a cab with {data.suggested_group_size > 1 ? `${data.suggested_group_size - 1} of them` : 'them'}
            </button>
          )}
          {acceptError && <p className="error">{acceptError}</p>}
          <p className="muted small">Simulated travellers. Nobody is actually notified.</p>
        </>
      )}
    </div>
  )
}
