import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type {
    GitHubSourceApi,
    PullRequestListApi,
    RepoOverviewApi,
    WorkflowHealthItemApi,
    WorkflowRunActivityApi,
} from '../generated/api.schemas'

const SOURCES: GitHubSourceApi[] = [{ id: 'src-1', repo: 'PostHog/posthog', prefix: '' }]

// One overview payload feeding the whole hub: the trend sparkline cards and the quill cost-per-merge
// line chart. Each trend series carries a null bucket so the trim + carry-forward path is exercised.
const OVERVIEW: RepoOverviewApi = {
    run_count: 1284,
    run_count_prev: 1122,
    success_rate: 0.87,
    success_rate_prev: 0.82,
    rerun_cycles: 41,
    rerun_cycles_prev: 30,
    median_open_to_merge_seconds: 14 * 3600,
    median_open_to_merge_seconds_prev: 19 * 3600,
    billable_minutes: 5230,
    billable_minutes_prev: 4890,
    estimated_cost_usd: 412.5,
    estimated_cost_usd_prev: 361.0,
    jobs_available: true,
    default_branch: 'master',
    cost_series_granularity: 'day',
    cost_series: [52.1, 47.8, 61.3, 58.9, 44.2, 49.5, 55.7].map((cost, i) => ({
        bucket_start: `2026-06-${25 + i}T00:00:00Z`,
        estimated_cost_usd: cost * 8,
        merges: 8,
        cost_per_merge_usd: cost,
    })),
    time_to_green_series: [540, 600, null, 660, 720, 900, 780].map((p50_seconds, i) => ({
        bucket_start: `2026-06-${25 + i}T00:00:00Z`,
        p50_seconds,
    })),
    time_to_green_series_granularity: 'day',
    success_rate_series: [0.82, 0.85, 0.8, null, 0.88, 0.79, 0.87].map((success_rate, i) => ({
        bucket_start: `2026-06-${25 + i}T00:00:00Z`,
        success_rate,
    })),
    success_rate_series_granularity: 'day',
    open_to_merge_series: [14 * 3600, 16 * 3600, null, 12 * 3600, 15 * 3600, 18 * 3600, 13 * 3600].map(
        (p50_seconds, i) => ({
            bucket_start: `2026-06-${25 + i}T00:00:00Z`,
            p50_seconds,
        })
    ),
    open_to_merge_series_granularity: 'day',
}

const ACTIVITY: WorkflowRunActivityApi = {
    points: [520, 680, 1450, 760, 590, 2100, 830, 640].map((duration, i) => ({
        run_id: 9000 + i,
        conclusion: i === 5 ? 'failure' : 'success',
        run_started_at: `2026-07-01T${String(8 + i * 2).padStart(2, '0')}:00:00Z`,
        duration_seconds: duration,
        head_branch: 'master',
        pr_number: 0,
        head_sha: `deadbeef${String(i).padStart(2, '0')}`,
    })),
    truncated: false,
    limit: 500,
}

function healthItem(
    workflowName: string,
    costUsd: number,
    failures: number[],
    successRate: number
): WorkflowHealthItemApi {
    return {
        repo: { provider: 'github', owner: 'PostHog', name: 'posthog' },
        workflow_name: workflowName,
        run_count: 320,
        success_rate: successRate,
        success_rate_prev: successRate - 0.03,
        p50_seconds: 540,
        p95_seconds: 1680,
        last_failure_at: failures.some((f) => f > 0) ? '2026-07-01T16:00:00Z' : null,
        latest_run_failed: false,
        latest_run_conclusion: 'success',
        granularity: 'day',
        billable_minutes: costUsd * 12,
        estimated_cost_usd: costUsd,
        rerun_cycles: 6,
        buckets: failures.map((failed, i) => ({
            bucket_start: `2026-06-${25 + i}T00:00:00Z`,
            run_count: 44 + i,
            completed: 40 + i,
            successes: 40 + i - failed,
            failures: failed,
        })),
    }
}

