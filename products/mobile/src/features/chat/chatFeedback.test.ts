import { chatFeedbackKey, chatFeedbackTargets } from './chatFeedback'
import type { SessionThreadItem } from './session/types'

describe('chat feedback targets', () => {
    test('rates only the last answer of a completed turn with its original run and trace', () => {
        const items: SessionThreadItem[] = [
            { kind: 'assistant', id: 'hidden-prompt', text: 'Context loaded', complete: true },
            { kind: 'turn_end', id: 'hidden-end' },
            { kind: 'user', id: 'u0', text: 'First question' },
            { kind: 'error', id: 'failed', message: 'Failed', variant: 'crash' },
            { kind: 'user', id: 'u1', text: 'Second question' },
            { kind: 'assistant', id: 'partial', text: 'I will check', complete: true },
            { kind: 'assistant', id: 'answer', text: 'The result', complete: true },
            { kind: 'turn_end', id: 'end', traceId: 'trace-2', runId: 'previous-run' },
            { kind: 'turn_end', id: 'duplicate-end' },
            { kind: 'user', id: 'u2', text: 'Third question' },
            { kind: 'assistant', id: 'streaming', text: 'Still working', complete: false },
        ]
        expect([...chatFeedbackTargets(items, { sessionId: 'task-1', runtime: 'sandbox' })]).toEqual([
            [
                'answer',
                { sessionId: 'task-1', runtime: 'sandbox', turnIndex: 1, traceId: 'trace-2', runId: 'previous-run' },
            ],
        ])
    })

    test('classic feedback requires a completed answer and its trace', () => {
        const items: SessionThreadItem[] = [
            { kind: 'assistant', id: 'complete', text: 'An answer', complete: true, traceId: 'trace-1' },
            { kind: 'assistant', id: 'missing-trace', text: 'Old answer', complete: true },
            { kind: 'assistant', id: 'streaming', text: 'Working', complete: false, traceId: 'trace-2' },
        ]
        expect([...chatFeedbackTargets(items, { sessionId: 'conversation-1', runtime: 'langgraph' })]).toEqual([
            ['complete', { sessionId: 'conversation-1', runtime: 'langgraph', traceId: 'trace-1' }],
        ])
    })

    test('stored ratings stay separate by account, runtime and turn when a trace is unavailable', () => {
        const target = { sessionId: 'task-1', runtime: 'sandbox' as const, turnIndex: 0 }
        const original = chatFeedbackKey('account-1', target)
        expect(chatFeedbackKey('account-2', target)).not.toBe(original)
        expect(chatFeedbackKey('account-1', { ...target, turnIndex: 1 })).not.toBe(original)
        expect(chatFeedbackKey('account-1', { ...target, runtime: 'langgraph' })).not.toBe(original)
    })
})
