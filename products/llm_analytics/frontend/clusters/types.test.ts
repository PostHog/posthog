import { getTimestampBoundsFromRunId } from './types'

describe('getTimestampBoundsFromRunId', () => {
    it.each([
        // Run ID generated at midnight UTC should return that UTC day's bounds
        {
            runId: '2_20260122_000043',
            expectedDayStart: '2026-01-22 00:00:00',
            expectedDayEnd: '2026-01-22 23:59:59',
            description: 'midnight UTC run',
        },
        // Run ID generated mid-day UTC
        {
            runId: '112495_20260121_033113',
            expectedDayStart: '2026-01-21 00:00:00',
            expectedDayEnd: '2026-01-21 23:59:59',
            description: 'mid-day UTC run',
        },
        // Run ID with optional label suffix
        {
            runId: '123_20260115_143022_experiment_v2',
            expectedDayStart: '2026-01-15 00:00:00',
            expectedDayEnd: '2026-01-15 23:59:59',
            description: 'run with label suffix',
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
