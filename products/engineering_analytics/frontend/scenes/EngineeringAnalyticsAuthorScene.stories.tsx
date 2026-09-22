import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type {
    DeliveryComparisonApi,
    DeliverySummaryApi,
    DurationDistributionApi,
    PRTimelineApi,
    PullRequestTimelinesApi,
    ReadyToMergeMediansApi,
    WorkflowCostApi,
} from '../generated/api.schemas'

const HOUR = 3600

function distribution(p50Hours: number, count: number): DurationDistributionApi {
    return {
        pr_count: count,
        min_seconds: 0.2 * p50Hours * HOUR,
        p05_seconds: 0.3 * p50Hours * HOUR,
        p25_seconds: 0.6 * p50Hours * HOUR,
        p50_seconds: p50Hours * HOUR,
        mean_seconds: 1.8 * p50Hours * HOUR,
        p75_seconds: 2.2 * p50Hours * HOUR,
        p95_seconds: 6 * p50Hours * HOUR,
        max_seconds: 9 * p50Hours * HOUR,
    }
}

const SUMMARY: DeliverySummaryApi = {
    scope_kind: 'author',
    scope: 'jane-dev',
    has_membership_data: false,
    jobs_available: true,
    review_data_available: true,
    ready_data_available: true,
    opened_pr_count: 24,
    merged_pr_count: 21,
    open_pr_count: 3,
    draft_pr_count: 1,
    cost_per_merged_pr_usd: { scope: 9.4, repo: 6.1 },
    billable_minutes_per_merged_pr: { scope: 118, repo: 84 },
    cost_per_push_usd: { scope: 1.35, repo: 1.2 },
    total_cost_usd: 231.8,
    total_billable_minutes: 2940,
    push_count: 172,
    median_ready_to_merge_seconds: { scope: 18 * HOUR, repo: 9 * HOUR },
    p90_ready_to_merge_seconds: { scope: 4.1 * 24 * HOUR, repo: 3.2 * 24 * HOUR },
    median_ready_to_first_approval_seconds: { scope: 2.1 * HOUR, repo: 2.6 * HOUR },
    median_first_approval_to_merge_seconds: { scope: 11 * HOUR, repo: 3.4 * HOUR },
    before_first_approval_share: { scope: 0.38, repo: 0.52 },
    pushes_after_approval_per_merged_pr: { scope: 1.6, repo: 0.9 },
    merge_queue_attempts_per_merged_pr: { scope: 1.4, repo: 1.3 },
    failed_merge_queue_share: { scope: 0.24, repo: 0.21 },
    lead_time: {
        deploy_data_available: true,
        environment_scope: 'prod-us, prod-eu',
        merged_pr_count: 21,
        deployed_merged_pr_count: 19,
        open_to_deploy: { scope: distribution(21, 19), repo: distribution(12, 640) },
        open_to_merge: { scope: distribution(20, 19), repo: distribution(10, 640) },
        merge_to_deploy: { scope: distribution(1.1, 19), repo: distribution(1.1, 640) },
    },
}

const NOW = '2026-07-02T12:00:00Z'

function timeline(
    number: number,
    title: string,
    startedAt: string,
    steps: [PRTimelineApi['segments'][number]['kind'], number][],
    options: { merged?: boolean; draft?: boolean } = {}
): PRTimelineApi {
    let cursor = Date.parse(startedAt)
    const segments = steps.map(([kind, hours]) => {
        const start = cursor
        cursor += hours * HOUR * 1000
        return { kind, started_at: new Date(start).toISOString(), ended_at: new Date(cursor).toISOString() }
    })
    const end = new Date(cursor).toISOString()
    return {
        number,
        title,
        author: { handle: 'jane-dev', display_name: 'jane-dev', avatar_url: '', is_bot: false },
        repo: { provider: 'github', owner: 'PostHog', name: 'posthog' },
        state: options.merged ? 'merged' : 'open',
        is_draft: !!options.draft,
        created_at: startedAt,
        started_at: startedAt,
        merged_at: options.merged ? end : null,
        pushes: segments
            .filter((segment) => segment.kind === 'ci_running')
            .map((segment, index) => ({ head_sha: `sha${number}${index}`, pushed_at: segment.started_at })),
        estimated_cost_usd: 4.2 * number,
        billable_minutes: 40 * number,
        segments,
    }
}

