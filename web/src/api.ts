// Mirrors api/main.py, api/journey.py and api/search.py.

import { getUserId } from './user'

export type StationRef = { spoken: string; code: string | null; name: string | null }

export type Journey = {
  origin: StationRef | null
  destination: StationRef | null
  date: string | null // YYYY-MM-DD
  fallback_mode: 'train' | 'shared_cab' | 'any'
  language: string | null
  missing: string[]
  warnings: string[]
}

export type VoiceResponse = {
  transcript: string
  language_code: string | null
  journey: Journey
  source: 'sarvam' | 'stub'
}

export type Station = { code: string; name: string; city: string }

export type Option = {
  id: number
  mode: 'train' | 'bus'
  number: string
  name: string
  operator: string
  travel_class: string
  origin: Station
  destination: Station
  depart_at: string // naive local ISO datetime
  arrive_at: string
  duration_minutes: number
  fare: number // INR, simulated estimate
  status: 'available' | 'waitlist'
  seats_available: number
  waitlist: number
  distance_km: number | null // alternatives only
  confirm_chance: number | null // waitlisted trains only: rule-of-thumb estimate, simulated data
}

export type Leg = {
  mode: 'train' | 'bus' | 'cab'
  number: string | null
  name: string
  operator: string
  travel_class: string | null
  origin: Station
  destination: Station
  depart_at: string
  arrive_at: string
  duration_minutes: number
  fare: number // a cab leg is one share of a 3-person cab (estimate)
  seats_available: number | null
  estimated: boolean
  wait_before_minutes: number
  change_note: string | null
}

export type Itinerary = {
  legs: Leg[]
  depart_at: string
  arrive_at: string
  total_minutes: number
  waiting_minutes: number
  total_fare: number
  changes: number
  tags: string[]
}

export type SearchResponse = {
  source: 'simulated'
  origin: Station
  destination: Station
  date: string
  max_station_distance_km: number
  options: Option[]
  preferred_station_has_train_seats: boolean
  alternatives: Option[]
  more_alternatives_beyond_limit: number
  connections: Itinerary[]
  connections_reason: 'no_direct' | 'requested' | null
  connections_paused: boolean
  served_from: 'live' | 'cache'
  tatkal_level: number
  search_id: number | null
  cab: {
    distance_km: number
    total_fare: number
    shares: { people: number; per_person: number }[]
    note: string
  }
}

export type ClientConfig = {
  tatkal_level: number
  poll_s: number
  interaction_mode: 'voice' | 'text_only'
  cohort_km: number
  matching_strategy: Strategy
  urgent: boolean
  flags_source: 'identity' | 'environment' | 'defaults'
  allow_override: boolean
  features?: Record<string, boolean> // release toggles for this visitor (Flagsmith)
}

export type SearchQuery = { origin: string; dest: string; date: string }

function userHeaders(extra?: Record<string, string>): Record<string, string> {
  return { 'X-User-Id': getUserId(), ...extra }
}

async function json<T>(resp: Response): Promise<T> {
  if (resp.ok) return resp.json()
  let detail = `HTTP ${resp.status}`
  try {
    const body = await resp.json()
    if (typeof body.detail === 'string') detail = body.detail
  } catch {
    // body was not JSON; keep the status text
  }
  throw new Error(detail)
}

export async function fetchConfig(date?: string, signal?: AbortSignal): Promise<ClientConfig> {
  const qs = date ? `?date=${encodeURIComponent(date)}` : ''
  return json(await fetch(`/api/config${qs}`, { headers: userHeaders(), signal }))
}

export async function postVoice(audio: Blob, filename: string): Promise<VoiceResponse> {
  const form = new FormData()
  form.append('file', audio, filename)
  return json(await fetch('/api/voice', { method: 'POST', headers: userHeaders(), body: form }))
}

export async function parseText(text: string): Promise<VoiceResponse> {
  return json(
    await fetch('/api/journey/parse', {
      method: 'POST',
      headers: userHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ text }),
    }),
  )
}

export async function fetchStations(): Promise<Station[]> {
  return json(await fetch('/api/stations', { headers: userHeaders() }))
}

export async function searchJourneys(
  q: SearchQuery,
  maxStationDistanceKm: number | null,
  includeConnections: boolean,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  const params = new URLSearchParams({
    origin: q.origin,
    dest: q.dest,
    date: q.date,
    include_connections: String(includeConnections),
  })
  if (maxStationDistanceKm !== null) {
    params.set('max_station_distance_km', String(maxStationDistanceKm))
  }
  return json(await fetch(`/api/search?${params}`, { headers: userHeaders(), signal }))
}

export async function selectAlternative(
  searchId: number,
  serviceId: number,
): Promise<{ search_id: number; service_id: number; station_code: string; extra_km: number }> {
  return json(
    await fetch(`/api/search/${searchId}/select`, {
      method: 'POST',
      headers: userHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ service_id: serviceId }),
    }),
  )
}

