import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { useStorybookMocks } from '~/mocks/browser'

import { mockTeamConfig } from '../../__mocks__/inboxMocks'
import type { GitHubAccessBlocker } from '../../logics/githubConnectionPresentation'
import { GitHubConnectionNotice } from './GitHubConnectionNotice'

interface NoticeStoryProps {
    blocker: GitHubAccessBlocker
    membershipLevel: OrganizationMembershipLevel
    hasReports: boolean | null
}

function NoticeStory({ blocker, membershipLevel, hasReports }: NoticeStoryProps): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/signals/config/': {
                ...mockTeamConfig,
                github_readiness: blocker,
                github_optional_available: false,
                research_access: { mode: 'blocked', blocker },
            },
        },
    })
    useEffect(() => {
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, effective_membership_level: membershipLevel })
    }, [membershipLevel])
    return (
        <div className="max-w-4xl p-4">
            <GitHubConnectionNotice hasReports={hasReports} />
        </div>
    )
}

const meta: Meta<typeof NoticeStory> = {
    title: 'Signals/Inbox/GitHubConnectionNotice',
    component: NoticeStory,
    args: { blocker: 'not_connected', membershipLevel: OrganizationMembershipLevel.Admin, hasReports: true },
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta
type Story = StoryObj<typeof meta>

export const Connect: Story = {}
export const Reconnect: Story = { args: { blocker: 'reconnect_required' } }
export const GrantAccess: Story = { args: { blocker: 'no_repositories', hasReports: false } }
export const AskAdmin: Story = { args: { membershipLevel: OrganizationMembershipLevel.Member } }
