import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { TurnOnEngagementEvents } from './Audience/TurnOnEngagementEvents'
import { WorkflowsEngagementEventsSettings } from './scenes/settings/WorkflowsEngagementEventsSettings'

const CONTROLS = [
    {
        control: 'the Turn on engagement events button',
        element: <TurnOnEngagementEvents surface="engagement" />,
        role: 'button' as const,
    },
    {
        control: 'the settings switch',
        element: <WorkflowsEngagementEventsSettings />,
        role: 'switch' as const,
    },
]

describe('engagement events controls', () => {
    afterEach(() => {
        cleanup()
    })

    it.each(
        CONTROLS.flatMap((control) => [
            { ...control, level: 'member', membershipLevel: OrganizationMembershipLevel.Member, saves: false },
            { ...control, level: 'admin', membershipLevel: OrganizationMembershipLevel.Admin, saves: true },
        ])
    )('$control for a project $level saves on click: $saves', async ({ element, role, membershipLevel, saves }) => {
        const team: TeamType = {
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: membershipLevel,
            workflows_config: { capture_workflows_engagement_events: false },
        }
        initKeaTests(true, team)
        const teamUpdates: Partial<TeamType>[] = []
        useMocks({
            patch: {
                '/api/projects/:team_id/': async ({ request }) => {
                    teamUpdates.push((await request.json()) as Partial<TeamType>)
                    return [200, { ...team, workflows_config: { capture_workflows_engagement_events: true } }]
                },
            },
        })

        render(<Provider>{element}</Provider>)
        fireEvent.click(screen.getByRole(role))
        await expectLogic(teamLogic).toFinishAllListeners()

        expect(teamUpdates).toHaveLength(saves ? 1 : 0)
    })
})
