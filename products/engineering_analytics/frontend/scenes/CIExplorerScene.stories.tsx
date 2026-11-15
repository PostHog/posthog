import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { CIDataFreshnessApi, PRLifecycleApi, WorkflowJobApi, WorkflowRunDetailApi } from '../generated/api.schemas'

const REPO = { provider: 'github', owner: 'PostHog', name: 'posthog' }
const NUMBER = 4820
const PUSHED_AT = '2026-07-01T11:12:00Z'

function run(
    id: number,
    workflow: string,
    conclusion: string | null,
    minutes: number,
    overrides: Partial<WorkflowRunDetailApi> = {}
): WorkflowRunDetailApi {
    return {
        repo: REPO,
        id,
        ci_engine: 'github_actions',
        workflow_name: workflow,
        workflow_id: id,
        event: 'pull_request',
        head_sha: 'c0ffee4820aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        head_branch: 'feat/run-scope-groups',
        status: conclusion === null ? 'in_progress' : 'completed',
        conclusion,
        run_started_at: PUSHED_AT,
        updated_at: new Date(Date.parse(PUSHED_AT) + minutes * 60_000).toISOString(),
        duration_seconds: conclusion === null ? null : minutes * 60,
        run_attempt: 1,
        pr_number: NUMBER,
        commit_pr_number: null,
        is_merge_queue: false,
        ...overrides,
    }
}

// A failed workflow, a running one, a Depot CI one, and an earlier commit with a failure in its history.
const RUNS: WorkflowRunDetailApi[] = [
    run(1, 'Backend CI', 'failure', 28),
    run(2, 'Frontend CI', 'success', 17),
    run(3, 'Backend CI on Depot', 'success', 22, { ci_engine: 'depot_ci', workflow_id: null, event: null }),
    run(4, 'Storybook', null, 9),
    run(5, 'Backend CI', 'failure', 25, {
        head_sha: 'badc0de4820bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        run_started_at: '2026-06-30T16:40:00Z',
        updated_at: '2026-06-30T17:05:00Z',
    }),
]

const JOBS: WorkflowJobApi[] = [1, 2, 3].map((shard) => ({
    id: shard,
    run_id: 1,
    ci_engine: 'github_actions',
    steps: [],
    name: `Python tests (${shard}/3)`,
    status: 'completed',
    conclusion: shard === 2 ? 'failure' : 'success',
    started_at: PUSHED_AT,
    completed_at: new Date(Date.parse(PUSHED_AT) + (16 + shard) * 60_000).toISOString(),
    duration_seconds: (16 + shard) * 60,
    runner_provider: 'self_hosted',
    runner_label: 'depot-ubuntu-16',
    estimated_cost_usd: 0.5,
}))

const LIFECYCLE: PRLifecycleApi = {
    pull_request: {
        author: { handle: 'octocat', display_name: 'octocat', avatar_url: '', is_bot: false },
        repo: REPO,
        id: 90000 + NUMBER,
        number: NUMBER,
        title: 'Group runs by scope',
        state: 'open',
        is_draft: false,
        created_at: '2026-06-30T16:38:00Z',
        merged_at: null,
        closed_at: null,
    },
    events: [
        { kind: 'opened', at: '2026-06-30T16:38:00Z' },
        { kind: 'converted_to_draft', at: '2026-06-30T18:00:00Z', detail: 'octocat' },
        { kind: 'ready_for_review', at: '2026-07-01T11:00:00Z', detail: 'octocat' },
    ],
    metric_quality: 'partial',
}

const FRESHNESS: CIDataFreshnessApi = {
    runs_synced_at: '2026-07-01T23:40:00Z',
    jobs_synced_at: '2026-07-01T23:35:00Z',
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Engineering Analytics/CI Explorer',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-02',
        featureFlags: [FEATURE_FLAGS.ENGINEERING_ANALYTICS],
        pageUrl: urls.engineeringAnalyticsCIExplorer('PostHog', 'posthog', NUMBER),
        testOptions: { waitForSelector: '.CIExplorer__card' },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/pr_lifecycle/': LIFECYCLE,
                'api/projects/:team_id/engineering_analytics/pr_runs/': RUNS,
                'api/projects/:team_id/engineering_analytics/workflow_jobs/': JOBS,
                'api/projects/:team_id/engineering_analytics/ci_data_freshness/': FRESHNESS,
                'api/projects/:team_id/engineering_analytics/ci_failure_logs/': {
                    repo: REPO,
                    pr_number: NUMBER,
                    jobs: [],
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const Overview: Story = {
    render: () => <App />,
}

export const Activity: Story = {
    render: () => <App />,
    parameters: {
        pageUrl: `${urls.engineeringAnalyticsCIExplorer('PostHog', 'posthog', NUMBER)}?view=activity`,
        testOptions: { waitForSelector: '[data-attr="ci-explorer-activity-commit"]' },
    },
}
