import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { WorkflowsRunLinkTagSettings } from './WorkflowsRunLinkTagSettings'

describe('<WorkflowsRunLinkTagSettings />', () => {
    let patchBodies: Record<string, unknown>[]

    beforeEach(() => {
        patchBodies = []
        useMocks({
            patch: {
                '/api/environments/:team_id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    patchBodies.push(body)
                    return [200, { ...MOCK_DEFAULT_TEAM, ...body }]
                },
            },
        })
        initKeaTests()
        teamLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        { stored: undefined, shownOn: true, saved: false },
        { stored: false, shownOn: false, saved: true },
    ])('stored $stored shows on=$shownOn, and a click sends only $saved', async ({ stored, shownOn, saved }) => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            workflows_config: {
                capture_workflows_engagement_events: true,
                email_utm_tags_enabled: true,
                ...(stored === undefined ? {} : { email_workflow_run_link_tag_enabled: stored }),
            },
        })
        render(<WorkflowsRunLinkTagSettings />)
        const toggle = screen.getByLabelText('Connect tracked email clicks to sessions')
        expect(toggle).toHaveAttribute('aria-checked', String(shownOn))

        await userEvent.click(toggle)

        await waitFor(() => expect(patchBodies).toHaveLength(1))
        expect(patchBodies[0]).toEqual({ workflows_config: { email_workflow_run_link_tag_enabled: saved } })
        await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', String(saved)))
    })

    it('keeps the switch off for a member without project admin, whose save the project API would refuse', async () => {
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Member,
            workflows_config: { capture_workflows_engagement_events: true, email_workflow_run_link_tag_enabled: false },
        })
        teamLogic.mount()
        render(<WorkflowsRunLinkTagSettings />)
        const toggle = screen.getByLabelText('Connect tracked email clicks to sessions')

        await userEvent.click(toggle)

        expect(toggle).toBeDisabled()
        expect(toggle).toHaveAttribute('aria-checked', 'false')
        expect(patchBodies).toEqual([])
    })
})
