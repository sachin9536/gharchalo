import { useEffect, useState } from 'react'

// Tatkal booking opens the day before the journey: AC classes at 10:00, non-AC (Sleeper) at 11:00.
// Released behind the Flagsmith flag `tatkal_countdown` (only visitors it is on for see this).

const OPEN = [
  { label: 'AC', hour: 10 },
  { label: 'Sleeper', hour: 11 },
]

function opening(journeyDate: string, hour: number): Date {
  const d = new Date(`${journeyDate}T00:00:00`)
  d.setDate(d.getDate() - 1)
  d.setHours(hour, 0, 0, 0)
  return d
}

function until(ms: number): string {
  const minutes = Math.max(0, Math.round(ms / 60_000))
  const d = Math.floor(minutes / 1440)
  const h = Math.floor((minutes % 1440) / 60)
  const m = minutes % 60
  return d ? `${d}d ${h}h ${m}m` : h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`
}

const stamp = (d: Date) =>
  `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}T` +
  `${String(d.getHours()).padStart(2, '0')}${String(d.getMinutes()).padStart(2, '0')}00`

/** A calendar file with a 10-minute reminder before the AC window opens. */
function calendarFile(journeyDate: string, route: string): Blob {
  const opens = opening(journeyDate, OPEN[0].hour)
  const start = new Date(opens.getTime() - 10 * 60_000)
  const end = new Date(opens.getTime() + 60 * 60_000)
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//GharChalo//Tatkal reminder//EN',
    'BEGIN:VEVENT',
    `UID:tatkal-${journeyDate}-${route.replace(/\W+/g, '-')}@gharchalo`,
    `DTSTAMP:${stamp(new Date())}`,
    `DTSTART:${stamp(start)}`,
    `DTEND:${stamp(end)}`,
    `SUMMARY:Tatkal opens: ${route}`,
    'DESCRIPTION:Tatkal booking opens: AC 10:00\\, Sleeper 11:00. Have your passenger details ready.',
    'BEGIN:VALARM',
    'TRIGGER:-PT10M',
    'ACTION:DISPLAY',
    'DESCRIPTION:Tatkal opens in 10 minutes',
    'END:VALARM',
    'END:VEVENT',
    'END:VCALENDAR',
  ]
  return new Blob([lines.join('\r\n')], { type: 'text/calendar' })
}

export default function TatkalCountdown({ date, origin, destination }: { date: string; origin: string; destination: string }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(timer)
  }, [])

  const route = `${origin} to ${destination}`
  const windows = OPEN.map((w) => ({ ...w, at: opening(date, w.hour) }))
  const next = windows.find((w) => w.at.getTime() > now)
  const day = windows[0].at.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })

  const download = () => {
    const url = URL.createObjectURL(calendarFile(date, route))
    const a = document.createElement('a')
    a.href = url
    a.download = `tatkal-${date}.ics`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="tatkal">
      <span className="tatkal-icon" aria-hidden="true">
        ⏰
      </span>
      <div className="tatkal-body">
        <span className="tag beta">beta</span>
        {next ? (
          <>
            <strong>Tatkal for this journey opens in {until(next.at.getTime() - now)}</strong>
            <span className="muted small">
              {day}: AC at 10:00, Sleeper at 11:00. Tatkal seats often sell out within minutes.
            </span>
          </>
        ) : (
          <>
            <strong>Tatkal booking for this journey is open now</strong>
            <span className="muted small">It opened {day} (AC 10:00, Sleeper 11:00).</span>
          </>
        )}
      </div>
      {next && (
        <button className="ghost" onClick={download}>
          📅 Remind me
        </button>
      )}
    </div>
  )
}
