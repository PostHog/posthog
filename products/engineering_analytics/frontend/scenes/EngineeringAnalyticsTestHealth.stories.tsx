import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { GitHubSourceApi, QuarantineFileApi, TrunkQuarantineDebtApi } from '../generated/api.schemas'

const QUARANTINE: QuarantineFileApi = {
    available: true,
    entries: [],
    parse_errors: [],
    parse_warnings: [],
    repo: { provider: 'github', owner: 'PostHog', name: 'posthog' },
    source_url: 'https://github.com/PostHog/posthog/blob/HEAD/.test_quarantine.json',
    generated_at: '2026-07-02T12:00:00Z',
}

const SOURCES: GitHubSourceApi[] = [{ id: 'src-1', repo: 'PostHog/posthog', prefix: '' }]

const TRUNK_QUARANTINE: TrunkQuarantineDebtApi = {
    available: true,
    ttl_days: 15,
    repository: 'PostHog/posthog',
    trunk_url: 'https://app.trunk.io/posthog-inc/flaky-tests?repo=PostHog/posthog',
    teams: [
        { owner_team: 'batch-exports', test_count: 1, overdue_count: 1, oldest_age_days: 44 },
        { owner_team: 'team-replay', test_count: 1, overdue_count: 1, oldest_age_days: 38 },
        { owner_team: 'unowned', test_count: 1, overdue_count: 0, oldest_age_days: 9 },
    ],
    tests: [
        {
            runner: 'pytest',
            nodeid: 'products/batch_exports/backend/tests/test_snowflake.py::TestSnowflakeExport::test_resume',
            file: 'products/batch_exports/backend/tests/test_snowflake.py',
            owner_team: 'batch-exports',
            status: 'FLAKY',
            quarantine_setting: 'AUTO_QUARANTINE',
            quarantined_at: '2026-05-19T08:00:00Z',
            age_days: 44,
            overdue: true,
            trunk_url: 'https://app.trunk.io/posthog-inc/flaky-tests/test/t-1?repo=PostHog/posthog',
        },
        {
            runner: 'pytest',
            nodeid: 'posthog/session_recordings/test/test_snapshots.py::TestSnapshots::test_batching',
            file: 'posthog/session_recordings/test/test_snapshots.py',
            owner_team: 'team-replay',
            status: 'FLAKY',
            quarantine_setting: 'AUTO_QUARANTINE',
            quarantined_at: '2026-05-25T08:00:00Z',
            age_days: 38,
            overdue: true,
            trunk_url: 'https://app.trunk.io/posthog-inc/flaky-tests/test/t-2?repo=PostHog/posthog',
        },
        {
            runner: 'jest',
            nodeid: 'frontend/src/lib/components/ActivityLog/activityLogLogic.test.tsx::humanizes flag changes',
            file: 'frontend/src/lib/components/ActivityLog/activityLogLogic.test.tsx',
            owner_team: 'unowned',
            status: 'FLAKY',
            quarantine_setting: 'AUTO_QUARANTINE',
            quarantined_at: '2026-06-23T08:00:00Z',
            age_days: 9,
            overdue: false,
            trunk_url: null,
        },
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Engineering Analytics/Test Health',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-02',
        featureFlags: [FEATURE_FLAGS.ENGINEERING_ANALYTICS],
        testOptions: {
            // The debt board's team table only renders once the trunk quarantine data loaded.
            waitForSelector: '[data-attr="engineering-analytics-trunk-debt-teams-table"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/quarantine/': QUARANTINE,
                'api/projects/:team_id/engineering_analytics/trunk_quarantine/': TRUNK_QUARANTINE,
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

export const TrunkQuarantineDebt: Story = {
    render: () => <App />,
    parameters: { pageUrl: urls.engineeringAnalyticsTestHealth() },
}
