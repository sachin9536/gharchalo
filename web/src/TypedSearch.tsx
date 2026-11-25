import { useEffect, useState } from 'react'
import { fetchStations, type SearchQuery, type Station } from './api'
import { POPULAR_ROUTES, SEED_DATES } from './demo'
import { chipDate } from './format'

function StationSelect({
  label,
  value,
  onChange,
  stations,
  labels,
}: {
  label: string
  value: string
  onChange: (code: string) => void
  stations: Station[]
  labels: Record<string, string>
}) {
  // Voice can resolve a non-primary station (e.g. Secunderabad); keep it selectable.
  const known = stations.some((s) => s.code === value)
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {!known && value && <option value={value}>{labels[value] ?? value}</option>}
        {stations.map((s) => (
          <option key={s.code} value={s.code}>
            {s.city}
          </option>
        ))}
      </select>
    </label>
  )
}

export default function TypedSearch({
  value,
  labels,
  onChange,
  onSearch,
  disabled,
}: {
  value: SearchQuery
  labels: Record<string, string>
  onChange: (q: SearchQuery) => void
  onSearch: (q: SearchQuery) => void
  disabled: boolean
}) {
  const [stations, setStations] = useState<Station[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchStations()
      .then(setStations)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  const sameCity = value.origin === value.dest

  return (
    <div className="typed">
      {error && <p className="error">Could not load stations: {error}</p>}
      <form
        className="typed-form"
        onSubmit={(e) => {
          e.preventDefault()
          onSearch(value)
        }}
      >
        <div className="od">
          <StationSelect
            label="From"
            value={value.origin}
            onChange={(origin) => onChange({ ...value, origin })}
            stations={stations}
            labels={labels}
          />
          <button
            type="button"
            className="swap"
            onClick={() => onChange({ ...value, origin: value.dest, dest: value.origin })}
            aria-label="Swap from and to"
            title="Swap"
          >
            ⇄
          </button>
          <StationSelect
            label="To"
            value={value.dest}
            onChange={(dest) => onChange({ ...value, dest })}
            stations={stations}
            labels={labels}
          />
        </div>

        <div className="dates">
          <span className="muted small">When</span>
          {SEED_DATES.map((d) => (
            <button
              type="button"
              key={d}
              className={`pill ${d === value.date ? 'on' : ''}`}
              aria-pressed={d === value.date}
              onClick={() => onChange({ ...value, date: d })}
            >
              {chipDate(d)}
            </button>
          ))}
          <input
            type="date"
            value={value.date}
            onChange={(e) => onChange({ ...value, date: e.target.value })}
            aria-label="Pick another date"
          />
        </div>

        <button type="submit" className="primary wide" disabled={disabled || sameCity || !stations.length || !value.date}>
          Find ways home
        </button>
      </form>
      {sameCity && <p className="warn">Pick two different cities.</p>}

      <div className="popular">
        <span className="muted small">Popular this festive season</span>
        {POPULAR_ROUTES.map((r) => (
          <button
            key={`${r.origin}-${r.dest}`}
            type="button"
            className="pill"
            disabled={disabled}
            onClick={() => {
              const q = { ...value, origin: r.origin, dest: r.dest }
              onChange(q)
              onSearch(q)
            }}
          >
            {r.label}
            {r.hint && <span className="muted"> · {r.hint}</span>}
          </button>
        ))}
      </div>
      <p className="muted small">Demo data covers 26 Nov – 1 Dec 2026.</p>
    </div>
  )
}
