// An anonymous, stable id for this browser. Flagsmith needs it so a person stays
// in the same experiment cohort (5 / 15 / 30 km) every time they come back.

const KEY = 'gharchalo.userId'

export function getUserId(): string {
  try {
    const existing = localStorage.getItem(KEY)
    if (existing) return existing
    const id = crypto.randomUUID()
    localStorage.setItem(KEY, id)
    return id
  } catch {
    // Storage blocked (private mode): fall back to an id that lasts for this page load.
    return (memoryId ??= crypto.randomUUID())
  }
}

let memoryId: string | undefined
