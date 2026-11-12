import { chatFeedbackKey, chatReplyActions } from './chatFeedback'
import type { SessionThreadItem } from './session/types'

describe('chat reply actions', () => {
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
        expect([...chatReplyActions(items, { sessionId: 'task-1', runtime: 'sandbox' }, 'working')]).toEqual([
            ['hidden-prompt', {}],
            [
                'answer',
                {
                    feedback: {
                        sessionId: 'task-1',
                        runtime: 'sandbox',
                        turnIndex: 1,
                        traceId: 'trace-2',
                        runId: 'previous-run',
                    },
                },
            ],
        ])
    })

    test('classic replies end at the next user message and feedback requires a trace', () => {
        const items: SessionThreadItem[] = [
            { kind: 'user', id: 'u1', text: 'First question' },
            { kind: 'assistant', id: 'intro', text: 'I will check', complete: true, traceId: 'trace-1' },
            { kind: 'assistant', id: 'complete', text: 'An answer', complete: true, traceId: 'trace-1' },
            { kind: 'user', id: 'u2', text: 'Second question' },
            { kind: 'assistant', id: 'missing-trace', text: 'Old answer', complete: true },
            { kind: 'user', id: 'u3', text: 'Third question' },
            { kind: 'assistant', id: 'streaming', text: 'Working', complete: false, traceId: 'trace-3' },
        ]
        expect([...chatReplyActions(items, { sessionId: 'conversation-1', runtime: 'langgraph' }, 'idle')]).toEqual([
            ['complete', { feedback: { sessionId: 'conversation-1', runtime: 'langgraph', traceId: 'trace-1' } }],
            ['missing-trace', {}],
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
