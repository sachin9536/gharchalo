import type { SearchQuery } from './api'
import { POPULAR_ROUTES } from './demo'

const STEPS = [
  { icon: '🎙', title: 'Say or type', text: 'Hindi, Hinglish or English. Pick a date, we do the rest.' },
  { icon: '🔎', title: 'See every way home', text: 'Trains, buses, nearby stations and journeys with changes, side by side.' },
  { icon: '🚕', title: 'Share a cab', text: 'Find people travelling your way and split the fare.' },
]

export default function Welcome({
  date,
  onPick,
  disabled,
}: {
  date: string
  onPick: (q: SearchQuery) => void
  disabled: boolean
}) {
  return (
    <section className="welcome">
      <h2 className="welcome-title">Where is home this festive season?</h2>
      <p className="welcome-sub">
        Even when every train looks sold out, there is usually a way. We show them all in one place.
      </p>

      <ol className="how">
        {STEPS.map((s, i) => (
          <li key={s.title}>
            <span className="how-icon" aria-hidden="true">
              {s.icon}
            </span>
            <div>
              <strong>
                {i + 1}. {s.title}
              </strong>
              <p>{s.text}</p>
            </div>
          </li>
        ))}
      </ol>

      <h3 className="section-label">Popular right now</h3>
      <div className="route-grid">
        {POPULAR_ROUTES.map((r) => (
          <button
            key={`${r.origin}-${r.dest}`}
            className="route-card"
            disabled={disabled}
            onClick={() => onPick({ origin: r.origin, dest: r.dest, date })}
          >
            <span className="route-icon" aria-hidden="true">
              {r.icon}
            </span>
            <strong>{r.label}</strong>
            <span className="muted small">{r.hint}</span>
            <span className="route-go">Search →</span>
          </button>
        ))}
      </div>
    </section>
  )
}
