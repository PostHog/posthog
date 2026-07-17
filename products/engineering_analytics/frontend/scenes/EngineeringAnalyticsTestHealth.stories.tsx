import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type {
    BrokenTestsResultApi,
    FlakyTestListApi,
    GitHubSourceApi,
    QuarantineFileApi,
} from '../generated/api.schemas'

// A fixed 24-slot hourly sparkline (oldest first) with the given recent tail — mirrors the endpoint's trend_24h.
const spark = (tail: number[]): number[] => [...new Array(24 - tail.length).fill(0), ...tail]

const FLAKY_TESTS: FlakyTestListApi = {
    items: [
        {
            nodeid: 'posthog/api/test/test_decide/TestDecide::test_flag_rollout_consistency',
            selector: 'posthog/api/test/test_decide.py::TestDecide::test_flag_rollout_consistency',
            classification: 'confirmed_flake',
            rerun_passed_run_count: 6,
            failed_run_count: 8,
            failed_pr_count: 3,
            master_failed_run_count: 2,
            quarantined_failed_run_count: 0,
            last_signal_at: '2026-07-01T18:30:00Z',
        },
        {
            nodeid: 'posthog/tasks/test/test_usage_report/TestUsageReport::test_full_report',
            selector: 'posthog/tasks/test/test_usage_report.py::TestUsageReport::test_full_report',
            classification: 'suspected_regression',
            rerun_passed_run_count: 0,
            failed_run_count: 9,
            failed_pr_count: 4,
            master_failed_run_count: 5,
            quarantined_failed_run_count: 0,
            last_signal_at: '2026-07-01T09:12:00Z',
        },
        {
            nodeid: 'posthog/hogql/test/test_resolver/TestResolver::test_asterisk_expander',
            selector: 'posthog/hogql/test/test_resolver.py::TestResolver::test_asterisk_expander',
            classification: 'quarantined',
            rerun_passed_run_count: 0,
            failed_run_count: 1,
            failed_pr_count: 1,
            master_failed_run_count: 0,
            quarantined_failed_run_count: 3,
            last_signal_at: '2026-06-30T22:45:00Z',
        },
        {
            nodeid: 'posthog/temporal/tests/batch_exports/test_backfill::test_workflow_timeout',
            selector: 'posthog/temporal/tests/batch_exports/test_backfill.py::test_workflow_timeout',
            classification: 'confirmed_flake',
            rerun_passed_run_count: 1,
            failed_run_count: 1,
            failed_pr_count: 1,
            master_failed_run_count: 0,
            quarantined_failed_run_count: 0,
            last_signal_at: '2026-06-29T14:00:00Z',
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

const BROKEN_TESTS: BrokenTestsResultApi = {
    rows: [
        {
            fingerprint: 'products/checkout/test_flow.py::test_checkout | assert N == N',
            test_id: 'products/checkout/test_flow.py::test_checkout',
            error_signature: 'AssertionError: expected 200, got 500',
            job_name: 'Django tests – Core (12/22)',
            repo: 'PostHog/posthog',
            state: 'breaking_master',
            first_seen: '2026-06-30T08:00:00Z',
            last_seen: '2026-07-02T11:40:00Z',
            occurrences: 41,
            branches: 5,
            master_hits: 6,
            latest_run_id: 9001,
            latest_branch: 'master',
            trend_24h: spark([1, 3, 6, 8]),
        },
        {
            fingerprint: 'posthog/api/test_serializer.py::test_contract | KeyError: N',
            test_id: 'posthog/api/test_serializer.py::test_contract',
            error_signature: 'KeyError: managed_viewset',
            job_name: 'Django tests – Core (4/22)',
            repo: 'PostHog/posthog',
            state: 'novel_burst',
            first_seen: '2026-07-02T05:00:00Z',
            last_seen: '2026-07-02T11:50:00Z',
            occurrences: 9,
            branches: 4,
            master_hits: 0,
            latest_run_id: 9002,
            latest_branch: 'feat/data-catalog',
            trend_24h: spark([2, 7]),
        },
        {
            fingerprint: 'posthog/temporal/test_async.py::test_race | ConnectionResetError',
            test_id: 'posthog/temporal/test_async.py::test_race',
            error_signature: 'ConnectionResetError',
            job_name: 'Playwright (2/8)',
            repo: 'PostHog/posthog',
            state: 'flaky',
            first_seen: '2026-06-28T14:00:00Z',
            last_seen: '2026-07-02T10:00:00Z',
            occurrences: 7,
            branches: 3,
            master_hits: 0,
            latest_run_id: 9004,
            latest_branch: 'fix/async-teardown',
            trend_24h: spark([1, 0, 1, 0, 0, 1]),
        },
        {
            fingerprint: 'posthog/flags/test_rollout.py::test_flag | Timeout',
            test_id: 'posthog/flags/test_rollout.py::test_flag',
            error_signature: 'Timeout waiting for flag',
            job_name: 'Frontend CI (3/6)',
            repo: 'PostHog/posthog',
            state: 'potentially_resolved',
            first_seen: '2026-06-29T09:00:00Z',
            last_seen: '2026-07-02T04:00:00Z',
            occurrences: 12,
            branches: 3,
            master_hits: 2,
            latest_run_id: 9003,
            latest_branch: 'master',
            trend_24h: spark([]),
        },
    ],
    breaking_master_jobs: ['Django tests – Core (12/22)'],
    window_days: 2,
    truncated: false,
    limit: 200,
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
                'api/projects/:team_id/engineering_analytics/broken_tests/': BROKEN_TESTS,
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
