import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { GitHubSourceApi, TeamCIHealthItemApi, TeamCIHealthListApi } from '../generated/api.schemas'

const SOURCES: GitHubSourceApi[] = [{ id: 'src-1', repo: 'PostHog/posthog', prefix: '' }]

function healthRow(overrides: Partial<TeamCIHealthItemApi> & { owner_team: string }): TeamCIHealthItemApi {
    return {
        flaky_test_count: 0,
        flaky_test_count_prior: 0,
        regression_test_count: 0,
        regression_test_count_prior: 0,
        failed_run_count: 0,
        failed_run_count_prior: 0,
        same_commit_recovery_run_count: 0,
        same_commit_recovery_run_count_prior: 0,
        quarantined_failed_run_count: 0,
        quarantined_failed_run_count_prior: 0,
        last_seen_at: null,
        test_file_count: null,
        test_file_count_prior: null,
        merged_pr_count: null,
        merged_pr_count_prior: null,
        ...overrides,
    }
}

// The table's whole state space: a signal row, the unowned bucket, and a census-only quiet team.
const TEAM_CI_HEALTH: TeamCIHealthListApi = {
    items: [
        healthRow({
            owner_team: 'unowned',
            flaky_test_count: 12,
            regression_test_count: 41,
            failed_run_count: 512,
            last_seen_at: '2026-07-02T09:12:00Z',
            test_file_count: 581,
            test_file_count_prior: 590,
        }),
        healthRow({
            owner_team: 'team-replay',
            flaky_test_count: 8,
            regression_test_count: 3,
            failed_run_count: 96,
            last_seen_at: '2026-07-02T08:40:00Z',
            test_file_count: 204,
            test_file_count_prior: 201,
            merged_pr_count: 31,
            merged_pr_count_prior: 28,
        }),
        healthRow({
            owner_team: 'team-quiet-green',
            test_file_count: 64,
            test_file_count_prior: 60,
            merged_pr_count: 12,
            merged_pr_count_prior: 15,
        }),
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
