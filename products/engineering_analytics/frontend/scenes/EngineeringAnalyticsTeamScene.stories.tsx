import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { DeliverySummaryApi, DurationDistributionApi, TeamCIHealthListApi } from '../generated/api.schemas'

const HOUR = 3600
const TEAM = 'team-replay'

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
    scope_kind: 'github_team',
    scope: TEAM,
    has_membership_data: true,
    jobs_available: true,
    review_data_available: true,
    ready_data_available: true,
    opened_pr_count: 41,
    merged_pr_count: 36,
    open_pr_count: 5,
    draft_pr_count: 2,
    cost_per_merged_pr_usd: { scope: 7.2, repo: 6.1 },
    billable_minutes_per_merged_pr: { scope: 96, repo: 84 },
    cost_per_push_usd: { scope: 1.1, repo: 1.2 },
    total_cost_usd: 302.4,
    total_billable_minutes: 4030,
    push_count: 274,
    median_ready_to_merge_seconds: { scope: 14 * HOUR, repo: 9 * HOUR },
    p90_ready_to_merge_seconds: { scope: 3.4 * 24 * HOUR, repo: 3.2 * 24 * HOUR },
    median_ready_to_first_approval_seconds: { scope: 3.2 * HOUR, repo: 2.6 * HOUR },
    median_first_approval_to_merge_seconds: { scope: 6.5 * HOUR, repo: 3.4 * HOUR },
    before_first_approval_share: { scope: 0.47, repo: 0.52 },
    pushes_after_approval_per_merged_pr: { scope: 1.1, repo: 0.9 },
    merge_queue_attempts_per_merged_pr: { scope: 1.35, repo: 1.3 },
    failed_merge_queue_share: { scope: 0.22, repo: 0.21 },
    lead_time: {
        deploy_data_available: true,
        environment_scope: 'prod-us, prod-eu',
        merged_pr_count: 36,
        deployed_merged_pr_count: 33,
        open_to_deploy: { scope: distribution(16, 33), repo: distribution(12, 640) },
        open_to_merge: { scope: distribution(15, 33), repo: distribution(10, 640) },
        merge_to_deploy: { scope: distribution(1.2, 33), repo: distribution(1.1, 640) },
    },
}

const TEAM_CI_HEALTH: TeamCIHealthListApi = {
    items: [
        {
            owner_team: TEAM,
            flaky_test_count: 8,
            flaky_test_count_prior: 11,
            regression_test_count: 3,
            regression_test_count_prior: 2,
            failed_run_count: 96,
            failed_run_count_prior: 120,
            same_commit_recovery_run_count: 14,
            same_commit_recovery_run_count_prior: 19,
            quarantined_failed_run_count: 2,
            quarantined_failed_run_count_prior: 1,
            last_seen_at: '2026-07-02T08:40:00Z',
            test_file_count: 204,
            test_file_count_prior: 201,
            merged_pr_count: 36,
            merged_pr_count_prior: 31,
        },
    ],
    truncated: false,
    limit: 100,
}

const TEAM_CI_ACTIVITY = {
    tests: [
        {
            runner: 'pytest',
            nodeid: 'products/replay/test_snapshots.py::test_resume_keeps_cursor',
            selector: 'products/replay/test_snapshots.py::test_resume_keeps_cursor',
            signal_count: 12,
            last_seen_at: '2026-07-02T07:10:00Z',
        },
        {
            runner: 'jest',
            nodeid: 'products/replay/frontend/scrubber.test.ts',
            selector: 'products/replay/frontend/scrubber.test.ts',
            signal_count: 4,
            last_seen_at: '2026-07-01T16:02:00Z',
        },
    ],
    truncated_tests: false,
}

