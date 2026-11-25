import { useCallback, useEffect, useRef, useState } from 'react'

// Sarvam's REST speech-to-text accepts short clips only; stop a bit before the limit.
export const MAX_RECORD_SECONDS = 25

export type RecorderState = 'idle' | 'recording'

export function useRecorder(onRecorded: (audio: Blob) => void) {
  const [state, setState] = useState<RecorderState>('idle')
  const [seconds, setSeconds] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const recorder = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const chunks = useRef<Blob[]>([])
  const timer = useRef<number | undefined>(undefined)
  // Keep the latest callback without restarting the recorder when it changes.
  const callback = useRef(onRecorded)
  useEffect(() => {
    callback.current = onRecorded
  }, [onRecorded])

  const cleanup = useCallback(() => {
    window.clearInterval(timer.current)
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null
    recorder.current = null
    setState('idle')
  }, [])

  const stop = useCallback(() => {
    if (recorder.current && recorder.current.state !== 'inactive') recorder.current.stop()
  }, [])

  const start = useCallback(async () => {
    setError(null)
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('This browser cannot record audio. Use the file upload instead.')
      return
    }
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
    } catch (e) {
      const denied = e instanceof DOMException && e.name === 'NotAllowedError'
      setError(
        denied
          ? 'Microphone permission was denied. Allow it in the browser, or use the file upload.'
          : 'No microphone available. Use the file upload instead.',
      )
      return
    }

    chunks.current = []
    const mr = new MediaRecorder(stream.current)
    mr.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.current.push(e.data)
    }
    mr.onstop = () => {
      const blob = new Blob(chunks.current, { type: mr.mimeType || 'audio/webm' })
      cleanup()
      if (blob.size > 0) callback.current(blob)
    }
    recorder.current = mr
    mr.start()

    setSeconds(0)
    setState('recording')
    const startedAt = Date.now()
    timer.current = window.setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000)
      setSeconds(elapsed)
      if (elapsed >= MAX_RECORD_SECONDS) stop()
    }, 250)
  }, [cleanup, stop])

  // Release the mic if the component unmounts mid-recording.
  useEffect(() => () => {
    window.clearInterval(timer.current)
    stream.current?.getTracks().forEach((t) => t.stop())
  }, [])

  return { state, seconds, error, start, stop }
}
