import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { RunFailureLogsApi, WorkflowJobApi, WorkflowRunDetailApi } from '../generated/api.schemas'

const REPO = { provider: 'github', owner: 'PostHog', name: 'posthog' }
const RUN_ID = 880163
const STARTED_AT = '2026-07-01T11:12:00Z'

const RUN: WorkflowRunDetailApi = {
    repo: REPO,
    id: RUN_ID,
    workflow_name: 'Backend CI',
    head_sha: 'c0ffee880163',
    head_branch: 'feat/run-scope-groups',
    status: 'completed',
    conclusion: 'failure',
    run_started_at: STARTED_AT,
    updated_at: '2026-07-01T11:40:00Z',
    duration_seconds: 1680,
    run_attempt: 1,
    pr_number: 4820,
    commit_pr_number: null,
    is_merge_queue: false,
}

function job(id: number, name: string, conclusion: string, startMinute: number, minutes: number): WorkflowJobApi {
    const startedAt = new Date(Date.parse(STARTED_AT) + startMinute * 60_000).toISOString()
    return {
        id,
        run_id: RUN_ID,
        name,
        status: 'completed',
        conclusion,
        started_at: startedAt,
        completed_at: new Date(Date.parse(startedAt) + minutes * 60_000).toISOString(),
        duration_seconds: minutes * 60,
        runner_provider: 'self_hosted',
        runner_label: 'depot-ubuntu-16',
        estimated_cost_usd: minutes * 0.032,
    }
}

// A matrix group with one failed shard and a passing single job.
const JOBS: WorkflowJobApi[] = [
    job(1, 'Python tests (1/3)', 'success', 1, 18),
    job(2, 'Python tests (2/3)', 'failure', 1, 22),
    job(3, 'Python tests (3/3)', 'success', 1, 17),
    job(4, 'Migrations', 'success', 0.5, 4),
]

const FAILURE_LOGS: RunFailureLogsApi = {
    run_id: RUN_ID,
    logs_available: true,
    truncated: false,
    jobs: [
        {
            job_id: 2,
            run_id: RUN_ID,
            conclusion: 'failure',
            branch: 'feat/run-scope-groups',
            original_total_lines: 4210,
            line_count: 3,
            truncated: false,
            lines: [
                { original_line: 3988, text: 'FAILED posthog/api/test/test_example.py::TestExample::test_scope' },
                { original_line: null, text: '... 12 lines omitted ...' },
                { original_line: 4001, text: 'AssertionError: expected 3 run groups, got 2' },
            ],
        },
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Engineering Analytics/Workflow Run',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-02',
        featureFlags: [FEATURE_FLAGS.ENGINEERING_ANALYTICS],
        pageUrl: urls.engineeringAnalyticsWorkflowRun('PostHog', 'posthog', RUN_ID),
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/workflow_run/': RUN,
                'api/projects/:team_id/engineering_analytics/workflow_jobs/': JOBS,
                'api/projects/:team_id/engineering_analytics/run_failure_logs/': FAILURE_LOGS,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const FailedRun: Story = {
    render: () => <App />,
    parameters: { testOptions: { waitForSelector: '#ea-section-jobs' } },
}

export const JobsAndLogsLoadErrors: Story = {
    render: () => <App />,
    parameters: { testOptions: { waitForSelector: '#ea-section-jobs' } },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/workflow_jobs/': () => [500, null],
                'api/projects/:team_id/engineering_analytics/run_failure_logs/': () => [500, null],
            },
        }),
    ],
}
