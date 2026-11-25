import { useEffect, useRef, useState } from 'react'
import { speak } from './api'
import type { SpokenLang } from './speech'

type State = { kind: 'idle' } | { kind: 'loading' } | { kind: 'playing' } | { kind: 'error'; message: string }

/** "Read aloud" with a Hindi / English choice. Plays once on its own when `autoPlay` is set (after voice). */
export default function ReadAloud({
  textFor,
  date,
  initialLang,
  autoPlay,
  disabledReason,
}: {
  textFor: (lang: SpokenLang) => string
  date: string
  initialLang: SpokenLang
  autoPlay: boolean
  disabledReason: string | null
}) {
  const [lang, setLang] = useState<SpokenLang>(initialLang)
  const [state, setState] = useState<State>({ kind: 'idle' })
  const audio = useRef<HTMLAudioElement | null>(null)
  const url = useRef<string | null>(null)
  const autoPlayed = useRef(false)

  const stop = () => {
    audio.current?.pause()
    audio.current = null
    if (url.current) URL.revokeObjectURL(url.current)
    url.current = null
  }

  const play = async (which: SpokenLang) => {
    stop()
    setState({ kind: 'loading' })
    try {
      const blob = await speak(textFor(which), which, date)
      url.current = URL.createObjectURL(blob)
      const el = new Audio(url.current)
      audio.current = el
      el.onended = () => setState({ kind: 'idle' })
      await el.play()
      setState({ kind: 'playing' })
    } catch (e) {
      // NotAllowedError = the browser blocked autoplay; the button still works.
      const blocked = e instanceof DOMException && e.name === 'NotAllowedError'
      setState(blocked ? { kind: 'idle' } : { kind: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }

  useEffect(() => {
    if (autoPlay && !disabledReason && !autoPlayed.current) {
      autoPlayed.current = true
      const timer = window.setTimeout(() => void play(initialLang), 0)
      return () => window.clearTimeout(timer)
    }
    // play/initialLang are intentionally read once: this only handles the first, automatic reply
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoPlay, disabledReason])

  useEffect(() => () => stop(), [])

  if (disabledReason) {
    return (
      <span className="readaloud muted small" title={disabledReason}>
        🔇 {disabledReason}
      </span>
    )
  }

  return (
    <span className="readaloud">
      {state.kind === 'playing' ? (
        <button
          className="ghost"
          onClick={() => {
            stop()
            setState({ kind: 'idle' })
          }}
        >
          ⏹ Stop
        </button>
      ) : (
        <button className="ghost" onClick={() => void play(lang)} disabled={state.kind === 'loading'}>
          {state.kind === 'loading' ? '… Preparing' : '🔊 Read aloud'}
        </button>
      )}
      <span className="lang-toggle" role="group" aria-label="Spoken language">
        {(['en', 'hi'] as const).map((l) => (
          <button key={l} className={l === lang ? 'on' : ''} aria-pressed={l === lang} onClick={() => setLang(l)}>
            {l === 'en' ? 'EN' : 'हिं'}
          </button>
        ))}
      </span>
      {state.kind === 'error' && <span className="bad small"> {state.message}</span>}
    </span>
  )
}
