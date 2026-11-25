// The sentence read aloud after a search, in Hindi or English. Kept short: TTS is billed per call and
// a reply should take a few seconds, not a minute.

export type SpokenLang = 'hi' | 'en'

export type SpokenFacts = {
  origin: string
  destination: string
  date: string // YYYY-MM-DD
  best?: { title: string; departs: string; arrives: string; fare: number; mode: string }
  cabEach: number
}

const MONTHS_HI = ['जनवरी', 'फ़रवरी', 'मार्च', 'अप्रैल', 'मई', 'जून', 'जुलाई', 'अगस्त', 'सितंबर', 'अक्टूबर', 'नवंबर', 'दिसंबर']
const MODE_HI: Record<string, string> = { train: 'ट्रेन', bus: 'बस', changes: 'बदलाव वाली यात्रा', nearby: 'पास के स्टेशन से ट्रेन' }

export function spokenSummary(f: SpokenFacts, lang: SpokenLang): string {
  const d = new Date(`${f.date}T00:00:00`)
  if (lang === 'hi') {
    const day = `${d.getDate()} ${MONTHS_HI[d.getMonth()]}`
    const head = `${f.origin} से ${f.destination}, ${day}।`
    const best = f.best
      ? ` सबसे जल्दी पहुँचने का रास्ता: ${MODE_HI[f.best.mode] ?? ''} ${f.best.title}, ${f.best.departs} पर निकलती है और ${f.best.arrives} पर पहुँचती है, किराया ${f.best.fare} रुपये।`
      : ' सीधी ट्रेन या बस में सीट नहीं है। पास के स्टेशन, बदलाव वाली यात्रा या शेयर कैब देखिए।'
    return `${head}${best} शेयर कैब में हर व्यक्ति का लगभग ${f.cabEach} रुपये।`
  }
  const day = d.toLocaleDateString('en-IN', { day: 'numeric', month: 'long' })
  const head = `${f.origin} to ${f.destination}, ${day}.`
  const best = f.best
    ? ` Quickest way home: ${f.best.title}, leaving at ${f.best.departs} and arriving at ${f.best.arrives}, ${f.best.fare} rupees.`
    : ' No direct train or bus has seats. Try a nearby station, a journey with changes, or a shared cab.'
  return `${head}${best} A shared cab costs about ${f.cabEach} rupees each.`
}
