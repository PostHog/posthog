import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { ScoutRepositoriesPicker } from './ScoutRepositoriesPicker'

/** Stories drive the picker like its call sites do: selection state lives outside. */
function ControlledPicker({ compact }: { compact?: boolean }): JSX.Element {
    const [selectedRepositories, setSelectedRepositories] = useState<string[]>(['acme-co/web'])
    return (
        <ScoutRepositoriesPicker
            compact={compact}
            selectedRepositories={selectedRepositories}
            onChange={setSelectedRepositories}
        />
    )
}

const githubIntegration = {
    id: 7,
    kind: 'github',
    display_name: 'acme-co',
    config: { account: { type: 'org' } },
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    errors: null,
}

const githubReposResponse = {
    repositories: [
        {
            id: 1,
            name: 'web',
            full_name: 'acme-co/web',
            private: false,
            default_branch: 'main',
            language: 'TypeScript',
            pushed_at: '2026-07-20T10:00:00Z',
            archived: false,
            can_push: true,
        },
        {
            id: 2,
            name: 'api',
            full_name: 'acme-co/api',
            private: true,
            default_branch: 'master',
            language: 'Python',
            pushed_at: '2026-07-14T10:00:00Z',
            archived: false,
            // A scout never pushes, so an option without write access is still a fine pin.
            can_push: false,
        },
        {
            id: 3,
            name: 'legacy-billing',
            full_name: 'acme-co/legacy-billing',
            private: true,
            default_branch: 'main',
            language: 'Ruby',
            pushed_at: '2025-02-01T10:00:00Z',
            archived: true,
            can_push: true,
        },
    ],
    has_more: false,
    total: 3,
}

const meta: Meta<typeof ScoutRepositoriesPicker> = {
    title: 'Scenes-App/Inbox/ScoutRepositoriesPicker',
    component: ScoutRepositoriesPicker,
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/integrations/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [githubIntegration],
                },
                '/api/environments/:team_id/integrations/:id/github_repos': githubReposResponse,
            },
        }),
    ],
    parameters: {
        testOptions: { waitForLoadersToDisappear: true },
    },
}
export default meta
type Story = StoryObj<typeof ScoutRepositoriesPicker>

export const CreateDialogVariant: Story = {
    render: () => (
        <div className="max-w-2xl p-4">
            <ControlledPicker />
        </div>
    ),
}

export const ScoutSettingsVariant: Story = {
    render: () => (
        <div className="max-w-md p-4">
            <ControlledPicker compact />
        </div>
    ),
}

export const NoGitHubConnection: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/integrations/': { count: 0, next: null, previous: null, results: [] },
            },
        }),
    ],
    render: () => (
        <div className="max-w-2xl p-4">
            <ControlledPicker />
        </div>
    ),
}
