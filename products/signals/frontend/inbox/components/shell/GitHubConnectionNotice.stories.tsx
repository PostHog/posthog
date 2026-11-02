import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import type { GitHubReadinessStatusEnumApi } from '../../../generated/api.schemas'
import { mockTeamConfig } from '../../__mocks__/inboxMocks'
import { GitHubConnectionNotice } from './GitHubConnectionNotice'

interface NoticeStoryProps {
    readiness: GitHubReadinessStatusEnumApi
    optional: boolean
}

function NoticeStory({ readiness, optional }: NoticeStoryProps): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/signals/config/': {
                ...mockTeamConfig,
                github_readiness: readiness,
                github_optional_available: optional,
                research_access: { mode: optional ? 'data_only' : 'blocked', blocker: optional ? null : readiness },
            },
        },
    })
    return <GitHubConnectionNotice />
}

const meta: Meta<typeof NoticeStory> = {
    title: 'Signals/Inbox/GitHubConnectionNotice',
    component: NoticeStory,
    args: { readiness: 'not_connected', optional: false },
}
export default meta
type Story = StoryObj<typeof meta>

export const Connect: Story = {}
export const Reconnect: Story = { args: { readiness: 'reconnect_required' } }
export const GrantAccess: Story = { args: { readiness: 'no_repositories' } }
export const TemporaryFailure: Story = { args: { readiness: 'temporarily_unavailable' } }
export const DataOnly: Story = { args: { optional: true } }
