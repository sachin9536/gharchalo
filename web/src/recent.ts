import type { SearchQuery } from './api'

// The last few searches, kept in this browser only.
const KEY = 'gharchalo.recent'
const LIMIT = 4

export function loadRecent(): SearchQuery[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter(
        (q): q is SearchQuery =>
          typeof q?.origin === 'string' && typeof q?.dest === 'string' && typeof q?.date === 'string',
      )
      .slice(0, LIMIT)
  } catch {
    return []
  }
}

/** The new list: this search first, no duplicate routes, at most LIMIT entries. */
export function withRecent(list: SearchQuery[], q: SearchQuery): SearchQuery[] {
  return [q, ...list.filter((r) => !(r.origin === q.origin && r.dest === q.dest))].slice(0, LIMIT)
}

export function saveRecent(list: SearchQuery[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list))
  } catch {
    // storage blocked (private mode): recent searches just won't persist
  }
}
