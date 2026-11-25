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
