import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EngagementEventsBanner } from './EngagementEventsBanner'

jest.mock('posthog-js')

describe('EngagementEventsBanner', () => {
    let patched: Record<string, any>[]

    const loadTeam = (effective_membership_level: OrganizationMembershipLevel): void => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level,
            workflows_config: {
                ...MOCK_DEFAULT_TEAM.workflows_config,
                capture_workflows_engagement_events: true,
                email_tracking_consent_mode: 'opt_in',
            },
        })
    }

    beforeEach(() => {
        patched = []
        useMocks({
            patch: {
                '/api/environments/:team_id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    patched.push(body)
                    return [200, { ...MOCK_DEFAULT_TEAM, ...body }]
                },
            },
        })
        initKeaTests()
    })

    it('turns capture off in one click, sending only that setting, and then hides', async () => {
        loadTeam(OrganizationMembershipLevel.Admin)
        render(<EngagementEventsBanner />)

        fireEvent.click(screen.getAllByRole('button', { name: 'Turn off engagement events' })[0])

        await waitFor(() => expect(screen.queryByText(/billed like any other event/)).not.toBeInTheDocument())
        expect(patched).toEqual([{ workflows_config: { capture_workflows_engagement_events: false } }])
    })

    it('does not let a member without admin access turn capture off', () => {
        loadTeam(OrganizationMembershipLevel.Member)
        render(<EngagementEventsBanner />)

        expect(screen.getAllByRole('button', { name: 'Turn off engagement events' })[0]).toHaveAttribute(
            'aria-disabled',
            'true'
        )
    })
})
