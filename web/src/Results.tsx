import { useState } from 'react'
import type { Option, SearchResponse } from './api'
import CabMatches from './CabMatches'
import Connections from './Connections'
import { chain, clock, dayOffset, dayStamp, inr, shortDate, span, via } from './format'

const DISTANCE_CHOICES = [5, 15, 30]

type Tab = 'all' | 'train' | 'bus' | 'nearby' | 'changes' | 'cab'
type Sort = 'depart' | 'fare' | 'duration' | 'seats'

const SORTS: { id: Sort; label: string }[] = [
  { id: 'depart', label: 'Departure' },
  { id: 'seats', label: 'Seats first' },
  { id: 'fare', label: 'Cheapest' },
  { id: 'duration', label: 'Fastest' },
]

const COMPARE: Record<Sort, (a: Option, b: Option) => number> = {
  depart: (a, b) => a.depart_at.localeCompare(b.depart_at),
  fare: (a, b) => a.fare - b.fare,
  duration: (a, b) => a.duration_minutes - b.duration_minutes,
  seats: (a, b) =>
    Number(b.status === 'available') - Number(a.status === 'available') || a.depart_at.localeCompare(b.depart_at),
}

const available = (o: Option) => o.status === 'available'

function OptionRow({ o, showOrigin }: { o: Option; showOrigin?: boolean }) {
  const plus = dayOffset(o.depart_at, o.arrive_at)
  return (
    <li className={`option ${o.status}`}>
      <div className="option-main">
        <span className={`mode ${o.mode}`}>{o.mode === 'train' ? 'Train' : 'Bus'}</span>
        {o.distance_km != null && <span className="chip dist">{o.distance_km} km away</span>}
        <strong>{o.name}</strong>
        <span className="muted">
          {' '}
          {o.number} · {o.travel_class}
        </span>
        <div className="muted small">
          {showOrigin && <>from {o.origin.name} · </>}
          {clock(o.depart_at)} → {clock(o.arrive_at)}
          {plus > 0 && <sup>+{plus}</sup>} · {span(o.duration_minutes)} · to {o.destination.name}
        </div>
      </div>
      <div className="option-side">
        <div className="fare">{inr(o.fare)}</div>
        {available(o) ? (
          <span className="chip ok">{o.seats_available} seats</span>
        ) : (
          <span className="chip wl">WL {o.waitlist}</span>
        )}
      </div>
    </li>
  )
}

type Pick = { title: string; detail: string; arrive: string; fare: number; tab: Tab; badge: string }

function bestPicks(data: SearchResponse): { quickest?: Pick; cheapest?: Pick } {
  const all: Pick[] = [
    ...data.options.filter(available).map((o) => ({
      title: o.name,
      detail: `Leaves ${o.origin.name} at ${clock(o.depart_at)}`,
      arrive: o.arrive_at,
      fare: o.fare,
      tab: o.mode,
      badge: o.mode === 'train' ? 'Train' : 'Bus',
    })),
    ...data.alternatives.map((o) => ({
      title: o.name,
      detail: `Leaves ${o.origin.name} (${o.distance_km} km away) at ${clock(o.depart_at)}`,
      arrive: o.arrive_at,
      fare: o.fare,
      tab: 'nearby' as const,
      badge: 'Nearby station',
    })),
    ...data.connections.map((it) => ({
      title: chain(it),
      detail: `${via(it)} · leaves ${dayStamp(it.depart_at)}`,
      arrive: it.arrive_at,
      fare: it.total_fare,
      tab: 'changes' as const,
      badge: `${it.changes} change${it.changes === 1 ? '' : 's'}`,
    })),
  ]
  if (!all.length) return {}
  const quickest = all.reduce((a, b) => (b.arrive < a.arrive ? b : a))
  const cheapest = all.reduce((a, b) => (b.fare < a.fare ? b : a))
  return { quickest, cheapest: cheapest === quickest ? undefined : cheapest }
}

function PickCard({ label, pick, onOpen }: { label: string; pick: Pick; onOpen: (t: Tab) => void }) {
  return (
    <button className="pick" onClick={() => onOpen(pick.tab)}>
      <span className="pick-label">{label}</span>
      <strong>{pick.title}</strong>
      <span className="muted small">
        {pick.badge} · {pick.detail}
      </span>
      <span className="pick-foot">
        Arrives {dayStamp(pick.arrive)} · <strong>{inr(pick.fare)}</strong>
      </span>
      <span className="pick-go">See details →</span>
    </button>
  )
}

export function ResultsSkeleton() {
  return (
    <div className="card skeleton" aria-label="Searching" aria-busy="true">
      <div className="bar w40" />
      <div className="bar" />
      <div className="bar" />
      <div className="bar w70" />
    </div>
  )
}

