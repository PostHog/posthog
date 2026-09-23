import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { turnSuggestionsResolveCreate } from '../generated/api'
import type { StoredLogEntry } from '../types/wireTypes'
import { runStreamLogic } from './runStreamLogic'
import { suggestionActionLogic } from './suggestionActionLogic'
import { turnSuggestionLogic } from './turnSuggestionLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    turnSuggestionsResolveCreate: jest.fn(() => Promise.resolve({ recorded: true })),
}))

jest.mock('products/tasks/frontend/generated/api', () => ({
    tasksRunsCommandCreate: jest.fn(),
    tasksRunsStreamTokenRetrieve: jest.fn(),
}))

const STREAM_KEY = 'turn-suggestion-logic-test'

function notification(method: string, params: Record<string, unknown>): StoredLogEntry {
    return { type: 'notification', notification: { method, params } }
}

const SUGGESTION = {
    turnIndex: 0,
    kind: 'scout',
    intent: 'metric_state',
    confidence: 0.9,
    title: 'Get this in Slack every week',
    description: 'A scout runs this analysis again every week and posts the results to Slack.',
    scout: { displayName: 'Weekly signups', description: '', body: '# Weekly signups', cadence: 'weekly' },
}

describe('turnSuggestionLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.mocked(turnSuggestionsResolveCreate).mockClear()
    })

    async function mountStreamWithSuggestion(): Promise<ReturnType<typeof runStreamLogic.build>> {
        const stream = runStreamLogic({ streamKey: STREAM_KEY })
        stream.mount()
        await expectLogic(stream, () => {
            stream.actions.ingestAcpFrame(notification('_posthog/user_message', { content: 'How many signups?' }))
            stream.actions.ingestAcpFrame(notification('_posthog/turn_suggestion', SUGGESTION))
        }).toFinishAllListeners()
        return stream
    }

    it('reveals after the delay, hides on dismiss, mutes the rest of the conversation and records the dismissal', async () => {
        const stream = await mountStreamWithSuggestion()

        // Fake timers only around the reveal: expectLogic waits on real timers.
        jest.useFakeTimers()
        const logic = turnSuggestionLogic({
            streamKey: STREAM_KEY,
            turnIndex: 0,
            sessionId: 'task',
            revealDelayMs: 1000,
        })
        logic.mount()
        expect(logic.values.suggestion).toMatchObject({ kind: 'scout' })
        expect(logic.values.visible).toBe(false)

        jest.advanceTimersByTime(1000)
        expect(logic.values.visible).toBe(true)
        jest.useRealTimers()

        logic.actions.dismiss()
        expect(logic.values.visible).toBe(false)
        expect(stream.values.turnSuggestionsMuted).toBe(true)
        expect(turnSuggestionsResolveCreate).toHaveBeenCalledWith(expect.any(String), {
            task_id: 'task',
            turn_index: 0,
            resolution: 'dismissed',
        })
    })

    it('records no accept when the accept skipped the create', async () => {
        const stream = await mountStreamWithSuggestion()
        const card = { streamKey: STREAM_KEY, turnIndex: 0, sessionId: 'task', revealDelayMs: 0 }
        const logic = suggestionActionLogic(card)
        logic.mount()
        expect(logic.values.acceptDisabledReason).not.toBeNull()

        await expectLogic(logic, () => {
            logic.actions.accept()
        }).toFinishAllListeners()

        expect(logic.values.accepted).toBeNull()
        expect(turnSuggestionLogic(card).values.completed).toBe(false)
        expect(stream.values.turnSuggestionAcceptedHere).toBeNull()
        expect(turnSuggestionsResolveCreate).not.toHaveBeenCalled()
    })
})
