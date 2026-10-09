import { type ConversationMessage, parseConversationEvent } from '@/api/conversations'
import type { SseEvent } from '@/api/sse'

import { chatPrompt } from './contextPrompt'
import {
    type ChatThreadAction,
    type ChatThreadState,
    chatThreadReducer,
    GENERIC_FAILURE,
    initialChatThread,
} from './conversation'

const AT = '2026-10-09T12:00:00.000Z'

function frame(event: string, data: unknown): SseEvent {
    return { event, data: JSON.stringify(data) }
}

function play(steps: (ChatThreadAction | SseEvent)[], state: ChatThreadState = initialChatThread): ChatThreadState {
    return steps.reduce((current, step) => {
        if ('type' in step) {
            return chatThreadReducer(current, step)
        }
        const event = parseConversationEvent(step)
        return event ? chatThreadReducer(current, { type: 'event', event, at: AT }) : current
    }, state)
}

function sent(text: string, traceId: string): ChatThreadAction {
    return { type: 'sent', text, traceId, at: AT }
}

function summary(
    state: ChatThreadState
): Pick<ChatThreadState['entries'][number], 'kind' | 'id' | 'text' | 'status'>[] {
    return state.entries.map(({ kind, id, text, status }) => ({ kind, id, text, status }))
}

describe('chat thread reducer', () => {
    test('streams snapshots in place, swaps in the final message, and keeps the typed text on the echo', () => {
        const prompt = chatPrompt('Why did signups drop?', {
            kind: 'reports',
            reports: [{ reportId: 'r1', title: 'Signups', canAct: false }],
        })
        const streaming = play([
            sent('Why did signups drop?', 'trace-1'),
            frame('message', { type: 'human', id: 'h1', trace_id: 'trace-1', content: prompt }),
            frame('message', { type: 'ai', id: 'temp-0', content: 'Let me' }),
            frame('message', { type: 'ai', id: 'temp-0', content: 'Let me check' }),
        ])
        expect(summary(streaming)).toEqual([
            { kind: 'user', id: 'h1', text: 'Why did signups drop?', status: 'completed' },
            { kind: 'assistant', id: 'temp-0', text: 'Let me check', status: 'loading' },
        ])

        const final = play([frame('message', { type: 'ai', id: 'a1', content: 'Signups fell 18%.' })], streaming)
        expect(summary(final)[1]).toEqual({
            kind: 'assistant',
            id: 'a1',
            text: 'Signups fell 18%.',
            status: 'completed',
        })
        expect(final.entries[1]?.key).toBe(streaming.entries[1]?.key)
    })

    test('a stopped reply keeps its text when the next turn streams temp-0 again', () => {
        const state = play([
            sent('First', 'trace-1'),
            frame('message', { type: 'ai', id: 'temp-0', content: 'Partial answer' }),
            { type: 'stopped' },
            sent('Second', 'trace-2'),
            frame('message', { type: 'ai', id: 'temp-0', content: 'New answer' }),
        ])
        expect(summary(state).map(({ text }) => text)).toEqual(['First', 'Partial answer', 'Second', 'New answer'])
    })

    test('tool updates attach progress to their message, even before it arrives, and clear when the turn ends', () => {
        const running = play([
            sent('Check errors', 'trace-1'),
            frame('update', { id: 'tool-msg', tool_call_id: 'call-1', content: 'Running query…' }),
            frame('message', {
                type: 'ai',
                id: 'tool-msg',
                content: '',
                tool_calls: [{ id: 'call-1', name: 'query' }],
            }),
        ])
        expect(running.entries).toHaveLength(2)
        expect(running.entries[1]).toMatchObject({ id: 'tool-msg', progress: 'Running query…' })

        const done = play([{ type: 'finished', at: AT }], running)
        expect(done.entries[1]).not.toHaveProperty('progress')
    })

    test.each([
        ['an ai/failure message', frame('message', { type: 'ai/failure', content: 'Oops! Something went wrong.' })],
        ['a generation_error status', frame('status', { type: 'generation_error' })],
    ])('%s ends the turn with an error entry', (_label, failure) => {
        const state = play([
            sent('Why?', 'trace-1'),
            frame('message', { type: 'ai', id: 'temp-0', content: 'Looking' }),
            failure,
        ])
        const entries = summary(state)
        expect(entries[1]?.status).toBe('completed')
        expect(entries[2]).toMatchObject({ kind: 'failure', status: 'error' })
        expect(entries[2]?.text).toBe(failure.event === 'status' ? GENERIC_FAILURE : 'Oops! Something went wrong.')
    })

    test('conversation events set the title once the server generates it', () => {
        const state = play([
            frame('conversation', { id: 'c1', status: 'in_progress', title: null }),
            frame('conversation', { id: 'c1', status: 'in_progress', title: 'Signup drop' }),
        ])
        expect(state.title).toBe('Signup drop')
    })

    test('a replay after reconnecting rebuilds the turn instead of duplicating its snapshots', () => {
        const beforeDrop = play([
            sent('Why?', 'trace-1'),
            frame('message', { type: 'human', id: 'h1', trace_id: 'trace-1', content: 'Why?' }),
            frame('message', { type: 'ai', id: 'temp-0', content: 'Signups' }),
            frame('message', { type: 'ai', id: 'a1', content: 'Signups fell.' }),
        ])
        const replayed = play(
            [
                { type: 'resuming' },
                frame('message', { type: 'human', id: 'h1', trace_id: 'trace-1', content: 'Why?' }),
                frame('message', { type: 'ai', id: 'temp-0', content: 'Signups' }),
                frame('message', { type: 'ai', id: 'a1', content: 'Signups fell.' }),
                { type: 'finished', at: AT },
            ],
            beforeDrop
        )
        expect(summary(replayed)).toEqual([
            { kind: 'user', id: 'h1', text: 'Why?', status: 'completed' },
            { kind: 'assistant', id: 'a1', text: 'Signups fell.', status: 'completed' },
        ])
    })

    test('loading a stored conversation shows what the person typed, not the context block', () => {
        const messages: ConversationMessage[] = [
            {
                type: 'human',
                id: 'h1',
                content: chatPrompt('What caused this?', {
                    kind: 'reports',
                    reports: [{ reportId: 'r1', title: 'Signups', canAct: true }],
                }),
            },
            { type: 'ai', id: 'a1', content: 'A deploy.' },
        ]
        const state = play([{ type: 'hydrated', title: 'Signups', messages, at: AT }])
        expect(summary(state).map(({ text }) => text)).toEqual(['What caused this?', 'A deploy.'])
    })
})
