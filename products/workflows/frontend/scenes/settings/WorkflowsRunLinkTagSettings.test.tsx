import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

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
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            workflows_config: {
                capture_workflows_engagement_events: true,
                email_utm_tags_enabled: true,
            },
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('shows the tag as on for a team that never set it, and turning it off sends only that field', async () => {
        render(<WorkflowsRunLinkTagSettings />)
        const toggle = screen.getByLabelText('Add ph_workflow_run to tracked email links')
        expect(toggle).toBeChecked()

        await userEvent.click(toggle)

        await waitFor(() => expect(patchBodies).toHaveLength(1))
        expect(patchBodies[0]).toEqual({ workflows_config: { email_workflow_run_link_tag_enabled: false } })
        await waitFor(() => expect(toggle).not.toBeChecked())
    })
})
