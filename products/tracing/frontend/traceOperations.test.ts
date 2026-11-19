import { makeSpan } from './__mocks__/span'
import { compareRowKey } from './compareUtils'
import { summarizeTraceOperations } from './traceOperations'
import type { Span } from './types'

const TRACE_START_MS = Date.parse('2026-09-03T10:00:00.000Z')

function opSpan(
    id: string,
    service_name: string,
    name: string,
    offsetMs: number,
    durationMs: number,
    parent_span_id = ''
): Span {
    return makeSpan({
        uuid: id,
        span_id: id,
        parent_span_id,
        is_root_span: !parent_span_id,
        service_name,
        name,
        timestamp: new Date(TRACE_START_MS + offsetMs).toISOString(),
        duration_nano: durationMs * 1_000_000,
    })
}

describe('summarizeTraceOperations', () => {
    // root 0-100 ms ── db 10-60 ── cache-1 20-40, cache-2 30-60 (they overlap)
    //                ├─ gateway 65-90
    //                └─ cache-3 90-190 (runs past the root's end)
    it('groups by service and span name, sorts by self time, and derives count, self time, total, avg, p50 and share', () => {
        // The root has the second largest total but little self time, the input order differs from the output
        // order, and the cache durations are unsorted. So the test fails if the operations sort by total, if
        // either sort is dropped, if overlapping children count twice (db would get 0 ms), or if a child is not
        // clipped to its parent (the root would get 0 ms instead of 15 ms).
        const summary = summarizeTraceOperations([
            opSpan('cache-3', 'web', 'cache GET', 90, 100, 'root'),
            opSpan('gateway', 'gateway', 'GET /x', 65, 25, 'root'),
            opSpan('db', 'db', 'SELECT', 10, 50, 'root'),
            opSpan('root', 'web', 'GET /x', 0, 100),
            opSpan('cache-1', 'web', 'cache GET', 20, 20, 'db'),
            opSpan('cache-2', 'web', 'cache GET', 30, 30, 'db'),
        ])

        expect(summary.spanCount).toBe(6)
        expect(summary.operations.map((o) => [o.service_name, o.name, o.count, o.self_time_nano, o.share])).toEqual([
            ['web', 'cache GET', 3, 150_000_000, 0.75],
            ['gateway', 'GET /x', 1, 25_000_000, 0.125],
            ['web', 'GET /x', 1, 15_000_000, 0.075],
            ['db', 'SELECT', 1, 10_000_000, 0.05],
        ])
        expect(summary.operations[0]).toMatchObject({
            key: compareRowKey({ service_name: 'web', name: 'cache GET' }),
            total_duration_nano: 150_000_000,
            avg_duration_nano: 50_000_000,
            p50_duration_nano: 30_000_000,
        })
        // "This span" summarizes one subtree, and its shares add up to 100% of that subtree's self time too.
        const dbSubtree = summarizeTraceOperations([
            opSpan('db', 'db', 'SELECT', 10, 50, 'root'),
            opSpan('cache-1', 'web', 'cache GET', 20, 20, 'db'),
            opSpan('cache-2', 'web', 'cache GET', 30, 30, 'db'),
        ])
        expect(dbSubtree.operations.map((o) => [o.name, o.share])).toEqual([
            ['cache GET', 50 / 60],
            ['SELECT', 10 / 60],
        ])
        expect(dbSubtree.operations.reduce((sum, o) => sum + o.share, 0)).toBeCloseTo(1)
    })

    it.each<[number[], number]>([
        [[10, 20, 30], 20],
        [[10, 20, 30, 40], 25],
    ])('p50 is the median (%j ms)', (durationsMs, expectedMs) => {
        const spans = durationsMs.map((ms, i) => opSpan(`span-${i}`, 'web', 'cache GET', 0, ms))

        expect(summarizeTraceOperations(spans).operations[0].p50_duration_nano).toBe(expectedMs * 1_000_000)
    })

    it('returns an empty summary for no spans and a zero share when the spans have no self time', () => {
        expect(summarizeTraceOperations([])).toEqual({ operations: [], spanCount: 0 })

        const summary = summarizeTraceOperations([opSpan('root', 'web', 'GET /x', 0, 0)])
        expect(summary.operations[0]).toMatchObject({ self_time_nano: 0, share: 0 })
    })
})
