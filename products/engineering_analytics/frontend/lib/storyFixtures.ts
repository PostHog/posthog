// Story-only fixture builders. App code never imports this file.

import type { WorkflowHealthBucketApi, WorkflowHealthItemApi } from '../generated/api.schemas'

function sevenDayBuckets(): WorkflowHealthBucketApi[] {
    return [0, 1, 2, 3, 4, 5, 6].map((day) => ({
        bucket_start: `2026-06-${25 + day}T00:00:00Z`,
        run_count: 44 + day,
        completed: 40 + day,
        successes: 40 + day,
        failures: 0,
    }))
}

/** A healthy workflow row. Pass the fields a story needs to differ; the rest stay plausible. */
export function workflowHealthItem(
    overrides: Partial<WorkflowHealthItemApi> & { workflow_name: string }
): WorkflowHealthItemApi {
    return {
        repo: { provider: 'github', owner: 'PostHog', name: 'posthog' },
        run_count: 320,
        successful_run_count: 304,
        conclusive_run_count: 320,
        success_rate: 0.95,
        success_rate_prev: 0.92,
        p50_seconds: 540,
        p95_seconds: 1680,
        last_failure_at: null,
        latest_run_failed: false,
        latest_run_conclusion: 'success',
        latest_run_id: 123456,
        latest_run_attempt: 1,
        granularity: 'day',
        billable_minutes: 2880,
        estimated_cost_usd: 96,
        rerun_cycles: 6,
        merge_queue_run_count: 0,
        buckets: sevenDayBuckets(),
        ...overrides,
    }
}
