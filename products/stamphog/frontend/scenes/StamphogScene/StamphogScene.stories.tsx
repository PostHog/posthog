import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { StamphogAvailableRepositoriesApi, StamphogRepoConfigApi } from '../../generated/api.schemas'

const repoConfig = (index: number, overrides: Partial<StamphogRepoConfigApi>): StamphogRepoConfigApi =>
    ({
        id: `00000000-0000-0000-0000-${String(index).padStart(12, '0')}`,
        repository: 'PostHog/posthog',
        provider: 'github',
        enabled: true,
        digest_enabled: false,
        installation_id: '1',
        review_mode: 'all',
        trigger_label: 'stamphog',
        user_access_level: 'manager',
        created_at: '2026-07-01T00:00:00Z',
        updated_at: '2026-07-01T00:00:00Z',
        ...overrides,
    }) as StamphogRepoConfigApi

const page = (results: StamphogRepoConfigApi[]): Record<string, unknown> => ({
    count: results.length,
    next: null,
    previous: null,
    results,
})

// One row per status the table can show: reviewing, reviewing on a label, and paused with or without the digest.
const repoConfigs = page([
    repoConfig(1, { repository: 'PostHog/posthog', digest_enabled: true }),
    repoConfig(2, {
        repository: 'PostHog/posthog-js',
        review_mode: 'label',
        trigger_label: 'needs-review',
        created_at: '2026-08-02T00:00:00Z',
    }),
    repoConfig(3, {
        repository: 'PostHog/posthog.com',
        enabled: false,
        digest_enabled: true,
        created_at: '2026-08-10T00:00:00Z',
    }),
    repoConfig(4, { repository: 'PostHog/hogland', enabled: false, created_at: '2026-08-12T00:00:00Z' }),
])

const availableRepositories: StamphogAvailableRepositoriesApi = {
    repositories: ['PostHog/charts', 'PostHog/plugin-server', 'PostHog/posthog-python', 'PostHog/wizard'],
    total_count: 4,
    has_installation: true,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Stamphog/Repositories',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-08-17 23:30:00',
        pageUrl: urls.stamphog(),
        testOptions: { waitForSelector: '[data-attr="stamphog-repo-table"]' },
    },
    // With no repository loaded the page reads the access level from the app context, so a fresh team needs it there.
    beforeEach: () => {
        const context = window.POSTHOG_APP_CONTEXT!
        const previous = context.resource_access_control
        context.resource_access_control = {
            ...previous,
            [AccessControlResourceType.Stamphog]: AccessControlLevel.Editor,
        }
        return () => {
            context.resource_access_control = previous
        }
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/stamphog/repo_configs/': repoConfigs,
                '/api/projects/:team_id/stamphog/repo_configs/available_repositories/': availableRepositories,
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

// Expands the label-triggered row, the only one that shows the trigger label input.
export const RepositoryExpanded: StoryObj = {
    play: async ({ canvasElement }) => {
        const labelRow = (await within(canvasElement).findByText('posthog-js', {}, { timeout: 15000 })).closest('tr')
        await userEvent.click(within(labelRow!).getByTitle('Show more'))
        await within(canvasElement).findByText('Daily digest')
    },
}

export const AddRepositoryPickerOpen: StoryObj = {
    play: async ({ canvasElement }) => {
        const picker = await within(canvasElement).findByPlaceholderText(
            'Search 4 repositories to add',
            {},
            { timeout: 15000 }
        )
        await userEvent.click(picker)
        await within(document.body).findByText('PostHog/charts')
    },
}

// Connected to GitHub, nothing added yet: the add bar is the whole page.
export const FirstRepository: StoryObj = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/stamphog/repo_configs/': page([]),
            },
        }),
    ],
}

export const NotConnected: StoryObj = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/stamphog/repo_configs/': page([]),
                '/api/projects/:team_id/stamphog/repo_configs/available_repositories/': {
                    repositories: [],
                    total_count: 0,
                    has_installation: false,
                },
            },
        }),
    ],
}

// GitHub sent the member back with a code: the sync records their repositories and turns no reviews on.
export const ConnectedAfterSync: StoryObj = {
    parameters: {
        pageUrl: `${urls.stamphogCallback()}?code=example-code&state=example-state`,
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/projects/:team_id/stamphog/repo_configs/sync_installation/': {
                    synced: [],
                    skipped: ['PostHog/charts'],
                    available_count: 4,
                    app_not_installed: false,
                    installations: [],
                },
            },
        }),
    ],
}
