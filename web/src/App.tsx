import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchConfig,
  parseText,
  postVoice,
  searchJourneys,
  type ClientConfig,
  type Journey,
  type SearchQuery,
  type SearchResponse,
  type StationRef,
  type VoiceResponse,
} from './api'
import { DEMO_DATE, EXAMPLE_PHRASES } from './demo'
import { chipDate, longDate } from './format'
import { loadRecent, saveRecent, withRecent } from './recent'
import Results, { ResultsSkeleton } from './Results'
import TypedSearch from './TypedSearch'
import { readUrl, writeUrl } from './urlstate'
import { MAX_RECORD_SECONDS, useRecorder } from './useRecorder'
import { toWav16kMono } from './wav'
import Experiments from './Experiments'
import Welcome from './Welcome'
import './App.css'

type Status = { kind: 'idle' } | { kind: 'working'; step: string } | { kind: 'error'; message: string }
type Mode = 'speak' | 'type'
type SearchOutcome = { key: string; route: string; data?: SearchResponse; error?: string }

function journeyQuery(j: Journey): SearchQuery | null {
  if (j.origin?.code && j.destination?.code && j.date) {
    return { origin: j.origin.code, dest: j.destination.code, date: j.date }
  }
  return null
}

const FALLBACK_LABEL: Record<Journey['fallback_mode'], string> = {
  train: 'Train only',
  shared_cab: 'Train, then shared cab',
  any: 'Any option',
}

function StationLine({ label, station }: { label: string; station: StationRef | null }) {
  return (
    <div className="row">
      <span className="label">{label}</span>
      {station ? (
        <span>
          {station.name ? (
            <>
              <strong>{station.name}</strong> <code>{station.code}</code>
              <span className="muted"> heard as “{station.spoken}”</span>
            </>
          ) : (
            <span className="bad">“{station.spoken}” is not a station we know</span>
          )}
        </span>
      ) : (
        <span className="bad">not understood</span>
      )}
    </div>
  )
}

const STEPS = ['Listen', 'Understand', 'Find options']

function Stepper({ stage }: { stage: number }) {
  return (
    <ol className="stepper" aria-label="Progress">
      {STEPS.map((s, i) => (
        <li key={s} className={i < stage ? 'done' : i === stage ? 'active' : ''} aria-current={i === stage ? 'step' : undefined}>
          <span className="dot">{i < stage ? '✓' : i + 1}</span>
          {s}
        </li>
      ))}
    </ol>
  )
}

