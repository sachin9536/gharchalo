// Reference checks for src/stats.ts.  Run: npm run check:stats   (Node 22+ strips the TypeScript types)
import { twoProportionP, verdict, wilson } from '../src/stats.ts'

const near = (a, b, tol) => Math.abs(a - b) <= tol
const checks = [
  ['wilson(50/100) is about [0.404, 0.596]', (() => { const w = wilson(50, 100); return near(w[0], 0.404, 0.002) && near(w[1], 0.596, 0.002) })()],
  ['wilson(0/20): lower bound 0, upper about 0.161', (() => { const w = wilson(0, 20); return w[0] === 0 && near(w[1], 0.161, 0.003) })()],
  ['wilson with no data is null', wilson(0, 0) === null],
  ['identical groups (40/100 vs 40/100): p = 1', near(twoProportionP(40, 100, 40, 100), 1, 1e-6)],
  ['30/100 vs 50/100: z = 2.887, two-sided p = 0.0039', near(twoProportionP(30, 100, 50, 100), 0.0039, 0.0003)],
  ['no data in one group: p is null', twoProportionP(1, 0, 1, 10) === null],
  ['10 per group is "too few", even when rates differ a lot', verdict(2, 10, 5, 10).kind === 'few'],
  ['200 per group, 20% vs 35%: real difference', verdict(40, 200, 70, 200).kind === 'real'],
  ['200 per group, 30% vs 31%: no significant difference', verdict(60, 200, 62, 200).kind === 'none'],
]
let failed = 0
for (const [name, ok] of checks) {
  if (!ok) failed++
  console.log(ok ? 'PASS' : 'FAIL', name)
}
process.exit(failed ? 1 : 0)
