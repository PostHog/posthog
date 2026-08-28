import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { DoraOverviewApi, GitHubSourceApi } from '../generated/api.schemas'

const SOURCES: GitHubSourceApi[] = [{ id: 'src-1', repo: 'PostHog/posthog', prefix: '', synced: true }]

// Eight daily buckets ending at the mock date, with a quiet weekend (Jul 12 thin, Jul 13 empty)
// so the box plot shows both dense boxes and a gap slot.
const BUCKET_DAYS = ['08', '09', '10', '11', '12', '13', '14', '15']

const FREQUENCY_COUNTS = [9, 11, 12, 8, 2, 0, 10, 8]

// Per-bucket [count, min, p25, p50, mean, p75, max] in seconds; null marks the empty weekend day.
const LEAD_TIME_STATS: (number[] | null)[] = [
    [16, 480, 1200, 2100, 2900, 4200, 9000],
    [19, 600, 1500, 2400, 3300, 3900, 12600],
    [21, 540, 1320, 2280, 3100, 4500, 10800],
    [14, 660, 1440, 2700, 4400, 5400, 21600],
    [3, 900, 1800, 3600, 6600, 7200, 14400],
    null,
    [17, 480, 1260, 2160, 2700, 3600, 8400],
    [13, 600, 1380, 2520, 3500, 4800, 11400],
]

const DORA: DoraOverviewApi = {
    deploy_data_available: true,
    environment_scope: 'production',
    environments: ['prod-us', 'prod-eu', 'dev'],
    has_membership_data: true,
    github_teams: ['team-devex', 'team-ingestion', 'team-replay'],
    deployment_count: 60,
    deployment_count_prev: 52,
    deployments_per_day: 8.6,
    deployments_per_day_prev: 7.4,
    median_merge_to_deploy_seconds: 2520,
    median_merge_to_deploy_seconds_prev: 3300,
    deployed_pr_count: 103,
    deployed_pr_count_prev: 88,
    failed_deployment_count: 2,
    failed_deployment_count_prev: 4,
    failed_deployment_share: 0.032,
    failed_deployment_share_prev: 0.071,
    median_failed_deploy_to_next_success_seconds: 2280,
    median_failed_deploy_to_next_success_seconds_prev: 3540,
    merged_pr_count: 112,
    unattributed_merged_pr_share: 0.045,
    latest_deploy_status_at: '2026-07-14T22:00:00Z',
    deployment_frequency_series: BUCKET_DAYS.map((day, i) => ({
        bucket_start: `2026-07-${day}T00:00:00Z`,
        deployment_count: FREQUENCY_COUNTS[i],
    })),
    merge_to_deploy_series: BUCKET_DAYS.map((day, i) => {
        const stats = LEAD_TIME_STATS[i]
        return {
            bucket_start: `2026-07-${day}T00:00:00Z`,
            deployed_pr_count: stats ? stats[0] : 0,
            min_seconds: stats ? stats[1] : null,
            p25_seconds: stats ? stats[2] : null,
            p50_seconds: stats ? stats[3] : null,
            mean_seconds: stats ? stats[4] : null,
            p75_seconds: stats ? stats[5] : null,
            max_seconds: stats ? stats[6] : null,
        }
    }),
    series_granularity: 'day',
}

const EMPTY_DORA: DoraOverviewApi = {
    ...DORA,
    deploy_data_available: false,
    environment_scope: 'persistent',
    environments: [],
    github_teams: [],
    has_membership_data: false,
    deployment_count: 0,
    deployment_count_prev: 0,
    deployments_per_day: null,
    deployments_per_day_prev: null,
    median_merge_to_deploy_seconds: null,
    median_merge_to_deploy_seconds_prev: null,
    deployed_pr_count: 0,
    deployed_pr_count_prev: 0,
    failed_deployment_count: 0,
    failed_deployment_count_prev: 0,
    failed_deployment_share: null,
    failed_deployment_share_prev: null,
    median_failed_deploy_to_next_success_seconds: null,
    median_failed_deploy_to_next_success_seconds_prev: null,
    merged_pr_count: 0,
    unattributed_merged_pr_share: null,
    latest_deploy_status_at: null,
    deployment_frequency_series: [],
    merge_to_deploy_series: [],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Engineering Analytics/Health',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-15',
        featureFlags: [FEATURE_FLAGS.ENGINEERING_ANALYTICS],
        testOptions: {
            // Past the skeletons once the box-plot chart has rendered.
            waitForSelector: '[data-attr="engineering-analytics-dora-box-plot"] canvas',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/sources/': SOURCES,
                'api/projects/:team_id/engineering_analytics/dora/': DORA,
                // Loaded by the shared scene logic on mount, whichever tab is active.
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
                'api/projects/:team_id/engineering_analytics/quarantine/': {
                    available: false,
                    entries: [],
                    source_url: '',
                },
                'api/projects/:team_id/engineering_analytics/flaky_tests/': {
                    items: [],
                    truncated: false,
                    limit: 100,
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const Health: Story = {
    render: () => <App />,
    parameters: { pageUrl: urls.engineeringAnalyticsHealth() },
}

// The not-yet-synced state: the deploy endpoints aren't enabled on the GitHub source, so the tab
// explains what to enable instead of showing zeros.
export const HealthWithoutDeployData: Story = {
    render: () => <App />,
    parameters: {
        pageUrl: urls.engineeringAnalyticsHealth(),
        testOptions: {
            waitForSelector: '[data-attr="engineering-analytics-dora-no-deploy-data"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/dora/': EMPTY_DORA,
            },
        }),
    ],
}
