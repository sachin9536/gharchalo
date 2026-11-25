import { useEffect, useState } from 'react'
import { fetchDateStrip, type DateStrip as Strip, type SearchQuery } from './api'
import { chipDate, inr } from './format'

type Outcome = { key: string; data?: Strip; error?: string }

/** Direct availability on the days around the search; tap a day to search it instead. */
export default function DateStrip({ query, onPick }: { query: SearchQuery; onPick: (date: string) => void }) {
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const key = `${query.origin}|${query.dest}|${query.date}`
  const strip = outcome?.key === key ? outcome.data : undefined

  useEffect(() => {
    const controller = new AbortController()
    fetchDateStrip(query, controller.signal)
      .then((data) => setOutcome({ key, data }))
      .catch((e) => {
        if (e instanceof DOMException && e.name === 'AbortError') return
        setOutcome({ key, error: e instanceof Error ? e.message : String(e) })
      })
    return () => controller.abort()
  }, [key, query])

  if (!strip) return null // optional extra: the results work without it

  return (
    <div className="datestrip" aria-label="Seats on nearby dates">
      <span className="muted small datestrip-label">Direct from {strip.origin.name}, nearby days</span>
      <div className="datestrip-days">
        {strip.days.map((d) => {
          const current = d.date === query.date
          const state = d.options === 0 ? 'none' : d.with_seats === 0 ? 'full' : 'free'
          return (
            <button
              key={d.date}
              className={`day ${state} ${current ? 'on' : ''}`}
              disabled={d.options === 0 || current}
              aria-current={current ? 'date' : undefined}
              onClick={() => onPick(d.date)}
              title={
                d.options === 0
                  ? 'No services in the demo data'
                  : `${d.trains_with_seats} train(s) and ${d.buses_with_seats} bus(es) with seats`
              }
            >
              <strong>{chipDate(d.date)}</strong>
              <span>
                {state === 'none' ? 'no data' : state === 'full' ? 'sold out' : `${d.with_seats} with seats`}
              </span>
              {d.cheapest_with_seats !== null && <span className="muted">from {inr(d.cheapest_with_seats)}</span>}
            </button>
          )
        })}
      </div>
    </div>
  )
}