// Open rows run exactly to NOW, so their last step length is the gap from the running total to NOW.
const TIMELINES: PullRequestTimelinesApi = {
    scope_kind: 'author',
    scope: 'jane-dev',
    has_membership_data: false,
    review_data_available: true,
    jobs_available: true,
    merge_queue_state_available: true,
    generated_at: NOW,
    truncated: false,
    limit: 200,
    items: [
        timeline(4101, 'feat(insights): stream breakdown legends into the composer', '2026-06-29T14:40:00Z', [
            ['waiting_for_review', 17.5],
            ['changes_requested', 3],
            ['ci_running', 0.6],
            ['red_fixed_by_push', 1.2],
            ['ci_running', 0.5],
            ['approved_not_enqueued', 0.9],
            ['merge_queue', 0.8],
            ['out_of_merge_queue', 44.83],
        ]),
        timeline(4102, 'fix(tasks): keep sandbox logs after a resume', '2026-07-01T09:05:00Z', [
            ['ci_running', 0.4],
            ['red_passed_on_rerun', 2.1],
            ['ci_running', 0.5],
            ['waiting_for_review', 23.9],
        ]),
        timeline(4103, 'chore(signals): drop the unused research prompt', '2026-07-02T09:10:00Z', [
            ['ci_running', 0.5],
            ['red_master_broken', 2.33],
        ]),
        timeline(
            4090,
            'feat(cohorts): cache static cohort sizes',
            '2026-06-22T08:00:00Z',
            [
                ['ci_running', 0.5],
                ['waiting_for_review', 26],
                ['changes_requested', 20],
                ['ci_running', 0.6],
                ['red_not_provable', 5],
                ['ci_running', 0.5],
                ['approved_not_enqueued', 2],
                ['merge_queue', 1.2],
            ],
            { merged: true }
        ),
        timeline(
            4094,
            'fix(cohorts): handle an empty cohort in the query builder',
            '2026-06-25T10:30:00Z',
            [
                ['ci_running', 0.5],
                ['waiting_for_review', 15],
                ['approved_not_enqueued', 1],
                ['merge_queue', 0.9],
            ],
            { merged: true }
        ),
        timeline(
            4097,
            'chore(ci): bump the runner image',
            '2026-06-30T07:15:00Z',
            [
                ['ci_running', 0.4],
                ['waiting_for_review', 1.5],
                ['merge_queue', 0.6],
            ],
            { merged: true }
        ),
        timeline(4105, 'feat(signals): let scouts reuse research', '2026-06-30T10:00:00Z', [['draft', 50]], {
            draft: true,
        }),
    ],
}

const WORKFLOW_COSTS: WorkflowCostApi[] = [
    {
        workflow_name: 'Backend CI',
        billable_minutes: 1720,
        estimated_cost_usd: 131.2,
        costed_jobs: 820,
        unsettled_jobs: 0,
        excluded_jobs: 12,
    },
    {
        workflow_name: 'Frontend CI',
        billable_minutes: 640,
        estimated_cost_usd: 58.4,
        costed_jobs: 310,
        unsettled_jobs: 0,
        excluded_jobs: 4,
    },
    {
        workflow_name: 'E2E - Playwright',
        billable_minutes: 580,
        estimated_cost_usd: 42.2,
        costed_jobs: 96,
        unsettled_jobs: 1,
        excluded_jobs: 0,
    },
]

function medians(
    count: number,
    hours: { ready: number; p90: number; beforeApproval: number; afterApproval: number },
    beforeShare: number
): ReadyToMergeMediansApi {
    return {
        merged_pr_count: count,
        ready_to_merge_seconds: hours.ready * HOUR,
        p90_ready_to_merge_seconds: hours.p90 * HOUR,
        ready_to_first_approval_seconds: hours.beforeApproval * HOUR,
        first_approval_to_merge_seconds: hours.afterApproval * HOUR,
        before_first_approval_share: beforeShare,
    }
}

// The author page reads only the team rows; the author and repo rows come from the summary.
const COMPARISON: DeliveryComparisonApi = {
    author: 'jane-dev',
    has_membership_data: true,
    review_data_available: true,
    ready_data_available: true,
    team_basis: 'review_requests',
    author_medians: medians(23, { ready: 18, p90: 98, beforeApproval: 2.1, afterApproval: 11 }, 0.38),
    teams: [
        {
            github_team: 'team-replay',
            medians: medians(84, { ready: 13, p90: 82, beforeApproval: 3.2, afterApproval: 5.5 }, 0.46),
        },
    ],
    repo_medians: medians(1380, { ready: 9, p90: 77, beforeApproval: 2.6, afterApproval: 3.4 }, 0.52),
    pull_request: null,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Engineering Analytics/Author',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-02',
        featureFlags: [FEATURE_FLAGS.ENGINEERING_ANALYTICS],
        pageUrl: urls.engineeringAnalyticsAuthor('jane-dev'),
        testOptions: {
            waitForSelector: '[data-attr="engineering-analytics-day-view"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/delivery_summary/': SUMMARY,
                'api/projects/:team_id/engineering_analytics/delivery_comparison/': COMPARISON,
                'api/projects/:team_id/engineering_analytics/pull_request_timelines/': TIMELINES,
                'api/projects/:team_id/engineering_analytics/author_workflow_costs/': WORKFLOW_COSTS,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const Author: Story = {
    render: () => <App />,
}

// A docked side panel leaves the scene about 520px wide: the cards stack and the day view drops its
// explanation column.
export const AuthorNarrow: Story = {
    render: () => <App />,
    parameters: { testOptions: { viewport: { width: 900, height: 1800 } } },
}

// Without the members table the ready card has no team row and says how to get one.
export const AuthorWithoutReviewsOrDeploys: Story = {
    render: () => <App />,
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/delivery_summary/': {
                    ...SUMMARY,
                    review_data_available: false,
                    lead_time: { ...SUMMARY.lead_time, deploy_data_available: false, environment_scope: '' },
                },
                'api/projects/:team_id/engineering_analytics/delivery_comparison/': {
                    ...COMPARISON,
                    has_membership_data: false,
                    review_data_available: false,
                    team_basis: 'no_team',
                    teams: [],
                },
                'api/projects/:team_id/engineering_analytics/pull_request_timelines/': {
                    ...TIMELINES,
                    review_data_available: false,
                },
            },
        }),
    ],
}
