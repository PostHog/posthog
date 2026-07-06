import { describe, expect, it } from 'vitest'

import { percentile, summarize, type ProbeResult } from '../../evals/runner/results'

describe('eval result aggregation', () => {
    it.each([
        { values: [], p: 95, expected: null },
        { values: [100], p: 50, expected: 100 },
        { values: [100], p: 95, expected: 100 },
        { values: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], p: 50, expected: 5 },
        { values: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], p: 95, expected: 10 },
        { values: [1, 2, 3, 4], p: 95, expected: 4 },
    ])('percentile(p$p) of $values is $expected', ({ values, p, expected }) => {
        expect(percentile(values, p)).toBe(expected)
    })

    it('counts every non-ok status as failed and keeps latency math to ok+errored calls only', () => {
        const probes: ProbeResult[] = [
            { task_id: 'a', tool: 't1', status: 'ok', latency_ms: 100 },
            { task_id: 'b', tool: 't2', status: 'tool_error', latency_ms: 300 },
            { task_id: 'c', tool: 't3', status: 'refused_not_read_only' },
            { task_id: 'd', tool: 't4', status: 'skipped_not_advertised' },
        ]

        const summary = summarize({
            benchmarkVersion: 0,
            tasksTotal: 4,
            toolsReferenced: 4,
            toolMisses: [{ task_id: 'd', tool: 't4' }],
            probes,
        })

        expect(summary.probes_total).toBe(4)
        expect(summary.probes_ok).toBe(1)
        expect(summary.probes_failed).toBe(3)
        expect(summary.latency_p50_ms).toBe(100)
        expect(summary.latency_p95_ms).toBe(300)
        expect(summary.tool_misses).toHaveLength(1)
    })
})
