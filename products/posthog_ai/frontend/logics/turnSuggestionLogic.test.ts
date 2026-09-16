import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import type { StoredLogEntry } from '../types/wireTypes'
import { runStreamLogic } from './runStreamLogic'
import { turnSuggestionLogic } from './turnSuggestionLogic'

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
    title: 'Get this every week in Slack',
    description: 'A scout can rerun this count each week.',
    scout: { displayName: 'Weekly signups', description: '', body: '# Weekly signups', cadence: 'weekly' },
}

describe('turnSuggestionLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('reveals after the delay, hides on dismiss, and mutes the rest of the conversation', async () => {
        const stream = runStreamLogic({ streamKey: STREAM_KEY })
        stream.mount()
        await expectLogic(stream, () => {
            stream.actions.ingestAcpFrame(notification('_posthog/user_message', { content: 'How many signups?' }))
            stream.actions.ingestAcpFrame(notification('_posthog/turn_suggestion', SUGGESTION))
        }).toFinishAllListeners()

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
    })
})
