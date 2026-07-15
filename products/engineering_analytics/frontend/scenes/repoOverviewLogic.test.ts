import type { RepoOverviewApi } from '../generated/api.schemas'
import { buildSuccessfulPrWorkflowDurationComparison } from './repoOverviewLogic'

describe('repoOverviewLogic', () => {
    it('preserves missing buckets as gaps and marks the incomplete tail', () => {
        const comparison = buildSuccessfulPrWorkflowDurationComparison({
            successful_pr_workflow_duration_p50_seconds: 600,
            successful_pr_workflow_duration_p50_seconds_prev: 720,
            successful_pr_workflow_duration_p95_seconds: 1800,
            successful_pr_workflow_duration_p95_seconds_prev: 2100,
            successful_pr_workflow_duration_sample_count: 12,
            successful_pr_workflow_duration_sample_count_prev: 10,
            successful_pr_workflow_duration_series_granularity: 'day',
            successful_pr_workflow_duration_series: [
                {
                    bucket_start: '2026-07-01T00:00:00Z',
                    p50_seconds: 540,
                    p95_seconds: 1500,
                    sample_count: 5,
                    is_partial: false,
                },
                {
                    bucket_start: '2026-07-02T00:00:00Z',
                    p50_seconds: null,
                    p95_seconds: null,
                    sample_count: 0,
                    is_partial: false,
                },
                {
                    bucket_start: '2026-07-03T00:00:00Z',
                    p50_seconds: 600,
                    p95_seconds: 1800,
                    sample_count: 7,
                    is_partial: true,
                },
            ],
        } as RepoOverviewApi)

        expect(comparison).not.toBeNull()
        expect(comparison?.p50Seconds[1]).toBeNaN()
        expect(comparison?.p95Seconds[1]).toBeNaN()
        expect(comparison?.sampleCounts).toEqual([5, 0, 7])
        expect(comparison?.partialFromIndex).toBe(1)
        expect(comparison?.p95SecondsCurrent).toBe(1800)
        expect(comparison?.p95SecondsPrevious).toBe(2100)
    })
})
