import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AfterClickingCard } from './AfterClickingCard'
import { emailImpactLogic } from './emailImpactLogic'

describe('AfterClickingCard', () => {
    let intents: unknown[]

    beforeEach(() => {
        intents = []
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/impact/': () => [200, null],
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': async ({ request }) => {
                    intents.push(await request.json())
                    return [200, MOCK_DEFAULT_TEAM]
                },
            },
        })
        initKeaTests()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, session_recording_opt_in: false })
    })

    afterEach(cleanup)

    it('records a cross-sell intent from the email impact tab when someone turns on session replay', async () => {
        render(
            <Provider>
                <BindLogic logic={emailImpactLogic} props={{ workflowId: 'workflow-1' }}>
                    <AfterClickingCard />
                </BindLogic>
            </Provider>
        )

        fireEvent.click(screen.getByText('Turn on session replay'))

        await waitFor(() => expect(intents).toHaveLength(1))
        expect(intents[0]).toEqual({
            product_type: 'session_replay',
            intent_context: 'transactional_email_impact_turn_on_replay',
            metadata: { from: 'workflows', to: 'session_replay', type: 'cross_sell' },
        })
    })
})
