import type { SearchQuery } from './api'

// A search lives in the URL (?from=SBC&to=HYB&date=2026-11-27) so it can be shared
// and survives a refresh. Everything read from the URL is validated.

const CODE = /^[A-Za-z]{1,8}$/
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/
export const DEFAULT_KM = 15

export type UrlState = { query: SearchQuery | null; km: number }

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
    km: Number.isInteger(km) && km >= 0 && km <= 30 && p.has('km') ? km : DEFAULT_KM,
  }
}

export function writeUrl(query: SearchQuery | null, km: number) {
  const base = window.location.pathname
  if (!query) {
    window.history.replaceState(null, '', base)
    return
  }
  const p = new URLSearchParams({ from: query.origin, to: query.dest, date: query.date })
  if (km !== DEFAULT_KM) p.set('km', String(km))
  window.history.replaceState(null, '', `${base}?${p}`)
}
