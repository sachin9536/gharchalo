import type { Itinerary, Leg, SearchResponse } from './api'
import { MODE_LABEL, dayStamp, inr, span, via } from './format'

function LegRow({ leg }: { leg: Leg }) {
  return (
    <li className="leg">
      {leg.wait_before_minutes > 0 && (
        <div className="wait">
          Wait {span(leg.wait_before_minutes)} at {leg.origin.name}
          {leg.change_note && <div className="small">{leg.change_note}</div>}
        </div>
      )}
      {leg.wait_before_minutes === 0 && leg.change_note && <div className="wait small">{leg.change_note}</div>}
      <div className="option">
        <div className="option-main">
          <span className={`mode ${leg.mode}`}>{MODE_LABEL[leg.mode]}</span>
          <strong>{leg.name}</strong>
          {leg.number && (
            <span className="muted">
              {' '}
              {leg.number}
              {leg.travel_class ? ` · ${leg.travel_class}` : ''}
            </span>
          )}
          <div className="muted small">
            {leg.origin.name} {dayStamp(leg.depart_at)} → {leg.destination.name} {dayStamp(leg.arrive_at)} ·{' '}
            {span(leg.duration_minutes)}
          </div>
        </div>
        <div className="option-side">
          <div className="fare">{inr(leg.fare)}</div>
          {leg.estimated ? (
            <span className="chip wl">estimate, 3 share</span>
          ) : (
            <span className="chip ok">{leg.seats_available} seats</span>
          )}
        </div>
      </div>
    </li>
  )
}

function ItineraryCard({ it, open }: { it: Itinerary; open: boolean }) {
  return (
    <details className="itinerary" open={open}>
      <summary>
        <div className="it-head">
          <div>
            <div className="chain">
              {it.legs.map((l, i) => (
                <span key={i}>
                  {i > 0 && <span className="arrow">→</span>}
                  <span className={`mode ${l.mode}`}>{MODE_LABEL[l.mode]}</span>
                </span>
              ))}
            </div>
            <strong>
              {dayStamp(it.depart_at)} → {dayStamp(it.arrive_at)}
            </strong>
            <div className="muted small">
              {span(it.total_minutes)} total ·{' '}
              {it.changes === 0 ? 'no change' : `${it.changes} change${it.changes > 1 ? 's' : ''}`} · {via(it)}
              {it.waiting_minutes > 0 && <> · {span(it.waiting_minutes)} waiting</>}
            </div>
          </div>
          <div className="option-side">
            <div className="fare">{inr(it.total_fare)}</div>
            {it.tags.map((t) => (
              <span key={t} className="chip dist">
                {t}
              </span>
            ))}
          </div>
        </div>
        <span className="expand muted small">Show steps</span>
      </summary>
      <ul className="legs">
        {it.legs.map((leg, i) => (
          <LegRow key={i} leg={leg} />
        ))}
      </ul>
    </details>
  )
}

export default function Connections({
  data,
  onShow,
  loading,
}: {
  data: SearchResponse
  onShow: () => void
  loading: boolean
}) {
  if (data.connections_paused) {
    return (
      <section className="card">
        <h2>Journeys with changes</h2>
        <p className="warn">
          Multi-leg planning is temporarily paused during high Tatkal demand (Level {data.tatkal_level}) to keep direct search
          fast.
        </p>
      </section>
    )
  }

  if (data.connections_reason === null) {
    if (loading) {
      return (
        <section className="card">
          <p className="working">Finding journeys with changes…</p>
        </section>
      )
    }
    return (
      <div className="card connect-offer">
        <button className="km" onClick={onShow}>
          Show journeys with changes
        </button>
        <span className="muted small"> train, bus or shared cab combinations</span>
      </div>
    )
  }

  return (
    <section className="card">
      <h2>
        Journeys with changes <span className="tag">simulated data</span>
      </h2>
      {data.connections_reason === 'no_direct' && (
        <p className="warn">
          No direct train or bus with seats from {data.origin.name} to {data.destination.city} on this date. Here are journeys
          with changes.
        </p>
      )}
      {data.connections.length === 0 ? (
        <p className="muted">
          No journey with up to two changes reaches {data.destination.city} within 40 hours on this date. Try another day.
        </p>
      ) : (
        data.connections.map((it, i) => <ItineraryCard key={i} it={it} open={i === 0} />)
      )}
      <p className="muted small">
        Only trains and buses with free seats are used. Changes allow at least 90 minutes (more when moving between
        stations), shared cabs run 05:00–22:30. Cab fares are estimates.
      </p>
    </section>
  )
}
