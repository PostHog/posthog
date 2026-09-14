import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type {
    GitHubSourceApi,
    WorkflowHealthItemApi,
    WorkflowJobAggregateApi,
    WorkflowRunActivityApi,
    WorkflowRunDetailApi,
    WorkflowRunnerCostApi,
} from '../generated/api.schemas'
import { workflowHealthItem } from '../lib/storyFixtures'

const SOURCES: GitHubSourceApi[] = [{ id: 'src-1', repo: 'PostHog/posthog', prefix: '' }]

const REPO = { provider: 'github', owner: 'PostHog', name: 'posthog' }
const GATE_BRANCH = 'trunk-merge/pr-4821/8f21c0de-5b44-4a19-9c07-2d6e11ab7f30'

function run(
    id: number,
    headBranch: string,
    conclusion: string | null,
    durationSeconds: number | null,
    startedAt: string,
    prNumber: number,
    runAttempt: number = 1
): WorkflowRunDetailApi {
    return {
        repo: REPO,
        id,
        workflow_name: 'Backend CI',
        head_sha: `c0ffee${id}`,
        head_branch: headBranch,
        status: conclusion === null ? 'in_progress' : 'completed',
        conclusion,
        run_started_at: startedAt,
        updated_at: startedAt,
        duration_seconds: durationSeconds,
        run_attempt: runAttempt,
        pr_number: prNumber,
        commit_pr_number: prNumber === 0 ? 4788 : null,
    }
}

// The lead column's whole state space: default-branch pushes, a PR branch, a merge-queue gate branch,
// a decisive failure, and a re-run attempt.
const RUNS: WorkflowRunDetailApi[] = [
    run(880141, 'master', 'success', 1420, '2026-07-01T08:05:00Z', 0),
    run(880152, 'feat/run-scope-groups', 'success', 1510, '2026-07-01T09:40:00Z', 4820),
    run(880163, 'feat/run-scope-groups', 'failure', 980, '2026-07-01T11:12:00Z', 4820),
    run(880163, 'feat/run-scope-groups', 'success', 1580, '2026-07-01T11:44:00Z', 4820, 2),
    run(880178, GATE_BRANCH, 'success', 1690, '2026-07-01T13:20:00Z', 4821),
    run(880190, 'master', 'success', 1380, '2026-07-01T15:02:00Z', 0),
]

const ACTIVITY: WorkflowRunActivityApi = {
    points: [1420, 1510, 980, 1580, 1690, 1380, 1455, 2210, 1340, 1520, 1610, 1290].map((duration, i) => ({
        run_id: 880100 + i,
        conclusion: i === 2 ? 'failure' : 'success',
        run_started_at: `2026-06-${26 + Math.floor(i / 2)}T${String(8 + (i % 2) * 6).padStart(2, '0')}:00:00Z`,
        duration_seconds: duration,
        head_branch: i % 3 === 0 ? 'master' : 'feat/run-scope-groups',
        pr_number: i % 3 === 0 ? 0 : 4820,
        head_sha: `c0ffee${String(i).padStart(2, '0')}`,
    })),
    truncated: false,
    limit: 500,
}

// One billable tier and one free tier, so the share bar and the "free" label both render.
const RUNNER_COSTS: WorkflowRunnerCostApi[] = [
    {
        provider: 'self_hosted',
        runner_label: 'depot-ubuntu-16',
        job_count: 184,
        billable_minutes: 2140,
        estimated_cost_usd: 61.4,
    },
    {
        provider: 'github_hosted',
        runner_label: 'ubuntu-latest',
        job_count: 42,
        billable_minutes: 310,
        estimated_cost_usd: null,
    },
]

const JOB_AGGREGATES: WorkflowJobAggregateApi[] = [
    {
        job_name: 'Python tests',
        job_count: 96,
        shard_count: 8,
        runs_in: 12,
        run_share: 1,
        queue_p50_seconds: 34,
        p50_seconds: 720,
        p95_seconds: 1180,
        failure_rate: 0.08,
        retry_job_count: 6,
        billable_minutes: 1420,
        estimated_cost_usd: 40.7,
    },
    {
        job_name: 'Migrations',
        job_count: 12,
        shard_count: 1,
        runs_in: 12,
        run_share: 1,
        queue_p50_seconds: 21,
        p50_seconds: 240,
        p95_seconds: 410,
        failure_rate: 0,
        retry_job_count: 0,
        billable_minutes: 320,
        estimated_cost_usd: 9.2,
    },
    {
        job_name: 'Async migrations check',
        job_count: 5,
        shard_count: 1,
        runs_in: 5,
        run_share: 0.42,
        queue_p50_seconds: 18,
        p50_seconds: 110,
        p95_seconds: 190,
        failure_rate: null,
        retry_job_count: 0,
        billable_minutes: null,
        estimated_cost_usd: null,
    },
]

// Only the workflow-switcher dropdown reads this, and it loads on first open.
const WORKFLOW_HEALTH: WorkflowHealthItemApi[] = ['Backend CI', 'Frontend CI', 'E2E - Playwright'].map(
    (workflowName): WorkflowHealthItemApi =>
        workflowHealthItem({
            workflow_name: workflowName,
            run_count: 312,
            successful_run_count: 292,
            conclusive_run_count: 306,
            success_rate_prev: 0.93,
            p50_seconds: 1440,
            p95_seconds: 2180,
            last_failure_at: '2026-07-01T11:12:00Z',
            latest_run_id: 880190,
            billable_minutes: 2140,
            estimated_cost_usd: 61.4,
            rerun_cycles: 4,
            merge_queue_run_count: 148,
            buckets: [],
        })
)

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Engineering Analytics/Workflow',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-02',
        featureFlags: [FEATURE_FLAGS.ENGINEERING_ANALYTICS],
        testOptions: {
            waitForSelector: '[data-attr="engineering-analytics-workflow-runs-table"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/sources/': SOURCES,
                'api/projects/:team_id/engineering_analytics/workflow_runs/': RUNS,
                'api/projects/:team_id/engineering_analytics/workflow_run_activity/': ACTIVITY,
                'api/projects/:team_id/engineering_analytics/workflow_runner_costs/': RUNNER_COSTS,
                'api/projects/:team_id/engineering_analytics/job_aggregates/': JOB_AGGREGATES,
                'api/projects/:team_id/engineering_analytics/workflow_health/': WORKFLOW_HEALTH,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

const WORKFLOW_URL = urls.engineeringAnalyticsWorkflowRuns('PostHog', 'posthog', 'Backend CI')

export const WorkflowDetail: Story = {
    render: () => <App />,
    parameters: { pageUrl: WORKFLOW_URL },
}

// The scope hydrates from the URL, so this opens on the pull-request group.
export const WorkflowDetailScopedToPullRequests: Story = {
    render: () => <App />,
    parameters: { pageUrl: `${WORKFLOW_URL}?run_scope=pull_request` },
}