const TEAM_MERGE_TREND = {
    has_membership_data: true,
    points: [
        { day: '2026-06-28', median_seconds: 11 * HOUR, average_seconds: 19 * HOUR },
        { day: '2026-06-29', median_seconds: 9 * HOUR, average_seconds: 14 * HOUR },
        { day: '2026-06-30', median_seconds: 13 * HOUR, average_seconds: 22 * HOUR },
        { day: '2026-07-01', median_seconds: 8 * HOUR, average_seconds: 12 * HOUR },
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Engineering Analytics/Team',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-02',
        featureFlags: [FEATURE_FLAGS.ENGINEERING_ANALYTICS],
        pageUrl: urls.engineeringAnalyticsTeam(TEAM),
        testOptions: {
            waitForSelector: '[data-attr="engineering-analytics-team-tests-table"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/delivery_summary/': SUMMARY,
                'api/projects/:team_id/engineering_analytics/team_ci_health/': TEAM_CI_HEALTH,
                'api/projects/:team_id/engineering_analytics/team_ci_activity/': TEAM_CI_ACTIVITY,
                'api/projects/:team_id/engineering_analytics/team_merge_trend/': TEAM_MERGE_TREND,
                'api/projects/:team_id/engineering_analytics/sources/': [
                    { id: 'src-1', repo: 'PostHog/posthog', prefix: '' },
                ],
                // Sibling-tab loaders mount with the scene; stub them so the story renders without error toasts.
                'api/projects/:team_id/engineering_analytics/ci_cards/': {
                    open_prs: 0,
                    repos: 1,
                    stuck: 0,
                    failing_ci: 0,
                },
                'api/projects/:team_id/engineering_analytics/pull_requests/': {
                    items: [],
                    truncated: false,
                    limit: 1000,
                },
                'api/projects/:team_id/engineering_analytics/workflow_health/': [],
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

export const Team: Story = {
    render: () => <App />,
}

// Without the membership snapshot a team matches no author, so the panels say so instead of showing zeros.
export const TeamWithoutMembership: Story = {
    render: () => <App />,
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/delivery_summary/': {
                    ...SUMMARY,
                    has_membership_data: false,
                    merged_pr_count: 0,
                    open_pr_count: 0,
                    draft_pr_count: 0,
                    opened_pr_count: 0,
                    total_cost_usd: null,
                    total_billable_minutes: null,
                    push_count: 0,
                    cost_per_merged_pr_usd: { scope: null, repo: 6.1 },
                    billable_minutes_per_merged_pr: { scope: null, repo: 84 },
                    cost_per_push_usd: { scope: null, repo: 1.2 },
                    median_ready_to_merge_seconds: { scope: null, repo: 9 * HOUR },
                    p90_ready_to_merge_seconds: { scope: null, repo: 3.2 * 24 * HOUR },
                    median_ready_to_first_approval_seconds: { scope: null, repo: 2.6 * HOUR },
                    median_first_approval_to_merge_seconds: { scope: null, repo: 3.4 * HOUR },
                    before_first_approval_share: { scope: null, repo: 0.52 },
                    pushes_after_approval_per_merged_pr: { scope: null, repo: 0.9 },
                    merge_queue_attempts_per_merged_pr: { scope: null, repo: 1.3 },
                    failed_merge_queue_share: { scope: null, repo: 0.21 },
                    lead_time: {
                        ...SUMMARY.lead_time,
                        merged_pr_count: 0,
                        deployed_merged_pr_count: 0,
                        open_to_deploy: { scope: null, repo: distribution(12, 640) },
                        open_to_merge: { scope: null, repo: distribution(10, 640) },
                        merge_to_deploy: { scope: null, repo: distribution(1.1, 640) },
                    },
                },
                'api/projects/:team_id/engineering_analytics/team_merge_trend/': {
                    has_membership_data: false,
                    points: [],
                },
                'api/projects/:team_id/engineering_analytics/team_ci_health/': {
                    ...TEAM_CI_HEALTH,
                    items: [{ ...TEAM_CI_HEALTH.items[0], merged_pr_count: null, merged_pr_count_prior: null }],
                },
            },
        }),
    ],
}