const WORKFLOW_HEALTH: WorkflowHealthItemApi[] = [
    healthItem('Backend CI', 210.4, [2, 0, 4, 1, 0, 3, 1], 0.91),
    healthItem('E2E - Playwright', 130.2, [5, 3, 6, 2, 4, 5, 3], 0.78),
    healthItem('Frontend CI', 71.9, [0, 1, 0, 0, 2, 0, 1], 0.95),
]

const PULL_REQUESTS: PullRequestListApi = {
    items: [
        {
            author: { handle: 'jane-dev', display_name: 'Jane Dev', avatar_url: '', is_bot: false },
            repo: { provider: 'github', owner: 'PostHog', name: 'posthog' },
            ci: { runs: 6, passing: 4, failing: 2, pending: 0, failing_workflows: ['Backend CI', 'E2E - Playwright'] },
            push_history: [
                {
                    head_sha: 'aaa111',
                    started_at: '2026-06-24T11:00:00Z',
                    wall_seconds: 1320,
                    failed: false,
                    pending: false,
                },
                {
                    head_sha: 'bbb222',
                    started_at: '2026-06-25T09:30:00Z',
                    wall_seconds: 1500,
                    failed: false,
                    pending: false,
                },
                {
                    head_sha: 'ccc333',
                    started_at: '2026-06-26T14:00:00Z',
                    wall_seconds: 1680,
                    failed: true,
                    pending: false,
                },
            ],
            number: 41231,
            title: 'feat(insights): sticky breakdown legends',
            state: 'open',
            is_draft: false,
            created_at: '2026-06-24T10:00:00Z',
            merged_at: null,
            open_to_merge_seconds: null,
            labels: [],
            pushes: 9,
            rerun_cycles: 3,
            estimated_cost_usd: 38.2,
            billable_minutes: 410,
        },
        {
            author: { handle: 'sam-eng', display_name: 'Sam Eng', avatar_url: '', is_bot: false },
            repo: { provider: 'github', owner: 'PostHog', name: 'posthog' },
            ci: { runs: 5, passing: 5, failing: 0, pending: 0 },
            push_history: [
                {
                    head_sha: 'ddd444',
                    started_at: '2026-06-30T09:15:00Z',
                    wall_seconds: 900,
                    failed: false,
                    pending: false,
                },
                {
                    head_sha: 'eee555',
                    started_at: '2026-06-30T15:00:00Z',
                    wall_seconds: 1020,
                    failed: false,
                    pending: false,
                },
                {
                    head_sha: 'fff666',
                    started_at: '2026-07-01T08:00:00Z',
                    wall_seconds: 960,
                    failed: false,
                    pending: false,
                },
            ],
            number: 41250,
            title: 'fix(cohorts): handle empty cohort in query builder',
            state: 'merged',
            is_draft: false,
            created_at: '2026-06-30T09:00:00Z',
            merged_at: '2026-07-01T08:30:00Z',
            open_to_merge_seconds: 84600,
            labels: [],
            pushes: 3,
            rerun_cycles: 0,
            estimated_cost_usd: 12.7,
            billable_minutes: 130,
        },
    ],
    truncated: false,
    limit: 1000,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Engineering Analytics/Repo Overview',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-02',
        featureFlags: [FEATURE_FLAGS.ENGINEERING_ANALYTICS],
        testOptions: {
            // The hub is past its skeletons once the "needs attention" PR table has rendered.
            waitForSelector: '[data-attr="engineering-analytics-attention-prs"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/sources/': SOURCES,
                'api/projects/:team_id/engineering_analytics/repo_overview/': OVERVIEW,
                'api/projects/:team_id/engineering_analytics/master_failures/': [],
                'api/projects/:team_id/engineering_analytics/repo_run_activity/': ACTIVITY,
                'api/projects/:team_id/engineering_analytics/ci_cards/': {
                    open_prs: 18,
                    repos: 1,
                    stuck: 3,
                    failing_ci: 4,
                },
                'api/projects/:team_id/engineering_analytics/pull_requests/': PULL_REQUESTS,
                'api/projects/:team_id/engineering_analytics/workflow_health/': WORKFLOW_HEALTH,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const RepoOverview: Story = {
    render: () => <App />,
    parameters: { pageUrl: urls.engineeringAnalytics() },
}