export default function Results({
  data,
  updating,
  maxKm,
  onMaxKm,
  onShowConnections,
  onModify,
}: {
  data: SearchResponse
  updating: boolean
  maxKm: number
  onMaxKm: (km: number) => void
  onShowConnections: () => void
  onModify: () => void
}) {
  const [tab, setTab] = useState<Tab>('all')
  const [sort, setSort] = useState<Sort>('depart')

  const trains = data.options.filter((o) => o.mode === 'train').sort(COMPARE[sort])
  const buses = data.options.filter((o) => o.mode === 'bus').sort(COMPARE[sort])
  const showNearby = !data.preferred_station_has_train_seats && trains.length > 0
  const { quickest, cheapest } = bestPicks(data)

  const open = (t: Tab) => {
    setTab(t)
    if (t === 'changes' && data.connections_reason === null) onShowConnections()
  }
  const visible = (t: Tab) => tab === 'all' || tab === t

  const tabs: { id: Tab; label: string; count?: number; hidden?: boolean }[] = [
    { id: 'all', label: 'All' },
    { id: 'train', label: 'Trains', count: trains.length },
    { id: 'bus', label: 'Buses', count: buses.length },
    { id: 'nearby', label: 'Nearby stations', count: data.alternatives.length, hidden: !showNearby },
    {
      id: 'changes',
      label: 'With changes',
      count: data.connections_reason === null ? undefined : data.connections.length,
    },
    { id: 'cab', label: 'Shared cab' },
  ]

  return (
    <div className={`results ${updating ? 'updating' : ''}`}>
      <div className="routebar">
        <div>
          <strong>
            {data.origin.city} → {data.destination.city}
          </strong>
          <span className="muted small">
            {' '}
            · {shortDate(data.date)} · from {data.origin.name}
          </span>
        </div>
        <div className="routebar-side">
          {updating && <span className="spinner" role="status" aria-label="Updating" />}
          <span className="tag">simulated</span>
          <button className="link" onClick={onModify}>
            Change search
          </button>
        </div>
      </div>

      <nav className="tabs" role="tablist" aria-label="Result types">
        {tabs
          .filter((t) => !t.hidden)
          .map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              className={tab === t.id ? 'on' : ''}
              onClick={() => open(t.id)}
            >
              {t.label}
              {t.count !== undefined && <span className="count">{t.count}</span>}
            </button>
          ))}
      </nav>

      {tab === 'all' &&
        (quickest ? (
          <div className="picks">
            <PickCard label="Quickest way home" pick={quickest} onOpen={open} />
            {cheapest && <PickCard label="Cheapest with seats" pick={cheapest} onOpen={open} />}
          </div>
        ) : (
          <section className="card picks-empty">
            <p>
              <strong>No direct train or bus has seats.</strong> You can still get home:
            </p>
            <div className="match-controls">
              {showNearby && (
                <button className="km" onClick={() => open('nearby')}>
                  Trains from nearby stations
                </button>
              )}
              <button className="km" onClick={() => open('changes')}>
                Journeys with changes
              </button>
              <button className="km" onClick={() => open('cab')}>
                Share a cab
              </button>
            </div>
          </section>
        ))}

      {(visible('train') || visible('bus')) && (
        <section className="card">
          <div className="card-head">
            <h2>{tab === 'bus' ? 'Buses' : tab === 'train' ? 'Trains' : 'Direct'} from {data.origin.name}</h2>
            <label className="sort">
              <span className="muted small">Sort</span>
              <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
                {SORTS.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {visible('train') && (
            <>
              {tab === 'all' && <h3>Trains</h3>}
              {trains.length ? (
                <ul className="options">
                  {trains.map((o) => (
                    <OptionRow key={o.id} o={o} />
                  ))}
                </ul>
              ) : (
                <p className="muted">No trains on this date.</p>
              )}
              {showNearby && (
                <p className="nudge">
                  Every train from {data.origin.name} is waitlisted.{' '}
                  <button className="link" onClick={() => open('nearby')}>
                    See trains with seats from nearby stations
                  </button>
                </p>
              )}
            </>
          )}

          {visible('bus') && (
            <>
              {tab === 'all' && <h3>Buses</h3>}
              {buses.length ? (
                <ul className="options">
                  {buses.map((o) => (
                    <OptionRow key={o.id} o={o} />
                  ))}
                </ul>
              ) : (
                <p className="muted">No buses on this route.</p>
              )}
            </>
          )}
        </section>
      )}

      {visible('nearby') && showNearby && (
        <section className="card">
          <h2>Trains with seats from nearby stations</h2>
          <p className="warn">
            No train with seats leaves {data.origin.name}. Show stations within
            {DISTANCE_CHOICES.map((km) => (
              <button
                key={km}
                className={`km ${km === maxKm ? 'on' : ''}`}
                onClick={() => onMaxKm(km)}
                aria-pressed={km === maxKm}
              >
                {km} km
              </button>
            ))}
            <span className="muted small"> (Flagsmith will assign this per user)</span>
          </p>
          {data.alternatives.length ? (
            <ul className="options">
              {data.alternatives.map((o) => (
                <OptionRow key={o.id} o={o} showOrigin />
              ))}
            </ul>
          ) : (
            <p className="muted">Nothing with seats within {maxKm} km.</p>
          )}
          {data.more_alternatives_beyond_limit > 0 && (
            <p className="muted small">
              {data.more_alternatives_beyond_limit} more option
              {data.more_alternatives_beyond_limit > 1 ? 's' : ''} from stations farther away.
            </p>
          )}
        </section>
      )}

      {visible('changes') && (
        <Connections data={data} onShow={onShowConnections} loading={updating && data.connections_reason === null} />
      )}

      {visible('cab') && (
        <section className="card">
          <h2>
            Shared cab <span className="tag">estimate</span>
          </h2>
          <p>
            About {data.cab.distance_km} km by road, around <strong>{inr(data.cab.total_fare)}</strong> for the cab.
          </p>
          <div className="shares">
            {data.cab.shares.map((s) => (
              <div key={s.people} className="share">
                <strong>{inr(s.per_person)}</strong>
                <span className="muted small">each, {s.people} people</span>
              </div>
            ))}
          </div>
          <CabMatches
            origin={data.origin.code}
            dest={data.destination.code}
            date={data.date}
            shares={data.cab.shares}
          />
        </section>
      )}
    </div>
  )
}
