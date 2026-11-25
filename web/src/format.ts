import type { Itinerary, Leg } from './api'

// Datetimes from the API are naive local ISO strings ("2026-11-27T21:40:00").

export const MODE_LABEL: Record<Leg['mode'], string> = { train: 'Train', bus: 'Bus', cab: 'Shared cab' }

export const inr = (n: number) => `₹${n.toLocaleString('en-IN')}`

export function clock(iso: string) {
  return new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

export function span(minutes: number) {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`
}

export function dayOffset(depart: string, arrive: string) {
  const d = new Date(depart)
  const a = new Date(arrive)
  d.setHours(0, 0, 0, 0)
  a.setHours(0, 0, 0, 0)
  return Math.round((a.getTime() - d.getTime()) / 86_400_000)
}

/** "Fri 21:40" */
export function dayStamp(iso: string) {
  const weekday = new Date(iso).toLocaleDateString('en-IN', { weekday: 'short' })
  return `${weekday} ${clock(iso)}`
}

const asDate = (isoDate: string) => new Date(`${isoDate}T00:00:00`)

/** "Fri, 27 Nov" */
export function shortDate(isoDate: string) {
  return asDate(isoDate).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

/** "Fri, 27 November 2026" */
export function longDate(isoDate: string) {
  return asDate(isoDate).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' })
}

/** "Fri 27" */
export function chipDate(isoDate: string) {
  const d = asDate(isoDate)
  return `${d.toLocaleDateString('en-IN', { weekday: 'short' })} ${d.getDate()}`
}

export const chain = (it: Itinerary) => it.legs.map((l) => MODE_LABEL[l.mode]).join(' + ')

export function via(it: Itinerary) {
  const stops = it.legs.slice(0, -1).map((l) => l.destination.city)
  return stops.length ? `via ${stops.join(', ')}` : 'one leg'
}
