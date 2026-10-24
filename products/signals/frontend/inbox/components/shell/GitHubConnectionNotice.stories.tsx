import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import type { GitHubReadinessStatusEnumApi } from 'products/signals/frontend/generated/api.schemas'

import { mockTeamConfig } from '../../__mocks__/inboxMocks'
import { GitHubConnectionNotice } from './GitHubConnectionNotice'

interface NoticeStoryProps {
    readiness: GitHubReadinessStatusEnumApi
    narrow?: boolean
}

function NoticeStory({ readiness, narrow = false }: NoticeStoryProps): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/signals/config/': { ...mockTeamConfig, github_readiness: readiness },
        },
    })
    return (
        <div className={narrow ? 'w-128' : 'w-full max-w-4xl'}>
            <GitHubConnectionNotice />
        </div>
    )
}

const meta: Meta<typeof NoticeStory> = {
    title: 'Signals/Inbox/GitHubConnectionNotice',
    component: NoticeStory,
}
export default meta
type Story = StoryObj<typeof meta>

export const NotConnected: Story = { args: { readiness: 'not_connected' } }
export const ReconnectRequired: Story = { args: { readiness: 'reconnect_required', narrow: true } }
export const NoRepositories: Story = { args: { readiness: 'no_repositories' } }
