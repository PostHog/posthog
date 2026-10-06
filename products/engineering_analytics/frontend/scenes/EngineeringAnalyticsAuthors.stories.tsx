import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { AuthorFrictionApi, AuthorFrictionListApi, GitHubSourceApi } from '../generated/api.schemas'

const SOURCES: GitHubSourceApi[] = [{ id: 'src-1', repo: 'PostHog/posthog', prefix: '' }]

function author(
    name: string,
    rank: number,
    [queue, review, ci, rework]: [number, number, number, number],
    overrides: Partial<AuthorFrictionApi> = {}
): AuthorFrictionApi {
    return {
        author: name,
        avatar_url: '',
        score: queue + review + ci + rework,
        groups: [
            { group: 'queue', score: queue },
            { group: 'review', score: review },
            { group: 'ci', score: ci },
            { group: 'rework', score: rework },
        ],
        pr_count: 12,
        rank,
        rank_low: Math.max(1, rank - 2),
        rank_high: rank + 4,
        teams: ['team-replay'],
        ...overrides,
    }
}

const FRICTION: AuthorFrictionListApi = {
    available: true,
    window_days: 30,
    ranked_author_count: 6,
    github_team: null,
    has_membership_data: true,
    items: [
        author('jane-dev', 1, [1.4, 0.3, 0.6, 0.2], { pr_count: 18 }),
        author('sam-ops', 2, [0.9, 0.6, 0.3, 0.2], { teams: ['team-infra'] }),
        author('li-web', 3, [0.5, 0.5, 0.2, 0.1], { pr_count: 4, rank_low: 1, rank_high: 6 }),
        author('max-data', 4, [0.3, 0.2, 0.2, 0.1], { teams: ['team-infra'] }),
        author('ana-api', 5, [0.2, 0.2, 0.1, 0.1]),
        author('tom-ui', 6, [0.1, 0.1, 0.1, 0.1], { rank_low: 5 }),
    ],
    teams: [{ github_team: 'team-replay', median_score: 1.0, scored_author_count: 4 }],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Engineering Analytics/Authors',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-24',
        featureFlags: [FEATURE_FLAGS.ENGINEERING_ANALYTICS],
        testOptions: {
            waitForSelector: '[data-attr="engineering-analytics-friction-table"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/author_friction/': FRICTION,
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

export const AuthorFriction: Story = {
    render: () => <App />,
    parameters: { pageUrl: urls.engineeringAnalyticsAuthors() },
}

export const AuthorFrictionNotReady: Story = {
    render: () => <App />,
    parameters: {
        pageUrl: urls.engineeringAnalyticsAuthors(),
        testOptions: { waitForSelector: '[data-attr="engineering-analytics-friction-not-ready"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/engineering_analytics/author_friction/': {
                    ...FRICTION,
                    available: false,
                    ranked_author_count: 0,
                    items: [],
                    teams: [],
                },
            },
        }),
    ],
}
