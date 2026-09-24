import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type {
    CIFailureLogsApi,
    DeliveryComparisonApi,
    PRCostSummaryApi,
    PRLifecycleApi,
    PRTimelineApi,
    PullRequestTimelinesApi,
    ReadyToMergeMediansApi,
    WorkflowJobApi,
    WorkflowRunDetailApi,
} from '../generated/api.schemas'

const HOUR = 3600 * 1000
const HOUR_SECONDS = 3600
const REPO = { provider: 'github', owner: 'PostHog', name: 'posthog' } as const
const AUTHOR = { handle: 'jane-dev', display_name: 'jane-dev', avatar_url: '', is_bot: false }

function hoursAfter(start: string, hours: number): string {
    return new Date(Date.parse(start) + hours * HOUR).toISOString()
}

function timeline(
    number: number,
    title: string,
    startedAt: string,
    steps: [PRTimelineApi['segments'][number]['kind'], number][],
    pushes: [string, number][],
    merged: boolean
): PRTimelineApi {
    let cursor = 0
    const segments = steps.map(([kind, hours]) => {
        const segment = {
            kind,
            started_at: hoursAfter(startedAt, cursor),
            ended_at: hoursAfter(startedAt, cursor + hours),
        }
        cursor += hours
        return segment
    })
    return {
        number,
        title,
        author: AUTHOR,
        repo: REPO,
        state: merged ? 'merged' : 'open',
        is_draft: false,
        created_at: hoursAfter(startedAt, -0.5),
        started_at: startedAt,
        merged_at: merged ? hoursAfter(startedAt, cursor) : null,
        pushes: pushes.map(([headSha, hours]) => ({ head_sha: headSha, pushed_at: hoursAfter(startedAt, hours) })),
        estimated_cost_usd: 6.4,
        billable_minutes: 88,
        segments,
    }
}

function run(
    prNumber: number,
    id: number,
    workflow: string,
    headSha: string,
    startedAt: string,
    conclusion: string | null,
    options: { attempt?: number; mergeQueue?: boolean } = {}
): WorkflowRunDetailApi {
    return {
        repo: REPO,
        id,
        workflow_name: workflow,
        head_sha: headSha,
        head_branch: options.mergeQueue ? `trunk-merge/pr-${prNumber}/1` : `jane/pr-${prNumber}`,
        status: conclusion === null ? 'in_progress' : 'completed',
        conclusion,
        run_started_at: startedAt,
        updated_at: hoursAfter(startedAt, 0.4),
        duration_seconds: conclusion === null ? null : 24 * 60,
        run_attempt: options.attempt ?? 1,
        pr_number: prNumber,
        commit_pr_number: null,
        is_merge_queue: !!options.mergeQueue,
    }
}

function lifecycle(timelineItem: PRTimelineApi): PRLifecycleApi {
    return {
        pull_request: {
            author: AUTHOR,
            repo: REPO,
            id: 90000 + timelineItem.number,
            number: timelineItem.number,
            title: timelineItem.title,
            state: timelineItem.state,
            is_draft: false,
            created_at: timelineItem.created_at,
            merged_at: timelineItem.merged_at,
            closed_at: timelineItem.merged_at,
        },
        events: [{ kind: 'opened', at: timelineItem.created_at }],
        metric_quality: 'partial',
    }
}

function timelines(item: PRTimelineApi): PullRequestTimelinesApi {
    return {
        scope_kind: 'pull_request',
        scope: `PostHog/posthog#${item.number}`,
        has_membership_data: true,
        review_data_available: true,
        jobs_available: true,
        merge_queue_state_available: true,
        generated_at: '2026-07-02T12:00:00Z',
        merged_pr_count: item.merged_at ? 1 : 0,
        red_seconds_per_merged_pr: [
            { kind: 'red_fixed_by_push', seconds_per_merged_pr: 0 },
            { kind: 'red_passed_on_rerun', seconds_per_merged_pr: 0 },
            { kind: 'red_master_broken', seconds_per_merged_pr: 0 },
            { kind: 'red_not_provable', seconds_per_merged_pr: 0 },
        ],
        truncated: false,
        limit: 200,
        items: [item],
    }
}