export type Strategy = 'exact' | 'time_window'

export type Match = {
  traveller_id: number
  name: string
  date: string
  window_start: string // HH:MM:SS
  window_end: string
  pickup: Station
  drop: Station
  shift: 'exact' | 'flexible'
  pickup_km: number // this match's pickup station, from yours
  day_shift: number // their day minus yours
  time_gap_min: number // minutes between the two time windows (0 = they overlap)
}

export type MatchResponse = {
  source: 'simulated'
  match_id: number | null
  strategy: Strategy
  offered: number
  suggested_group_size: number
  matches: Match[]
  paused: boolean
  retry_after_s: number | null
}

export type MatchQuery = {
  user_id: string
  origin: string
  dest: string
  date: string
  window_start: string
  window_end: string
  strategy?: Strategy
}

export async function postMatch(q: MatchQuery, signal?: AbortSignal): Promise<MatchResponse> {
  return json(
    await fetch('/api/match', {
      method: 'POST',
      headers: userHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(q),
      signal,
    }),
  )
}

export async function acceptMatch(matchId: number): Promise<{ match_id: number; accepted: boolean }> {
  return json(await fetch(`/api/match/${matchId}/accept`, { method: 'POST', headers: userHeaders() }))
}

export type ExperimentVisitors = 'live' | 'simulated' | 'all'

export type ExperimentsSummary = {
  source: 'simulated' // the railway data is always simulated
  visitors: ExperimentVisitors // which visitors this read-out covers
  population: {
    search_events: { live: number; simulated: number }
    match_events: { live: number; simulated: number }
  }
  station_distance: {
    cohort_km: number
    searches: number
    searches_with_alternatives: number
    alternatives_shown: number
    alternatives_selected: number
    selection_rate: number | null
    avg_extra_km: number | null
    abandonment_rate: number | null
  }[]
  degradation: {
    current_level: number
    searches_live: number
    searches_cache: number
    cache_share: number | null
    matches_served: number
    matches_paused: number
    note: string
  }
  matching: {
    strategy: string
    offers_with_matches: number
    accepted: number
    acceptance_rate: number | null
    avg_matches_offered: number | null
    avg_group_size: number | null
    avg_pickup_km: number | null
    avg_day_shift: number | null
    avg_time_gap_min: number | null
  }[]
  matching_legacy_offers_excluded: number // offers made under the earlier rules, left out of the A/B
}

export async function fetchExperiments(visitors: ExperimentVisitors, signal?: AbortSignal): Promise<ExperimentsSummary> {
  return json(await fetch(`/api/experiments/summary?source=${visitors}`, { headers: userHeaders(), signal }))
}

export type BenchmarkScenario = {
  name: string
  pickup: { code: string; name: string }
  date: string
  window: string
  exact: { found: number; group_size: number; fare_each: number }
  flexible: {
    found: number
    group_size: number
    fare_each: number
    avg_pickup_km: number | null
    avg_day_shift: number | null
    avg_time_gap_min: number | null
  }
  flexible_only: number
}

export type MatchingBenchmark = {
  source: 'simulated'
  kind: string
  config: { max_matches: number; exact_pickup_km: number; flex_pickup_km: number; date_flex_days: number; time_window_min: number }
  route: string
  scenarios: BenchmarkScenario[]
  summary: {
    scenarios: number
    found_by_exact: number
    found_by_flexible: number
    rescued: number
    still_empty: number
    extra_matches: number
    extra_avg_pickup_km: number | null
    extra_avg_day_shift: number | null
    extra_avg_time_gap_min: number | null
    avg_fare_saving_each: number | null
  }
}

export async function fetchMatchingBenchmark(signal?: AbortSignal): Promise<MatchingBenchmark> {
  return json(await fetch('/api/experiments/matching-benchmark', { headers: userHeaders(), signal }))
}

export type DayAvailability = {
  date: string
  options: number
  with_seats: number
  trains_with_seats: number
  buses_with_seats: number
  cheapest_with_seats: number | null
}

export type DateStrip = { source: 'simulated'; origin: Station; destination: Station; center: string; days: DayAvailability[] }

export async function fetchDateStrip(q: SearchQuery, signal?: AbortSignal): Promise<DateStrip> {
  const params = new URLSearchParams({ origin: q.origin, dest: q.dest, date: q.date, days: '3' })
  return json(await fetch(`/api/search/dates?${params}`, { headers: userHeaders(), signal }))
}

/** Read `text` aloud (Sarvam Bulbul). Resolves to WAV audio; rejects with the server's reason. */
export async function speak(text: string, language: string, date?: string): Promise<Blob> {
  const resp = await fetch('/api/speak', {
    method: 'POST',
    headers: userHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ text, language, date }),
  })
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // not JSON
    }
    throw new Error(detail)
  }
  return resp.blob()
}
