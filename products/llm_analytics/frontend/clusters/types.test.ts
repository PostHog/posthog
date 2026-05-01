import { getJobIdFromRunId, getLevelFromRunId, getTimestampBoundsFromRunId, parseClusterMetrics } from './types'

describe('getLevelFromRunId', () => {
    it.each([
        { runId: '2_trace_20260122_000043', expected: 'trace', description: 'trace-level run' },
        { runId: '112495_generation_20260121_033113', expected: 'generation', description: 'generation-level run' },
        {
            runId: '1_evaluation_20260415_220657_019d92dc-3657-70b0-9a46-8c89b4a56b3c',
            expected: 'evaluation',
            description: 'evaluation-level run with job id suffix',
        },
        { runId: '123_trace_20260115_143022_experiment_v2', expected: 'trace', description: 'trace run with suffix' },
        { runId: 'invalid_runid', expected: 'trace', description: 'invalid format defaults to trace' },
        { runId: '123_unknown_20260101_000000', expected: 'trace', description: 'unknown level defaults to trace' },
    ])('returns $expected for $description', ({ runId, expected }) => {
        expect(getLevelFromRunId(runId)).toBe(expected)
    })
})

describe('parseClusterMetrics', () => {
    it('normalizes snake_case backend fields to camelCase frontend fields', () => {
        const raw = {
            avg_cost: 0.012,
            avg_latency: 250.5,
            avg_tokens: 650,
            total_cost: 1.2,
            error_rate: 0.1,
            error_count: 2,
            item_count: 20,
            pass_rate: 0.85,
            na_rate: 0.05,
            dominant_evaluation_name: 'Accuracy',
            dominant_runtime: 'llm_judge',
            avg_judge_cost: 0.0009,
        }
        expect(parseClusterMetrics(raw)).toEqual({
            avgCost: 0.012,
            avgLatency: 250.5,
            avgTokens: 650,
            totalCost: 1.2,
            errorRate: 0.1,
            errorCount: 2,
            itemCount: 20,
            passRate: 0.85,
            naRate: 0.05,
            dominantEvaluationName: 'Accuracy',
            dominantRuntime: 'llm_judge',
            avgJudgeCost: 0.0009,
        })
    })

    it('defaults missing eval-only fields to null so trace/generation runs parse cleanly', () => {
        // Trace/generation runs won't include the eval-only keys; they should
        // come back as null, not undefined, so chip rendering checks work uniformly.
        const raw = { avg_cost: 0.01, error_count: 0, item_count: 5 }
        const parsed = parseClusterMetrics(raw)!
        expect(parsed.passRate).toBeNull()
        expect(parsed.naRate).toBeNull()
        expect(parsed.dominantEvaluationName).toBeNull()
        expect(parsed.dominantRuntime).toBeNull()
        expect(parsed.avgJudgeCost).toBeNull()
    })

    it('returns null when the cluster has no metrics dict (trace/generation aggregates activity may have failed)', () => {
        expect(parseClusterMetrics(null)).toBeNull()
        expect(parseClusterMetrics(undefined)).toBeNull()
        expect(parseClusterMetrics('not an object')).toBeNull()
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

describe('getJobIdFromRunId', () => {
    it.each([
        {
            runId: '2_trace_20260122_000043_019cb7f3-a123-7bde-b699-6fa50502196c',
            expected: '019cb7f3-a123-7bde-b699-6fa50502196c',
            description: 'returns UUID job_id',
        },
        {
            runId: '2_generation_20260305_114422_019cb7f3-a126-7809-bffc-7f13bffe1325',
            expected: '019cb7f3-a126-7809-bffc-7f13bffe1325',
            description: 'returns UUID job_id for generation level',
        },
        {
            runId: '2_trace_20260122_000043_019cb7f3-a123-7bde-b699-6fa50502196c_experiment',
            expected: '019cb7f3-a123-7bde-b699-6fa50502196c',
            description: 'extracts UUID job_id even with trailing run_label',
        },
        {
            runId: '2_trace_20260122_000043',
            expected: null,
            description: 'returns null when no job_id present',
        },
        {
            runId: '2_trace_20260122_000043_baseline',
            expected: null,
            description: 'returns null for non-UUID suffix',
        },
    ])('returns $expected for $description', ({ runId, expected }) => {
        expect(getJobIdFromRunId(runId)).toBe(expected)
    })
})
