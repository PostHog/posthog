import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { GitHubSourceApi, WorkflowHealthItemApi } from '../generated/api.schemas'
import { workflowHealthItem } from '../lib/storyFixtures'

const SOURCES: GitHubSourceApi[] = [{ id: 'src-1', repo: 'PostHog/posthog', prefix: '' }]

function healthItem(
    workflowName: string,
    runCount: number,
    mergeQueueRunCount: number,
    successRate: number | null,
    failing: boolean = false
): WorkflowHealthItemApi {
    const settled = successRate !== null
    return workflowHealthItem({
        workflow_name: workflowName,
        run_count: runCount,
        successful_run_count: settled ? Math.round(runCount * successRate) : 0,
        conclusive_run_count: settled ? runCount : 0,
        success_rate: successRate,
        success_rate_prev: settled ? successRate - 0.02 : null,
        p50_seconds: settled ? 480 : null,
        p95_seconds: settled ? 1520 : null,
        last_failure_at: failing ? '2026-07-01T15:20:00Z' : null,
        latest_run_failed: settled ? failing : null,
        latest_run_conclusion: settled ? (failing ? 'failure' : 'success') : null,
        latest_run_id: settled ? 900000 + runCount : null,
        billable_minutes: runCount * 9,
        estimated_cost_usd: runCount * 0.6,
        rerun_cycles: failing ? 14 : 2,
        merge_queue_run_count: mergeQueueRunCount,
        buckets: [0, 1, 2, 3, 4, 5, 6].map((day) => ({
            bucket_start: `2026-06-${25 + day}T00:00:00Z`,
            run_count: Math.round(runCount / 7),
            completed: settled ? Math.round(runCount / 7) : 0,
            successes: settled ? Math.round((runCount / 7) * successRate) : 0,
            failures: failing && day % 2 === 0 ? 3 : 0,
        })),
    })
}

// The list's whole ordering space: gating workflows the merge queue runs (one of them failing), busier
// workflows it does not gate, and one with nothing settled in the window.
const WORKFLOW_HEALTH: WorkflowHealthItemApi[] = [
    healthItem('Backend CI', 412, 186, 0.93),
    healthItem('Frontend CI', 388, 174, 0.96),
    healthItem('E2E - Playwright', 210, 96, 0.74, true),
    healthItem('Docs preview', 940, 0, 0.99),
    healthItem('Container images', 132, 0, 0.88),
    healthItem('Storybook', 96, 0, 0.91),
    healthItem('Nightly benchmarks', 21, 0, 0.62, true),
    healthItem('Release', 4, 0, null),
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Engineering Analytics/Workflows',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-02',
        featureFlags: [FEATURE_FLAGS.ENGINEERING_ANALYTICS],
        testOptions: {
            waitForSelector: '[data-attr="engineering-analytics-workflow-table"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/sources/': SOURCES,
                'api/projects/:team_id/engineering_analytics/workflow_health/': WORKFLOW_HEALTH,
                // Sibling-tab loaders mount with the scene; stub them so the story renders without error toasts.
                'api/projects/:team_id/engineering_analytics/ci_cards/': {
                    open_prs: 18,
                    repos: 1,
                    stuck: 3,
                    failing_ci: 4,
                },
                'api/projects/:team_id/engineering_analytics/pull_requests/': {
                    items: [],
                    truncated: false,
                    limit: 1000,
                },
                'api/projects/:team_id/engineering_analytics/quarantine/': {
                    available: false,
                    entries: [],
                    parse_errors: [],
                    parse_warnings: [],
                    repo: null,
                    source_url: null,
                    generated_at: null,
                },
                'api/projects/:team_id/engineering_analytics/trunk_quarantine/': {
                    available: false,
                    ttl_days: 15,
                    repository: null,
                    trunk_url: null,
                    teams: [],
                    tests: [],
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const WorkflowList: Story = {
    render: () => <App />,
    parameters: { pageUrl: urls.engineeringAnalyticsWorkflows() },
}

// The scope hydrates from the URL, so this opens on the merge-queue group.
export const WorkflowListScopedToMergeQueue: Story = {
    render: () => <App />,
    parameters: { pageUrl: `${urls.engineeringAnalyticsWorkflows()}?run_scope=merge_queue` },
}
