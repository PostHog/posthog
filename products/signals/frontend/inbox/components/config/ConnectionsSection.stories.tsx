import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import type { GitHubReadinessStatusEnumApi } from 'products/integrations/frontend/generated/api.schemas'

import { mockTeamConfig } from '../../__mocks__/inboxMocks'
import { ConnectionsSection } from './ConnectionsSection'

interface ConnectionStoryProps {
    readiness: GitHubReadinessStatusEnumApi
    narrow?: boolean
}

function ConnectionStory({ readiness, narrow = false }: ConnectionStoryProps): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/signals/config/': { ...mockTeamConfig, github_readiness: readiness },
        },
    })
    return (
        <div className={narrow ? 'w-128' : 'w-full max-w-4xl'}>
            <ConnectionsSection />
        </div>
    )
}

const meta: Meta<typeof ConnectionStory> = {
    title: 'Signals/Inbox/Connections',
    component: ConnectionStory,
}
export default meta
type Story = StoryObj<typeof meta>

export const Connected: Story = { args: { readiness: 'ready' } }
export const NotConnected: Story = { args: { readiness: 'not_connected' } }
export const ReconnectRequired: Story = { args: { readiness: 'reconnect_required', narrow: true } }
export const NoRepositories: Story = { args: { readiness: 'no_repositories', narrow: true } }
export const TemporarilyUnavailable: Story = { args: { readiness: 'temporarily_unavailable' } }
