import { useState } from 'react'
import { selectAlternative, type Option, type SearchResponse } from './api'
import CabMatches from './CabMatches'
import Connections from './Connections'
import DateStrip from './DateStrip'
import TatkalCountdown from './TatkalCountdown'
import ReadAloud from './ReadAloud'
import { spokenSummary, type SpokenLang } from './speech'
import {
  DAY_PARTS,
  MODE_ICON,
  chain,
  clock,
  dayOffset,
  dayPart,
  dayStamp,
  inr,
  shortDate,
  span,
  via,
  type DayPart,
} from './format'

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

function OptionRow({
  o,
  showOrigin,
  badges = [],
  onSelect,
  selected,
}: {
  o: Option
  showOrigin?: boolean
  badges?: string[]
  onSelect?: () => void
  selected?: boolean
}) {
  const plus = dayOffset(o.depart_at, o.arrive_at)
  return (
    <li className={`option ${o.status}`}>
      <div className="option-main">
        <span className={`mode ${o.mode}`}>
          {MODE_ICON[o.mode]} {o.mode === 'train' ? 'Train' : 'Bus'}
        </span>
        {o.distance_km != null && <span className="chip dist">{o.distance_km} km away</span>}
        {badges.map((b) => (
          <span key={b} className="chip best">
            {b}
          </span>
        ))}
        <strong>{o.name}</strong>
        <span className="muted">
          {' '}
          {o.number} · {o.travel_class}
        </span>
        <div className="row-times">
          <strong>{clock(o.depart_at)}</strong> → <strong>{clock(o.arrive_at)}</strong>
          {plus > 0 && <sup>+{plus}</sup>}
          <span className="muted"> · {span(o.duration_minutes)}</span>
        </div>
        <div className="muted small">
          {showOrigin ? `from ${o.origin.name} ` : ''}to {o.destination.name}
        </div>
      </div>
      <div className="option-side">
        <div className="fare big">{inr(o.fare)}</div>
        {available(o) ? (
          <span className="chip ok">{o.seats_available} seats</span>
        ) : (
          <span className="chip wl">WL {o.waitlist}</span>
        )}
        {o.confirm_chance !== null && (
          <div>
            <span
              className={`chance ${o.confirm_chance >= 0.7 ? 'high' : o.confirm_chance >= 0.4 ? 'medium' : 'low'}`}
              title="Rough estimate from the waitlist length, the class and the days left before travel. Simulated data, not a prediction."
            >
              ~{Math.round(o.confirm_chance * 100)}% may confirm
            </span>
          </div>
        )}
        {onSelect && (
          <div>
            <button className={`km select-alt ${selected ? 'on' : ''}`} onClick={onSelect} disabled={selected}>
              {selected ? 'Selected ✓' : 'Choose this'}
            </button>
          </div>
        )}
      </div>
    </li>
  )
}

type Pick = { title: string; detail: string; departs: string; arrive: string; fare: number; tab: Tab; badge: string; kind: string }