const READY = '2026-06-29T09:40:00Z'
const MERGED = timeline(
    4721,
    'feat(replay): keep the scrubber in place on resume',
    READY,
    [
        ['ci_running', 0.5],
        ['waiting_for_review', 21.5],
        ['changes_requested', 3],
        ['ci_running', 0.6],
        ['red_passed_on_rerun', 0.8],
        ['ci_running', 0.5],
        ['waiting_for_review', 2.1],
        ['approved_not_enqueued', 1.5],
        ['merge_queue', 0.9],
    ],
    [
        ['a1b2c3d4e5', -0.4],
        ['f6e5d4c3b2', 25],
    ],
    true
)
const SECOND_PUSH = hoursAfter(READY, 25)
const MERGED_RUNS: WorkflowRunDetailApi[] = [
    run(4721, 101, 'Backend CI', 'a1b2c3d4e5', hoursAfter(READY, -0.4), 'success'),
    run(4721, 102, 'Frontend CI', 'a1b2c3d4e5', hoursAfter(READY, -0.4), 'success'),
    run(4721, 103, 'Backend CI', 'f6e5d4c3b2', SECOND_PUSH, 'failure'),
    run(4721, 103, 'Backend CI', 'f6e5d4c3b2', hoursAfter(READY, 26.4), 'success', { attempt: 2 }),
    run(4721, 104, 'Frontend CI', 'f6e5d4c3b2', SECOND_PUSH, 'success'),
    run(4721, 105, 'Backend CI', '9a8b7c6d5e', hoursAfter(READY, 30.5), 'success', { mergeQueue: true }),
]

const KICKED_READY = '2026-07-01T08:00:00Z'
const KICKED = timeline(
    4730,
    'fix(replay): drop the stale snapshot cache',
    KICKED_READY,
    [
        ['ci_running', 0.6],
        ['waiting_for_review', 4.4],
        ['ci_running', 0.5],
        ['approved_not_enqueued', 0.5],
        ['merge_queue', 1.2],
        ['out_of_merge_queue', 20.8],
    ],
    [
        ['0c1d2e3f4a', -0.3],
        ['5b6c7d8e9f', 5],
    ],
    false
)
const KICKED_RUNS: WorkflowRunDetailApi[] = [
    run(4730, 201, 'Backend CI', '0c1d2e3f4a', hoursAfter(KICKED_READY, -0.3), 'success'),
    run(4730, 202, 'Backend CI', '5b6c7d8e9f', hoursAfter(KICKED_READY, 5), 'success'),
    run(4730, 203, 'Backend CI', '1f2e3d4c5b', hoursAfter(KICKED_READY, 6.2), 'failure', { mergeQueue: true }),
]

const FAILED_GATE_JOBS: WorkflowJobApi[] = [
    {
        id: 2031,
        run_id: 203,
        name: 'Django tests (Core, 3/8)',
        status: 'completed',
        conclusion: 'failure',
        started_at: hoursAfter(KICKED_READY, 6.3),
        completed_at: hoursAfter(KICKED_READY, 6.8),
        duration_seconds: 30 * 60,
        runner_provider: 'depot',
        runner_label: 'depot-ubuntu-latest-4',
        estimated_cost_usd: 0.4,
    },
]

const PR_COST: PRCostSummaryApi = {
    by_workflow: [],
    by_run: [],
    llm_spend: null,
    jobs_available: true,
    billable_minutes: 88,
    estimated_cost_usd: 6.4,
    costed_jobs: 41,
    unsettled_jobs: 0,
    excluded_jobs: 2,
}

const NO_FAILURE_LOGS: CIFailureLogsApi = {
    repo: REPO,
    jobs: [],
    pr_number: 4721,
    runs_attributed: 5,
    logs_available: false,
    truncated: false,
}

