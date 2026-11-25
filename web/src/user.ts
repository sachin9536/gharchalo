// An anonymous, stable id for this browser. Flagsmith needs it so a person stays
// in the same experiment cohort (5 / 15 / 30 km) every time they come back.
// For side-by-side demos, append ?as=demo-5km (or demo-15km / demo-30km) to the URL.

const KEY = 'gharchalo.userId'

export function getUserId(): string {
  try {
    const asUser = new URLSearchParams(window.location.search).get('as')?.trim()
    if (asUser) return asUser
  } catch {
    // non-browser context
  }
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
