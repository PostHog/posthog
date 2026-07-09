import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { FlakyTestListApi, GitHubSourceApi, QuarantineFileApi } from '../generated/api.schemas'

const FLAKY_TESTS: FlakyTestListApi = {
    items: [
        {
            nodeid: 'posthog/api/test/test_decide/TestDecide::test_flag_rollout_consistency',
            selector: 'posthog/api/test/test_decide.py::TestDecide::test_flag_rollout_consistency',
            rerun_passed_count: 6,
            failed_count: 4,
            failed_pr_count: 3,
            branch_count: 5,
            xfailed_count: 0,
            last_seen_at: '2026-07-01T18:30:00Z',
        },
        {
            nodeid: 'posthog/tasks/test/test_usage_report/TestUsageReport::test_full_report',
            selector: 'posthog/tasks/test/test_usage_report.py::TestUsageReport::test_full_report',
            rerun_passed_count: 0,
            failed_count: 9,
            failed_pr_count: 4,
            branch_count: 4,
            xfailed_count: 0,
            last_seen_at: '2026-07-01T09:12:00Z',
        },
        {
            nodeid: 'posthog/hogql/test/test_resolver/TestResolver::test_asterisk_expander',
            selector: 'posthog/hogql/test/test_resolver.py::TestResolver::test_asterisk_expander',
            rerun_passed_count: 2,
            failed_count: 1,
            failed_pr_count: 1,
            branch_count: 3,
            xfailed_count: 3,
            last_seen_at: '2026-06-30T22:45:00Z',
        },
        {
            nodeid: 'posthog/temporal/tests/batch_exports/test_backfill::test_workflow_timeout',
            selector: 'posthog/temporal/tests/batch_exports/test_backfill.py::test_workflow_timeout',
            rerun_passed_count: 1,
            failed_count: 2,
            failed_pr_count: 2,
            branch_count: 2,
            xfailed_count: 0,
            last_seen_at: '2026-06-29T14:00:00Z',
        },
    ],
    truncated: false,
    limit: 50,
}

const QUARANTINE: QuarantineFileApi = {
    available: true,
    entries: [
        {
            id: 'posthog/hogql/test/test_resolver.py::TestResolver::test_asterisk_expander',
            runner: 'pytest',
            reason: 'Nondeterministic ordering or data',
            owner: '@PostHog/team-hogql',
            issue: 'https://github.com/PostHog/posthog/issues/1',
            added: '2026-06-24',
            expires: '2026-07-08',
            mode: 'run',
            lifecycle: 'active',
            days_until_expiry: 6,
            selector_kind: 'test',
        },
    ],
    parse_errors: [],
    parse_warnings: [],
    repo: { provider: 'github', owner: 'PostHog', name: 'posthog' },
    source_url: 'https://github.com/PostHog/posthog/blob/HEAD/.test_quarantine.json',
    generated_at: '2026-07-02T12:00:00Z',
}

const SOURCES: GitHubSourceApi[] = [{ id: 'src-1', repo: 'PostHog/posthog', prefix: '' }]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Engineering Analytics/Test Health',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-02',
        featureFlags: [FEATURE_FLAGS.ENGINEERING_ANALYTICS],
        testOptions: {
            // A per-row quarantine button only renders once the leaderboard has data rows.
            waitForSelector: '[data-attr="eng-analytics-flaky-quarantine"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/flaky_tests/': FLAKY_TESTS,
                'api/projects/:team_id/engineering_analytics/quarantine/': QUARANTINE,
                'api/projects/:team_id/engineering_analytics/sources/': SOURCES,
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
                'api/projects/:team_id/engineering_analytics/workflow_health/': [],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const FlakyTestLeaderboard: Story = {
    render: () => <App />,
    parameters: { pageUrl: urls.engineeringAnalyticsTestHealth() },
}