function medians(count: number, readyHours: number, beforeHours: number, afterHours: number): ReadyToMergeMediansApi {
    return {
        merged_pr_count: count,
        ready_to_merge_seconds: readyHours * HOUR_SECONDS,
        p90_ready_to_merge_seconds: 2.5 * readyHours * HOUR_SECONDS,
        ready_to_first_approval_seconds: beforeHours * HOUR_SECONDS,
        first_approval_to_merge_seconds: afterHours * HOUR_SECONDS,
        before_first_approval_share: beforeHours / (beforeHours + afterHours),
    }
}

// Jane is in two teams that own code; this pull request asked team-replay to review.
function comparison(pullRequest: DeliveryComparisonApi['pull_request']): DeliveryComparisonApi {
    return {
        author: AUTHOR.handle,
        has_membership_data: true,
        review_data_available: true,
        ready_data_available: true,
        team_basis: 'pull_request',
        author_medians: medians(21, 16, 5, 6),
        teams: [{ github_team: 'team-replay', medians: medians(88, 12, 4, 4.5) }],
        repo_medians: medians(1380, 9, 2.6, 3.4),
        pull_request: pullRequest,
    }
}

const MERGED_COMPARISON = comparison({
    number: 4721,
    ready_to_merge_seconds: 31.4 * HOUR_SECONDS,
    ready_to_first_approval_seconds: 29 * HOUR_SECONDS,
    first_approval_to_merge_seconds: 2.4 * HOUR_SECONDS,
    before_first_approval_share: 29 / 31.4,
})

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Engineering Analytics/Pull Request',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-02',
        featureFlags: [FEATURE_FLAGS.ENGINEERING_ANALYTICS],
        pageUrl: urls.engineeringAnalyticsPullRequest('PostHog', 'posthog', MERGED.number),
        testOptions: {
            waitForSelector: '[data-attr="engineering-analytics-pr-delivery-timeline"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/pr_lifecycle/': lifecycle(MERGED),
                'api/projects/:team_id/engineering_analytics/pr_runs/': MERGED_RUNS,
                'api/projects/:team_id/engineering_analytics/pr_cost/': PR_COST,
                'api/projects/:team_id/engineering_analytics/ci_failure_logs/': NO_FAILURE_LOGS,
                'api/projects/:team_id/engineering_analytics/pull_request_timelines/': timelines(MERGED),
                'api/projects/:team_id/engineering_analytics/delivery_comparison/': MERGED_COMPARISON,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const Merged: Story = {
    render: () => <App />,
}

export const OutOfTheMergeQueue: Story = {
    render: () => <App />,
    parameters: {
        pageUrl: urls.engineeringAnalyticsPullRequest('PostHog', 'posthog', KICKED.number),
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/pr_lifecycle/': lifecycle(KICKED),
                'api/projects/:team_id/engineering_analytics/pr_runs/': KICKED_RUNS,
                'api/projects/:team_id/engineering_analytics/pull_request_timelines/': timelines(KICKED),
                'api/projects/:team_id/engineering_analytics/workflow_jobs/': FAILED_GATE_JOBS,
                // Jane's two teams tie, and the smaller one has too few other authors to show a median.
                'api/projects/:team_id/engineering_analytics/delivery_comparison/': {
                    ...comparison(null),
                    team_basis: 'review_requests',
                    teams: [
                        { github_team: 'team-replay', medians: medians(88, 12, 4, 4.5) },
                        { github_team: 'team-web-analytics', medians: null },
                    ],
                },
            },
        }),
    ],
}

export const SectionLoadErrors: Story = {
    render: () => <App />,
    parameters: { testOptions: { waitForSelector: '#ea-section-pr-runs' } },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/pr_runs/': () => [500, null],
                'api/projects/:team_id/engineering_analytics/pull_request_timelines/': () => [500, null],
            },
        }),
    ],
}