function bestPicks(data: SearchResponse): { quickest?: Pick; cheapest?: Pick } {
  const all: Pick[] = [
    ...data.options.filter(available).map((o) => ({
      title: o.name,
      detail: `Leaves ${o.origin.name} at ${clock(o.depart_at)}`,
      departs: o.depart_at,
      kind: o.mode,
      arrive: o.arrive_at,
      fare: o.fare,
      tab: o.mode,
      badge: `${MODE_ICON[o.mode]} ${o.mode === 'train' ? 'Train' : 'Bus'}`,
    })),
    ...data.alternatives.map((o) => ({
      title: o.name,
      detail: `Leaves ${o.origin.name} (${o.distance_km} km away) at ${clock(o.depart_at)}`,
      departs: o.depart_at,
      kind: 'nearby',
      arrive: o.arrive_at,
      fare: o.fare,
      tab: 'nearby' as const,
      badge: '🚆 Nearby station',
    })),
    ...data.connections.map((it) => ({
      title: chain(it),
      detail: `${via(it)} · leaves ${dayStamp(it.depart_at)}`,
      departs: it.depart_at,
      kind: 'changes',
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
  maxKmOverride,
  allowOverride,
  onMaxKm,
  onShowConnections,
  onModify,
  onNotify,
  onPickDate,
  spokenLang,
  autoSpeak,
  voiceOff,
  features,
}: {
  data: SearchResponse
  updating: boolean
  maxKmOverride: number | null
  allowOverride: boolean
  onMaxKm: (km: number | null) => void
  onShowConnections: () => void
  onModify: () => void
  onNotify: (message: string) => void
  onPickDate: (date: string) => void
  spokenLang: SpokenLang
  autoSpeak: boolean
  voiceOff: boolean
  features: Record<string, boolean>
}) {
  const [tab, setTab] = useState<Tab>('all')
  const [sort, setSort] = useState<Sort>('depart')
  const [seatsOnly, setSeatsOnly] = useState(false)
  const [part, setPart] = useState<DayPart>('any')
  const [selectedAlt, setSelectedAlt] = useState<number | null>(null)
  const [selectError, setSelectError] = useState<string | null>(null)

  // The cohort distance actually applied by the server (Flagsmith, or the demo override).
  const activeKm = data.max_station_distance_km
  const chooseAlt = async (serviceId: number) => {
    if (data.search_id === null) return
    setSelectError(null)
    try {
      await selectAlternative(data.search_id, serviceId)
      setSelectedAlt(serviceId)
    } catch (e) {
      setSelectError(e instanceof Error ? e.message : String(e))
    }
  }

  const passes = (o: Option) => (!seatsOnly || available(o)) && (part === 'any' || dayPart(o.depart_at) === part)
  const allTrains = data.options.filter((o) => o.mode === 'train')
  const allBuses = data.options.filter((o) => o.mode === 'bus')
  const trains = allTrains.filter(passes).sort(COMPARE[sort])
  const buses = allBuses.filter(passes).sort(COMPARE[sort])
  const hidden = allTrains.length + allBuses.length - trains.length - buses.length
  const filtering = seatsOnly || part !== 'any'

  const seatsCount = data.options.filter(available).length
  const showNearby = !data.preferred_station_has_train_seats && allTrains.length > 0
  const { quickest, cheapest } = bestPicks(data)
  const cab4 = data.cab.shares.find((s) => s.people === 4) ?? data.cab.shares[data.cab.shares.length - 1]

  // "Cheapest" / "Fastest" badges, only when there is something to compare.
  const bestBadges = new Map<number, string[]>()
  const bookable = data.options.filter(available)
  if (bookable.length > 1) {
    const mark = (o: Option, label: string) => bestBadges.set(o.id, [...(bestBadges.get(o.id) ?? []), label])
    mark(bookable.reduce((a, b) => (b.fare < a.fare ? b : a)), 'Cheapest')
    mark(bookable.reduce((a, b) => (b.duration_minutes < a.duration_minutes ? b : a)), 'Fastest')
  }

  const open = (t: Tab) => {
    setTab(t)
    if (t === 'changes' && data.connections_reason === null) onShowConnections()
  }
  const visible = (t: Tab) => tab === 'all' || tab === t

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      onNotify('Link copied. Paste it anywhere.')
    } catch {
      onNotify('Could not copy. Copy the link from the address bar.')
    }
  }
  const whatsapp = () => {
    const text = `${data.origin.city} → ${data.destination.city} on ${shortDate(data.date)}: trains, buses and shared cabs\n${window.location.href}`
    window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, '_blank', 'noopener')
  }

  const tabs: { id: Tab; label: string; count?: number; hidden?: boolean }[] = [
    { id: 'all', label: '✨ Overview' },
    { id: 'train', label: '🚆 Trains', count: allTrains.length },
    { id: 'bus', label: '🚌 Buses', count: allBuses.length },
    { id: 'nearby', label: '📍 Nearby stations', count: data.alternatives.length, hidden: !showNearby },
    {
      id: 'changes',
      label: '🔀 With changes',
      count: data.connections_reason === null ? undefined : data.connections.length,
    },
    { id: 'cab', label: '🚕 Shared cab' },
  ]

  return (
    <div className={`results ${updating ? 'updating' : ''}`}>
      <div className="routebar">
        <div className="routebar-title">
          <h2 className="route-h">
            {data.origin.city} <span aria-hidden="true">→</span>
            <span className="sr-only"> to </span> {data.destination.city}
          </h2>
          <span className="muted small">
            {shortDate(data.date)} · leaving from {data.origin.name}
          </span>
        </div>
        <div className="routebar-side">
          {updating && <span className="spinner" role="status" aria-label="Updating" />}
          {data.served_from === 'cache' && <span className="tag soft">cached</span>}
          <ReadAloud
            textFor={(lang) =>
              spokenSummary(
                {
                  origin: data.origin.city,
                  destination: data.destination.city,
                  date: data.date,
                  best: quickest && {
                    title: quickest.title,
                    departs: clock(quickest.departs),
                    arrives: clock(quickest.arrive),
                    fare: quickest.fare,
                    mode: quickest.kind,
                  },
                  cabEach: cab4.per_person,
                },
                lang,
              )
            }
            date={data.date}
            initialLang={spokenLang}
            autoPlay={autoSpeak}
            disabledReason={
              data.tatkal_level >= 2
                ? 'Spoken replies paused during peak demand'
                : voiceOff
                  ? 'Voice is paused right now'
                  : null
            }
          />
          <button className="ghost" onClick={() => void copyLink()}>
            🔗 Copy link
          </button>
          <button className="ghost wa" onClick={whatsapp}>
            WhatsApp
          </button>
          <button className="ghost" onClick={onModify}>
            Change search
          </button>
        </div>
      </div>

      <p className={`guide ${seatsCount > 0 ? 'good' : 'tip'}`}>
        {seatsCount > 0 ? (
          <>
            <strong>
              {seatsCount} direct option{seatsCount > 1 ? 's have' : ' has'} seats.
            </strong>{' '}
            Pick one below, or compare with a shared cab.
          </>
        ) : (
          <>
            <strong>No direct train or bus has seats.</strong> You still have options: nearby stations, journeys with
            changes and a shared cab.
          </>
        )}
      </p>

      {features.tatkal_countdown && (
        <TatkalCountdown date={data.date} origin={data.origin.city} destination={data.destination.city} />
      )}

      <DateStrip query={{ origin: data.origin.code, dest: data.destination.code, date: data.date }} onPick={onPickDate} />

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

      {tab === 'all' && (
        <div className="picks">
          {quickest && <PickCard label="⚡ Quickest way home" pick={quickest} onOpen={open} />}
          {cheapest && <PickCard label="💰 Cheapest with seats" pick={cheapest} onOpen={open} />}
          <button className="pick cab-pick" onClick={() => open('cab')}>
            <span className="pick-label">🚕 Split a cab</span>
            <strong>{inr(cab4.per_person)} each</strong>
            <span className="muted small">
              With up to 3 co-travellers · about {data.cab.distance_km} km by road
            </span>
            <span className="pick-foot">Available any time between 05:00 and 22:30</span>
            <span className="pick-go">Find co-travellers →</span>
          </button>
          {!quickest && (
            <button className="pick" onClick={() => open(showNearby ? 'nearby' : 'changes')}>
              <span className="pick-label">{showNearby ? '📍 Nearby stations' : '🔀 With changes'}</span>
              <strong>{showNearby ? 'Trains with seats close by' : 'Combine trains, buses and cabs'}</strong>
              <span className="muted small">
                {showNearby ? `${data.alternatives.length} within ${activeKm} km` : 'We check timings for you'}
              </span>
              <span className="pick-go">See details →</span>
            </button>
          )}
        </div>
      )}

      {(visible('train') || visible('bus')) && (
        <section className="card">
          <div className="card-head">
            <h2>{tab === 'bus' ? 'Buses' : tab === 'train' ? 'Trains' : 'Direct options'} from {data.origin.name}</h2>
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

          <div className="filters">
            <label className="switch">
              <input type="checkbox" checked={seatsOnly} onChange={(e) => setSeatsOnly(e.target.checked)} />
              <span>Seats available only</span>
            </label>
            <div className="chips" role="group" aria-label="Departure time">
              {DAY_PARTS.map((p) => (
                <button
                  key={p.id}
                  className={`km ${part === p.id ? 'on' : ''}`}
                  aria-pressed={part === p.id}
                  onClick={() => setPart(p.id)}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {visible('train') && (
            <>
              {tab === 'all' && <h3>🚆 Trains</h3>}
              {trains.length ? (
                <ul className="options">
                  {trains.map((o) => (
                    <OptionRow key={o.id} o={o} badges={bestBadges.get(o.id)} />
                  ))}
                </ul>
              ) : (
                <p className="muted">{filtering ? 'No trains match these filters.' : 'No trains on this date.'}</p>
              )}
              {showNearby && !filtering && (
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
              {tab === 'all' && <h3>🚌 Buses</h3>}
              {buses.length ? (
                <ul className="options">
                  {buses.map((o) => (
                    <OptionRow key={o.id} o={o} badges={bestBadges.get(o.id)} />
                  ))}
                </ul>
              ) : (
                <p className="muted">{filtering ? 'No buses match these filters.' : 'No buses on this route.'}</p>
              )}
            </>
          )}

          {filtering && hidden > 0 && (
            <p className="muted small">
              {hidden} option{hidden > 1 ? 's' : ''} hidden by filters.{' '}
              <button
                className="link"
                onClick={() => {
                  setSeatsOnly(false)
                  setPart('any')
                }}
              >
                Clear filters
              </button>
            </p>
          )}
        </section>
      )}

      {visible('nearby') && showNearby && (
        <section className="card">
          <div className="card-head">
            <h2>📍 Trains with seats from nearby stations</h2>
            <span className="tag soft">{activeKm} km cohort</span>
          </div>
          <p className="warn">
            No train with seats leaves {data.origin.name}. Showing nearby stations within <strong>{activeKm} km</strong>
            {allowOverride && (
              <>
                {' '}
                · demo override:
                {DISTANCE_CHOICES.map((km) => (
                  <button
                    key={km}
                    className={`km ${km === activeKm ? 'on' : ''}`}
                    onClick={() => onMaxKm(km)}
                    aria-pressed={km === activeKm}
                  >
                    {km} km
                  </button>
                ))}
                {maxKmOverride !== null && (
                  <button className="link small" onClick={() => onMaxKm(null)}>
                    reset
                  </button>
                )}
              </>
            )}
          </p>
          {selectError && <p className="error">{selectError}</p>}
          {data.alternatives.length ? (
            <ul className="options">
              {data.alternatives.map((o) => (
                <OptionRow
                  key={o.id}
                  o={o}
                  showOrigin
                  onSelect={data.search_id !== null ? () => void chooseAlt(o.id) : undefined}
                  selected={selectedAlt === o.id}
                />
              ))}
            </ul>
          ) : (
            <p className="muted">Nothing with seats within {activeKm} km. Try a longer distance above.</p>
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
            🚕 Shared cab <span className="tag">estimate</span>
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
            allowOverride={allowOverride}
          />
        </section>
      )}
    </div>
  )
}