export default function App() {
  // A search can arrive in the URL (shared link, refresh).
  const [initial] = useState(readUrl)
  const [mode, setMode] = useState<Mode>(initial.query ? 'type' : 'speak')
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const [result, setResult] = useState<VoiceResponse | null>(null)
  const [edited, setEdited] = useState('')
  // The typed form mirrors whatever was searched last, including voice searches.
  const [form, setForm] = useState<SearchQuery>(initial.query ?? { origin: 'SBC', dest: 'HYB', date: DEMO_DATE })
  const [labels, setLabels] = useState<Record<string, string>>({})
  const [query, setQuery] = useState<SearchQuery | null>(initial.query)
  // null = Flagsmith's 5 / 15 / 30 km cohort decides on the server, per user.
  const [maxKmOverride, setMaxKmOverride] = useState<number | null>(initial.km)
  const [withConnections, setWithConnections] = useState(false)
  const [outcome, setOutcome] = useState<SearchOutcome | null>(null)
  const [cfg, setCfg] = useState<ClientConfig | null>(null)
  const [refreshTick, setRefreshTick] = useState(0)
  const [recent, setRecent] = useState<SearchQuery[]>(loadRecent)
  const [editing, setEditing] = useState(false) // small screens: search form expanded again
  const [toast, setToast] = useState<string | null>(null)
  const toastTimer = useRef<number | undefined>(undefined)
  const [view, setView] = useState<'search' | 'experiments'>(() => (window.location.hash === '#experiments' ? 'experiments' : 'search'))
  useEffect(() => {
    const onHash = () => setView(window.location.hash === '#experiments' ? 'experiments' : 'search')
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const textOnly = cfg?.interaction_mode === 'text_only'
  const effectiveMode: Mode = textOnly ? 'type' : mode

  // Poll /api/config so dashboard flag changes (tatkal_level, interaction_mode) land live.
  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const load = () => {
      fetchConfig(query?.date ?? form.date, controller.signal)
        .then((c) => {
          if (active) setCfg(c)
        })
        .catch(() => {
          // Safe defaults remain in place if /config is unreachable.
        })
    }
    load()
    const timer = window.setInterval(load, 15_000)
    return () => {
      active = false
      controller.abort()
      window.clearInterval(timer)
    }
  }, [query?.date, form.date])

  // Experiment A (level 0 vs level 1): refresh active search results on the poll_s cadence from Flagsmith.
  const pollS = cfg?.poll_s ?? 30
  useEffect(() => {
    if (!query) return
    const timer = window.setInterval(() => setRefreshTick((t) => t + 1), pollS * 1000)
    return () => window.clearInterval(timer)
  }, [query, pollS])

  // Results are stored with the key they answer, so "idle" and "loading" are
  // derived (no outcome for the current key yet) rather than set inside the effect.
  const route = query ? `${query.origin}|${query.dest}|${query.date}` : null
  const searchKey = route ? `${route}|${maxKmOverride ?? 'auto'}|${withConnections}|${refreshTick}` : null
  const settled = searchKey !== null && outcome?.key === searchKey ? outcome : null
  const searching = searchKey !== null && settled === null
  // While a refinement of the same route loads (distance, journeys with changes, a live
  // refresh), keep the previous results on screen instead of flashing a loader.
  const shown = settled?.data ?? (searching && outcome?.route === route ? outcome?.data : undefined)

  useEffect(() => {
    if (!query || !searchKey || !route) return
    const controller = new AbortController()
    searchJourneys(query, maxKmOverride, withConnections, controller.signal)
      .then((data) => setOutcome({ key: searchKey, route, data }))
      .catch((e) => {
        if (e instanceof DOMException && e.name === 'AbortError') return
        setOutcome({ key: searchKey, route, error: e instanceof Error ? e.message : String(e) })
      })
    return () => controller.abort()
  }, [query, maxKmOverride, withConnections, searchKey, route])

  // Keep the address bar in step with the search, so it can be shared.
  useEffect(() => {
    writeUrl(query, maxKmOverride)
  }, [query, maxKmOverride])

  const notify = useCallback((message: string) => {
    setToast(message)
    window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(null), 2600)
  }, [])

  // Functional update, so callers that captured an older render never overwrite newer history.
  const remember = (q: SearchQuery) => setRecent((prev) => withRecent(prev, q))
  useEffect(() => {
    saveRecent(recent)
  }, [recent])

  const show = (r: VoiceResponse) => {
    setResult(r)
    setEdited(r.transcript)
    setStatus({ kind: 'idle' })
    const q = journeyQuery(r.journey)
    setQuery(q)
    setWithConnections(false)
    setEditing(false)
    if (q) {
      setForm(q)
      remember(q)
      const named: Record<string, string> = {}
      for (const s of [r.journey.origin, r.journey.destination]) {
        if (s?.code && s.name) named[s.code] = s.name
      }
      setLabels(named)
    }
  }

  const searchTyped = (q: SearchQuery) => {
    setResult(null)
    setStatus({ kind: 'idle' })
    setForm(q)
    setQuery(q)
    setWithConnections(false)
    setEditing(false)
    remember(q)
  }
  const fail = (e: unknown) =>
    setStatus({ kind: 'error', message: e instanceof Error ? e.message : String(e) })

  const sendAudio = useCallback(async (audio: Blob, name: string) => {
    setResult(null)
    setQuery(null)
    try {
      setStatus({ kind: 'working', step: 'Preparing audio…' })
      let wav: Blob
      let filename = 'recording.wav'
      try {
        wav = await toWav16kMono(audio)
      } catch {
        // Browser could not decode it (odd format); let the server try the raw file.
        wav = audio
        filename = name
      }
      setStatus({ kind: 'working', step: 'Transcribing and understanding your request…' })
      show(await postVoice(wav, filename))
    } catch (e) {
      fail(e)
    }
  }, [])

  const recorder = useRecorder((blob) => void sendAudio(blob, 'recording.webm'))
  const busy = status.kind === 'working'
  const recording = recorder.state === 'recording'

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // allow picking the same file twice
    if (file) void sendAudio(file, file.name)
  }

  const understand = async (text: string) => {
    setStatus({ kind: 'working', step: 'Understanding your request…' })
    try {
      show(await parseText(text))
    } catch (e) {
      fail(e)
    }
  }

  const tryPhrase = (phrase: string) => {
    setResult(null)
    setQuery(null)
    void understand(phrase)
  }

  const modify = () => {
    setMode('type')
    setEditing(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const j = result?.journey
  const ready = j && j.missing.length === 0
  const stage = recording ? 0 : busy ? 1 : result && searching && !shown ? 2 : null
  const hasSearched = query !== null || result !== null
  const compact = hasSearched && !editing
  const empty = !hasSearched && !busy && !recording
  const summaryRoute = shown ? `${shown.origin.city} → ${shown.destination.city}` : query ? `${query.origin} → ${query.dest}` : 'Your search'

  // Demand banner (Flagsmith tatkal_level) and the priority note for travel within 48 hours.
  const level = shown?.tatkal_level ?? cfg?.tatkal_level ?? 0
  let banner: { kind: 'warn' | 'nudge'; text: string } | null = null
  if (level >= 1) {
    banner = {
      kind: 'warn',
      text:
        level >= 3
          ? 'Peak Tatkal load (Level 3): serving cached search results · co-traveller matching paused.'
          : level === 2
            ? 'High demand (Level 2): multi-leg planning paused to keep direct search fast.'
            : `High demand (Level 1): results refresh every ${pollS}s.`,
    }
  } else if (cfg?.urgent && query) {
    banner = { kind: 'nudge', text: 'Priority service active (travel within 48h · Level 0)' }
  }

  const hero = (
    <header className="hero">
      <div className="hero-inner">
        <div className="brand">
          <span className="logo" aria-hidden="true">
            🪔
          </span>
          <h1>GharChalo</h1>
        </div>
        <p className="tagline">Festive season travel, made simple. Tell us where home is, we'll find the way.</p>
        <ul className="trust">
          <li>🚆 Trains</li>
          <li>🚌 Buses</li>
          <li>🚕 Shared cabs</li>
          <li>🗣 Hindi, Hinglish, English</li>
        </ul>
        <nav className="topnav" aria-label="Main">
          <a href="#" aria-current={view === 'search' ? 'page' : undefined}>
            Find a way home
          </a>
          <a href="#experiments" aria-current={view === 'experiments' ? 'page' : undefined}>
            Experiments
          </a>
        </nav>
      </div>
    </header>
  )
  const footer = (
    <footer className="foot muted small">
      All trains, buses, fares and travellers shown here are simulated for FestiveHacks 2026. They are not live IRCTC or
      operator data.
    </footer>
  )

  if (view === 'experiments') {
    return (
      <>
        {hero}
        <main className="exp-main">
          <Experiments />
        </main>
        {footer}
      </>
    )
  }

  return (
    <>
      {hero}

      <div className="layout">
        <aside className={`panel ${compact ? 'compact' : ''}`}>
          {compact && (
            <button className="panel-summary" onClick={() => setEditing(true)} aria-label="Edit your search">
              <span>
                <strong>{summaryRoute}</strong>
                {query && <span className="muted small"> · {chipDate(query.date)}</span>}
              </span>
              <span className="edit-link">Edit</span>
            </button>
          )}

          <section className="card search-card">
            <div className="segmented" role="tablist" aria-label="How do you want to search?">
              <button
                role="tab"
                aria-selected={effectiveMode === 'speak'}
                className={effectiveMode === 'speak' ? 'on' : ''}
                onClick={() => setMode('speak')}
                disabled={textOnly}
              >
                🎙 Speak
              </button>
              <button
                role="tab"
                aria-selected={effectiveMode === 'type'}
                className={effectiveMode === 'type' ? 'on' : ''}
                onClick={() => setMode('type')}
              >
                ⌨️ Type
              </button>
            </div>

            {effectiveMode === 'speak' ? (
              <div className="speak">
                <button
                  className={`mic-orb ${recording ? 'recording' : ''}`}
                  onClick={recording ? recorder.stop : () => void recorder.start()}
                  disabled={busy}
                  aria-label={recording ? 'Stop recording' : 'Start recording'}
                >
                  <span aria-hidden="true">{recording ? '■' : '🎙'}</span>
                </button>
                <p className="mic-label">
                  {recording
                    ? `Listening… ${recorder.seconds}s of ${MAX_RECORD_SECONDS}s. Tap to stop.`
                    : status.kind === 'working'
                      ? status.step
                      : 'Tap and say where you want to go'}
                </p>
                <p className="muted small">Hindi, Hinglish, English and other Indian languages</p>
                <details className="try">
                  <summary>No microphone? Try an example</summary>
                  {EXAMPLE_PHRASES.map((p) => (
                    <button key={p} className="pill phrase" onClick={() => tryPhrase(p)} disabled={busy || recording}>
                      “{p}”
                    </button>
                  ))}
                </details>
                <label className={`upload ${busy || recording ? 'disabled' : ''}`}>
                  or upload a recording
                  <input type="file" accept="audio/*" onChange={onFile} disabled={busy || recording} />
                </label>
              </div>
            ) : (
              <TypedSearch
                value={form}
                labels={labels}
                recent={recent}
                onChange={setForm}
                onSearch={searchTyped}
                disabled={busy}
              />
            )}
          </section>
        </aside>

        <div className="content">
          {banner && <div className={`banner ${banner.kind}`}>{banner.text}</div>}
          {textOnly && (
            <div className="banner warn">
              Voice search is temporarily paused (text-only fallback). Typed search works normally.
            </div>
          )}

          {stage !== null && <Stepper stage={stage} />}
          {recorder.error && <p className="error">{recorder.error}</p>}
          {status.kind === 'error' && <p className="error">{status.message}</p>}

          {result && j && (
            <section className="card heard">
              <div className="card-head">
                <h2>🗣 We understood</h2>
                <span>
                  {result.source === 'stub' && <span className="tag">load-test stub</span>}
                  {result.language_code && <span className="tag soft">{result.language_code}</span>}
                </span>
              </div>
              {!textOnly && (
                <>
                  <textarea value={edited} onChange={(e) => setEdited(e.target.value)} rows={2} aria-label="Transcript" />
                  <div className="actions">
                    <button onClick={() => void understand(edited)} disabled={busy || !edited.trim() || edited === result.transcript}>
                      Fix the text and retry
                    </button>
                    <span className="muted small">Misheard something? Edit it, then retry.</span>
                  </div>
                </>
              )}
              <div className="journey-grid">
                <StationLine label="From" station={j.origin} />
                <StationLine label="To" station={j.destination} />
                <div className="row">
                  <span className="label">Date</span>
                  {j.date ? <strong>{longDate(j.date)}</strong> : <span className="bad">not understood</span>}
                </div>
                <div className="row">
                  <span className="label">If no train</span>
                  <span>{FALLBACK_LABEL[j.fallback_mode]}</span>
                </div>
              </div>
              {j.warnings.map((w) => (
                <p className="warn" key={w}>
                  {w}
                </p>
              ))}
              {!ready && <p className="warn">Missing: {j.missing.join(', ')}. Edit the text above and retry.</p>}
            </section>
          )}

          {searching && !shown && <ResultsSkeleton />}
          {settled?.error && <p className="error">Search failed: {settled.error}</p>}
          {shown && route && (
            <Results
              key={route}
              data={shown}
              updating={searching}
              maxKmOverride={maxKmOverride}
              allowOverride={cfg?.allow_override ?? true}
              onMaxKm={setMaxKmOverride}
              onShowConnections={() => setWithConnections(true)}
              onModify={modify}
              onNotify={notify}
              onPickDate={(date) => query && searchTyped({ ...query, date })}
              spokenLang={result?.journey.language === 'hi' ? 'hi' : 'en'}
              autoSpeak={result?.source === 'sarvam'}
              voiceOff={textOnly}
              features={cfg?.features ?? {}}
            />
          )}

          {empty && <Welcome date={form.date} onPick={searchTyped} disabled={busy} />}

          {j && (
            <details className="card raw">
              <summary>Developer view: journey JSON</summary>
              <pre>{JSON.stringify(j, null, 2)}</pre>
            </details>
          )}
        </div>
      </div>

      {footer}

      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </>
  )
}
