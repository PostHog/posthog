import { getLevelFromRunId, getTimestampBoundsFromRunId } from './types'

describe('getLevelFromRunId', () => {
    it.each([
        { runId: '2_trace_20260122_000043', expected: 'trace', description: 'trace-level run' },
        { runId: '112495_generation_20260121_033113', expected: 'generation', description: 'generation-level run' },
        { runId: '123_trace_20260115_143022_experiment_v2', expected: 'trace', description: 'trace run with suffix' },
        { runId: 'invalid_runid', expected: 'trace', description: 'invalid format defaults to trace' },
        { runId: '123_unknown_20260101_000000', expected: 'trace', description: 'unknown level defaults to trace' },
    ])('returns $expected for $description', ({ runId, expected }) => {
        expect(getLevelFromRunId(runId)).toBe(expected)
    })
})

describe('getTimestampBoundsFromRunId', () => {
    it.each([
        {
            runId: '2_trace_20260122_000043',
            expectedDayStart: '2026-01-22 00:00:00',
            expectedDayEnd: '2026-01-22 23:59:59',
            description: 'trace-level run at midnight UTC',
        },
        {
            runId: '112495_generation_20260121_033113',
            expectedDayStart: '2026-01-21 00:00:00',
            expectedDayEnd: '2026-01-21 23:59:59',
            description: 'generation-level run mid-day UTC',
        },
        {
            runId: '123_trace_20260115_143022_experiment_v2',
            expectedDayStart: '2026-01-15 00:00:00',
            expectedDayEnd: '2026-01-15 23:59:59',
            description: 'run with optional label suffix',
        },
    ])('returns correct UTC day bounds for $description', ({ runId, expectedDayStart, expectedDayEnd }) => {
        const result = getTimestampBoundsFromRunId(runId)
        expect(result.dayStart).toBe(expectedDayStart)
        expect(result.dayEnd).toBe(expectedDayEnd)
    })

    it('returns fallback bounds for invalid run ID format', () => {
        const result = getTimestampBoundsFromRunId('invalid_runid')
        // Should return some valid date range (last 7 days fallback)
        expect(result.dayStart).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/)
        expect(result.dayEnd).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/)
    })
})
