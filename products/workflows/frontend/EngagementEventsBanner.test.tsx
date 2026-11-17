import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EngagementEventsBanner } from './EngagementEventsBanner'

jest.mock('posthog-js')

describe('EngagementEventsBanner', () => {
    let patched: Record<string, any>[]

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
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            workflows_config: { ...MOCK_DEFAULT_TEAM.workflows_config, capture_workflows_engagement_events: true },
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('turns capture off in one click and then hides', async () => {
        render(<EngagementEventsBanner />)

        fireEvent.click(screen.getAllByRole('button', { name: 'Turn off engagement events' })[0])

        await waitFor(() => expect(screen.queryByText(/billed like any other event/)).not.toBeInTheDocument())
        expect(patched).toHaveLength(1)
        expect(patched[0].workflows_config.capture_workflows_engagement_events).toBe(false)
    })
})
