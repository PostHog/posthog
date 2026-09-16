import type { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { StamphogRepoConfigApi } from '../../generated/api.schemas'

const REPO_NAMES = [
    'posthog',
    'posthog-js',
    'posthog-python',
    'posthog-node',
    'posthog-ios',
    'posthog-android',
    'posthog-flutter',
    'posthog-go',
    'posthog-ruby',
    'posthog-php',
    'posthog.com',
    'charts',
    'hogql-parser',
    'plugin-server',
    'rrweb',
    'wizard',
    'hogland',
    'pr-approval-agent',
]

const repoConfig = (name: string, index: number, on: { enabled: boolean; digest: boolean }): StamphogRepoConfigApi =>
    ({
        id: `00000000-0000-0000-0000-${String(index).padStart(12, '0')}`,
        repository: `PostHog/${name}`,
        provider: 'github',
        enabled: on.enabled,
        digest_enabled: on.digest,
        installation_id: '1',
        review_mode: 'all',
        trigger_label: 'stamphog',
        created_at: '2026-07-01T00:00:00Z',
        updated_at: '2026-07-01T00:00:00Z',
    }) as StamphogRepoConfigApi

const page = (results: StamphogRepoConfigApi[]): Record<string, unknown> => ({
    count: results.length,
    next: null,
    previous: null,
    results,
})

const repoConfigs = page(
    REPO_NAMES.map((name, index) =>
        repoConfig(name, index, { enabled: name === 'posthog' || name === 'wizard', digest: name === 'posthog-js' })
    )
)

const allOrgRepoConfigs = page(
    Array.from({ length: 730 }, (_, index) =>
        repoConfig(`service-${String(index).padStart(3, '0')}`, index, { enabled: index % 97 === 0, digest: false })
    )
)

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Stamphog/Repositories',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-08-17 23:30:00',
        pageUrl: urls.stamphog(),
        testOptions: { waitForSelector: '[data-attr="stamphog-repo-status-filter-all"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/stamphog/repo_configs/': repoConfigs,
                '/api/projects/:team_id/stamphog/repo_configs/install_info/': {
                    app_slug: 'stamphog',
                    install_url: 'https://github.com/apps/stamphog/installations/new',
                    authorize_url: 'https://github.com/login/oauth/authorize',
                },
            },
        }),
    ],
}
export default meta

export const RepositoriesList: StoryObj = {}

// Too tall for a useful snapshot. It exists to check that search and the status filter stay fast at org scale.
export const AllOrgRepositories: StoryObj = {
    tags: ['test-skip'],
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/stamphog/repo_configs/': allOrgRepoConfigs,
            },
        }),
    ],
}
