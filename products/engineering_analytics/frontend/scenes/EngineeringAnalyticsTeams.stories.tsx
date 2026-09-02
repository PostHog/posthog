import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { GitHubSourceApi, TeamCIHealthListApi } from '../generated/api.schemas'

const SOURCES: GitHubSourceApi[] = [{ id: 'src-1', repo: 'PostHog/posthog', prefix: '' }]

const TEAM_CI_HEALTH: TeamCIHealthListApi = {
    items: [
        {
            owner_team: 'unowned',
            flaky_test_count: 12,
            flaky_test_count_prior: 30,
            regression_test_count: 41,
            regression_test_count_prior: 22,
            failed_run_count: 512,
            failed_run_count_prior: 431,
            same_commit_recovery_run_count: 18,
            same_commit_recovery_run_count_prior: 40,
            quarantined_failed_run_count: 6,
            quarantined_failed_run_count_prior: 0,
            last_seen_at: '2026-07-02T09:12:00Z',
        },
        {
            owner_team: 'team-replay',
            flaky_test_count: 8,
            flaky_test_count_prior: 8,
            regression_test_count: 3,
            regression_test_count_prior: 1,
            failed_run_count: 96,
            failed_run_count_prior: 240,
            same_commit_recovery_run_count: 11,
            same_commit_recovery_run_count_prior: 12,
            quarantined_failed_run_count: 0,
            quarantined_failed_run_count_prior: 0,
            last_seen_at: '2026-07-02T08:40:00Z',
        },
        {
            owner_team: 'batch-exports',
            flaky_test_count: 0,
            flaky_test_count_prior: 2,
            regression_test_count: 7,
            regression_test_count_prior: 0,
            failed_run_count: 130,
            failed_run_count_prior: 6,
            same_commit_recovery_run_count: 0,
            same_commit_recovery_run_count_prior: 2,
            quarantined_failed_run_count: 0,
            quarantined_failed_run_count_prior: 0,
            last_seen_at: '2026-07-01T22:05:00Z',
        },
        {
            owner_team: 'team-product-analytics',
            flaky_test_count: 1,
            flaky_test_count_prior: 0,
            regression_test_count: 2,
            regression_test_count_prior: 5,
            failed_run_count: 44,
            failed_run_count_prior: 44,
            same_commit_recovery_run_count: 1,
            same_commit_recovery_run_count_prior: 0,
            quarantined_failed_run_count: 0,
            quarantined_failed_run_count_prior: 0,
            last_seen_at: '2026-07-01T16:30:00Z',
        },
    ],
    truncated: false,
    limit: 100,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Engineering Analytics/Teams',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-02',
        featureFlags: [FEATURE_FLAGS.ENGINEERING_ANALYTICS],
        testOptions: {
            waitForSelector: '[data-attr="engineering-analytics-teams-table"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/team_ci_health/': TEAM_CI_HEALTH,
                'api/projects/:team_id/engineering_analytics/sources/': SOURCES,
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

export const TeamCIHealthRoster: Story = {
    render: () => <App />,
    parameters: { pageUrl: urls.engineeringAnalyticsTeams() },
}
