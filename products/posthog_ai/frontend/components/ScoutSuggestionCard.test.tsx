import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { runStreamLogic } from '../logics/runStreamLogic'
import { suggestionActionLogic } from '../logics/suggestionActionLogic'
import { ScoutSuggestionCard } from './ScoutSuggestionCard'

jest.mock('products/tasks/frontend/generated/api', () => ({
    tasksRunsCommandCreate: jest.fn(),
    tasksRunsStreamTokenRetrieve: jest.fn(),
}))

const STREAM_KEY = 'scout-suggestion-card-test'
const CARD = { streamKey: STREAM_KEY, turnIndex: 0, sessionId: 'task', revealDelayMs: 0 }
const DRAFTED_INSTRUCTIONS = 'Count signed_up events for the last 7 days and post the total.'

describe('ScoutSuggestionCard', () => {
    beforeEach(async () => {
        useMocks({ get: { '/api/environments/:team_id/integrations': { results: [] } } })
        initKeaTests()
        const stream = runStreamLogic({ streamKey: STREAM_KEY })
        stream.mount()
        await expectLogic(stream, () => {
            stream.actions.ingestAcpFrame({
                type: 'notification',
                notification: { method: '_posthog/user_message', params: { content: 'How many signups?' } },
            })
            stream.actions.ingestAcpFrame({
                type: 'notification',
                notification: {
                    method: '_posthog/turn_suggestion',
                    params: {
                        turnIndex: 0,
                        kind: 'scout',
                        intent: 'metric_state',
                        confidence: 0.9,
                        title: 'Get this in Slack every week',
                        description: 'A scout runs this analysis again every week and posts the results to Slack.',
                        scout: {
                            displayName: 'Weekly signups',
                            description: '',
                            body: DRAFTED_INSTRUCTIONS,
                            cadence: 'weekly',
                        },
                    },
                },
            })
            stream.actions.setTurnSuggestionLedger({ taskId: 'task', muted: false, resolvedTurns: [] })
        }).toFinishAllListeners()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows the drafted instructions before the scout is created, and creates it with the edited ones', () => {
        render(<ScoutSuggestionCard {...CARD} />)

        const instructions = screen.getByDisplayValue(DRAFTED_INSTRUCTIONS)
        fireEvent.change(instructions, { target: { value: 'Count signups only.' } })

        expect(suggestionActionLogic(CARD).values.scoutBody).toBe('Count signups only.')
    })
})
