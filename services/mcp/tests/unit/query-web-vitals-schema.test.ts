import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/query-wrappers'

// `query-web-vitals` used to require `metric`, `percentile`, and `thresholds`.
// Agents doing ordinary per-page vitals analysis omitted the latter two (they
// have obvious defaults — p75 and the standard Google bands for the metric),
// so nearly a quarter of calls failed schema validation. These tests lock in
// that only `metric` is required, while malformed inputs are still rejected
// with an error that names the offending field.
describe('query-web-vitals tool schema', () => {
    const tool = GENERATED_TOOLS['query-web-vitals']!()

    it('accepts a metric-only call, leaving percentile/thresholds for the backend to default', () => {
        const parsed = tool.schema.safeParse({ metric: 'LCP' })

        expect(parsed.success).toBe(true)
        // Omitted, not client-defaulted — the backend derives p75 + the metric's
        // standard bands, so the query body carries neither field.
        expect(parsed.data).not.toHaveProperty('percentile')
        expect(parsed.data).not.toHaveProperty('thresholds')
    })

    it('still accepts an explicit p75 request shape', () => {
        expect(tool.schema.safeParse({ metric: 'LCP', percentile: 'p75', thresholds: [2500, 4000] }).success).toBe(true)
    })

    it.each([
        ['missing metric', {}, 'metric'],
        ['unknown metric', { metric: 'TTFB' }, 'metric'],
        ['bad percentile', { metric: 'LCP', percentile: 'p50' }, 'percentile'],
        ['thresholds too short', { metric: 'LCP', thresholds: [2500] }, 'thresholds'],
        ['thresholds too long', { metric: 'LCP', thresholds: [2500, 4000, 5000] }, 'thresholds'],
        ['non-string date_from', { metric: 'LCP', dateRange: { date_from: 7 } }, 'dateRange'],
    ])('rejects %s and points at the %s field', (_name, input, field) => {
        const parsed = tool.schema.safeParse(input)

        expect(parsed.success).toBe(false)
        expect(parsed.error!.issues.some((issue) => issue.path.includes(field))).toBe(true)
    })
})
