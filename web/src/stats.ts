// Small, dependency-free statistics for the Experiments page.

/** Standard normal CDF (Abramowitz & Stegun 7.1.26 approximation of erf). */
function normalCdf(x: number): number {
  const t = 1 / (1 + 0.3275911 * Math.abs(x) / Math.SQRT2)
  const poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))))
  const erf = 1 - poly * Math.exp(-(x * x) / 2)
  return x >= 0 ? 0.5 * (1 + erf) : 0.5 * (1 - erf)
}

/** 95% Wilson score interval for `successes` out of `n`; null when there is no data. */
export function wilson(successes: number, n: number, z = 1.96): [number, number] | null {
  if (n <= 0) return null
  const p = successes / n
  const denom = 1 + (z * z) / n
  const centre = p + (z * z) / (2 * n)
  const margin = z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))
  return [Math.max(0, (centre - margin) / denom), Math.min(1, (centre + margin) / denom)]
}

/** Two-sided p-value of a two-proportion z-test (pooled); null when it cannot be computed. */
export function twoProportionP(x1: number, n1: number, x2: number, n2: number): number | null {
  if (n1 <= 0 || n2 <= 0) return null
  const pooled = (x1 + x2) / (n1 + n2)
  const se = Math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
  if (se === 0) return 1
  const z = (x1 / n1 - x2 / n2) / se
  return 2 * (1 - normalCdf(Math.abs(z)))
}

export const MIN_PER_GROUP = 30

export type Verdict = { kind: 'few' | 'none' | 'real'; text: string }

/** Plain-language reading of "is group A different from group B?". */
export function verdict(x1: number, n1: number, x2: number, n2: number): Verdict {
  if (Math.min(n1, n2) < MIN_PER_GROUP) {
    return { kind: 'few', text: `Not enough data yet (about ${MIN_PER_GROUP}+ per group needed)` }
  }
  const p = twoProportionP(x1, n1, x2, n2)
  if (p === null) return { kind: 'few', text: 'No data' }
  const shown = p < 0.001 ? '<0.001' : p.toFixed(3)
  return p < 0.05
    ? { kind: 'real', text: `Difference unlikely to be chance (p = ${shown})` }
    : { kind: 'none', text: `No significant difference (p = ${shown})` }
}

export const percent = (r: number | null | undefined, digits = 0) =>
  r === null || r === undefined ? '–' : `${(r * 100).toFixed(digits)}%`
