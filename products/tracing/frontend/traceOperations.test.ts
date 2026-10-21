import { makeSpan } from './__mocks__/span'
import { compareRowKey } from './compareUtils'
import { summarizeTraceOperations } from './traceOperations'
import type { Span } from './types'

const TRACE_START_MS = Date.parse('2026-09-03T10:00:00.000Z')

function opSpan(id: string, service_name: string, name: string, offsetMs: number, durationMs: number): Span {
    return makeSpan({
        uuid: id,
        span_id: id,
        service_name,
        name,
        timestamp: new Date(TRACE_START_MS + offsetMs).toISOString(),
        duration_nano: durationMs * 1_000_000,
    })
}

describe('summarizeTraceOperations', () => {
    it('groups by service and span name, sorts by total, and derives count, total, avg, p50 and share', () => {
        // The input order differs from the expected output order, and the cache durations are
        // unsorted, so the test fails if the operation sort or the per-group duration sort is dropped.
        const summary = summarizeTraceOperations([
            opSpan('gateway', 'gateway', 'GET /x', 3, 5),
            opSpan('cache-3', 'web', 'cache GET', 40, 60),
            opSpan('db', 'db', 'SELECT', 2, 50),
            opSpan('root', 'web', 'GET /x', 0, 100),
            opSpan('cache-1', 'web', 'cache GET', 1, 10),
            opSpan('cache-2', 'web', 'cache GET', 15, 20),
        ])

        expect(summary.spanCount).toBe(6)
        expect(summary.traceDurationNano).toBe(100_000_000)
        expect(summary.operations.map((o) => [o.service_name, o.name, o.count])).toEqual([
            ['web', 'GET /x', 1],
            ['web', 'cache GET', 3],
            ['db', 'SELECT', 1],
            ['gateway', 'GET /x', 1],
        ])
        expect(summary.operations[1]).toMatchObject({
            key: compareRowKey({ service_name: 'web', name: 'cache GET' }),
            total_duration_nano: 90_000_000,
            avg_duration_nano: 30_000_000,
            p50_duration_nano: 20_000_000,
            share: 0.9,
        })
    })

    it.each<[number[], number]>([
        [[10, 20, 30], 20],
        [[10, 20, 30, 40], 25],
    ])('p50 is the median (%j ms)', (durationsMs, expectedMs) => {
        const spans = durationsMs.map((ms, i) => opSpan(`span-${i}`, 'web', 'cache GET', 0, ms))

        expect(summarizeTraceOperations(spans).operations[0].p50_duration_nano).toBe(expectedMs * 1_000_000)
    })

    it('returns an empty summary for no spans and a zero share when the trace has no duration', () => {
        expect(summarizeTraceOperations([])).toEqual({ operations: [], traceDurationNano: 0, spanCount: 0 })

        const summary = summarizeTraceOperations([opSpan('root', 'web', 'GET /x', 0, 0)])
        expect(summary.traceDurationNano).toBe(0)
        expect(summary.operations[0].share).toBe(0)
    })
})
