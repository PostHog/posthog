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

// Deltas cover every pill state: pp up (good), % up (neutral), % up while good-is-down (bad), and
// an hours drop (good) — the surface this scene's quill MetricCard migration changed.
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
}

const ACTIVITY: WorkflowRunActivityApi = {
    points: [520, 680, 1450, 760, 590, 2100, 830, 640].map((duration, i) => ({
        run_id: 9000 + i,
        conclusion: i === 5 ? 'failure' : 'success',
        run_started_at: `2026-07-01T${String(8 + i * 2).padStart(2, '0')}:00:00Z`,
        duration_seconds: duration,
        head_branch: 'master',
        pr_number: 0,
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
            // The change pill only renders once the overview payload (and its deltas) has landed.
            waitForSelector: '[data-attr="metric-card-change-pill"]',
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
