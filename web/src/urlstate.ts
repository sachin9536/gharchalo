import type { SearchQuery } from './api'

// A search lives in the URL (?from=SBC&to=HYB&date=2026-11-27) so it can be shared
// and survives a refresh. Everything read from the URL is validated.
//
// Other parameters (notably ?as=demo-5km, which pins the demo identity) are left
// exactly as they are: only from / to / date / km are ever touched.

const CODE = /^[A-Za-z]{1,8}$/
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

/** `km` is the demo override of the station-distance cohort; null = Flagsmith decides. */
export type UrlState = { query: SearchQuery | null; km: number | null }

export function readUrl(search: string = window.location.search): UrlState {
  const p = new URLSearchParams(search)
  const from = p.get('from') ?? ''
  const to = p.get('to') ?? ''
  const date = p.get('date') ?? ''
  const km = Number(p.get('km'))
  return {
    query:
      CODE.test(from) && CODE.test(to) && ISO_DATE.test(date) && from.toUpperCase() !== to.toUpperCase()
        ? { origin: from.toUpperCase(), dest: to.toUpperCase(), date }
        : null,
    km: p.has('km') && Number.isInteger(km) && km >= 0 && km <= 30 ? km : null,
  }
}

/** The URL search string for a query, keeping every parameter we do not own. */
export function buildSearch(current: string, query: SearchQuery | null, km: number | null): string {
  const p = new URLSearchParams(current)
  for (const key of ['from', 'to', 'date', 'km']) p.delete(key)
  if (query) {
    p.set('from', query.origin)
    p.set('to', query.dest)
    p.set('date', query.date)
    if (km !== null) p.set('km', String(km))
  }
  const text = p.toString()
  return text ? `?${text}` : ''
}

export function writeUrl(query: SearchQuery | null, km: number | null) {
  const next = buildSearch(window.location.search, query, km)
  if (next !== window.location.search) {
    window.history.replaceState(null, '', `${window.location.pathname}${next}${window.location.hash}`)
  }
}
