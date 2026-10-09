import type { SseEvent } from '@/api/sse'

import { decisionQuestionFor } from './permissionRequest'
import {
    displayStage,
    initialRunState,
    RECONNECT_ATTEMPTS_PER_DROP,
    type RunEffect,
    RunStreamCursor,
    reduceFrame,
    type StreamControl,
    shouldReconnect,
} from './runStream'
import type { RunStreamState } from './types'

const RUN = 'run-1'

function frame(data: unknown, id?: string): SseEvent {
    return { event: 'message', data: JSON.stringify(data), ...(id ? { id } : {}) }
}

function update(update: Record<string, unknown>, eventId?: string): Record<string, unknown> {
    return {
        type: 'notification',
        ...(eventId ? { event_id: eventId } : {}),
        notification: { jsonrpc: '2.0', method: 'session/update', params: { sessionId: 's', update } },
    }
}

function posthog(method: string, params: Record<string, unknown>): Record<string, unknown> {
    return { type: 'notification', notification: { jsonrpc: '2.0', method, params } }
}

const BASH_REQUEST = {
    type: 'permission_request',
    requestId: 'req-bash',
    options: [
        { optionId: 'allow', kind: 'allow_once', name: 'Yes' },
        { optionId: 'reject', kind: 'reject_once', name: 'No' },
    ],
    toolCall: {
        toolCallId: 'tc-bash',
        title: 'Run tests',
        kind: 'execute',
        _meta: { claudeCode: { toolName: 'Bash' } },
    },
}

const QUESTION_REQUEST = {
    type: 'permission_request',
    requestId: 'req-q',
    options: [
        { optionId: 'option_0', kind: 'allow_once', name: 'Patch the SDK' },
        { optionId: 'option_1', kind: 'allow_once', name: 'Patch the server' },
    ],
    toolCall: {
        toolCallId: 'tc-q',
        title: 'Which fix should I make?',
        kind: 'other',
        _meta: {
            codeToolKind: 'question',
            questions: [
                {
                    question: 'Which fix should I make?',
                    header: 'Fix',
                    multiSelect: false,
                    options: [{ label: 'Patch the SDK', description: 'Smaller change' }, { label: 'Patch the server' }],
                },
            ],
        },
    },
}

interface Fed {
    state: RunStreamState
    effects: RunEffect[]
    controls: StreamControl[]
    cursor: RunStreamCursor
}

function feed(events: SseEvent[], state: RunStreamState = initialRunState('task-1', RUN, 'in_progress')): Fed {
    const cursor = new RunStreamCursor(RUN)
    const effects: RunEffect[] = []
    const controls: StreamControl[] = []
    let current = state
    for (const event of events) {
        const result = cursor.accept(event)
        if (result.frame) {
            const reduced = reduceFrame(current, result.frame.data, result.frame.context)
            current = reduced.state
            effects.push(...reduced.effects)
        }
        if (result.control) {
            controls.push(result.control)
        }
    }
    return { state: current, effects, controls, cursor }
}

describe('runStream', () => {
    test('a run state frame sets the status, the PR and the error', () => {
        const { state } = feed([
            frame({
                type: 'task_run_state',
                run_id: RUN,
                status: 'in_progress',
                stage: null,
                output: {
                    pr_url: 'https://github.com/org/repo/pull/12',
                    pr_urls: ['https://github.com/org/repo/pull/12'],
                },
                error_message: null,
            }),
        ])
        expect(state).toMatchObject({ status: 'in_progress', prUrl: 'https://github.com/org/repo/pull/12' })

        const failed = feed([frame({ type: 'task_run_state', run_id: RUN, status: 'failed', error_message: 'Boom' })])
        expect(failed.state).toMatchObject({ status: 'failed', errorMessage: 'Boom' })
    })

    test.each<[string, SseEvent[], string | undefined]>([
        [
            'the latest tool title, as progress',
            [frame(update({ sessionUpdate: 'tool_call', toolCallId: 't1', title: 'Read /repo/src/ChartLegend.tsx' }))],
            'Reading ChartLegend.tsx',
        ],
        [
            'a step label wins over the tool title',
            [
                frame(update({ sessionUpdate: 'tool_call', toolCallId: 't1', title: 'Read a.ts' })),
                frame(
                    posthog('_posthog/progress', { step: 'clone', status: 'in_progress', label: 'Cloning the repo' })
                ),
            ],
            'Cloning the repo',
        ],
        [
            'a finished step falls back to the tool title',
            [
                frame(update({ sessionUpdate: 'tool_call', toolCallId: 't1', title: 'Read a.ts' })),
                frame(posthog('_posthog/progress', { step: 'clone', status: 'in_progress', label: 'Cloning' })),
                frame(posthog('_posthog/progress', { step: 'clone', status: 'completed', label: 'Cloning' })),
            ],
            'Reading a.ts',
        ],
        [
            'an update to an older tool call does not move the stage',
            [
                frame(update({ sessionUpdate: 'tool_call', toolCallId: 't1', title: 'Read a.ts' })),
                frame(update({ sessionUpdate: 'tool_call', toolCallId: 't2', title: 'Edit b.ts' })),
                frame(update({ sessionUpdate: 'tool_call_update', toolCallId: 't1', title: 'Read c.ts' })),
            ],
            'Editing b.ts',
        ],
    ])('stage: %s', (_name, events, expected) => {
        expect(displayStage(feed(events).state)).toBe(expected)
    })

    test('a live question surfaces as a decision with option ids and descriptions', () => {
        const { state, effects } = feed([frame(QUESTION_REQUEST, '1-0')])
        expect(effects).toEqual([])
        expect(state.pending?.kind).toBe('question')
        expect(state.pending && decisionQuestionFor(state.pending)).toEqual({
            id: 'req-q',
            question: 'Which fix should I make?',
            options: [
                { id: 'option_0', title: 'Patch the SDK', meta: 'Smaller change' },
                { id: 'option_1', title: 'Patch the server' },
            ],
        })
    })

    test('a live built-in tool request is allowed for the user, a replayed one is shown', () => {
        const live = feed([frame(BASH_REQUEST, '1-0')])
        expect(live.effects).toMatchObject([{ type: 'auto_allow', requestId: 'req-bash', optionId: 'allow' }])
        expect(live.state.pending).toBeUndefined()

        const replayed = feed([frame(posthog('_posthog/permission_request', BASH_REQUEST), 'log-4')])
        expect(replayed.effects).toEqual([])
        expect(replayed.state.pending?.record.requestId).toBe('req-bash')
    })

    test.each<[string, SseEvent[]]>([
        [
            'a logged resolution',
            [
                frame(posthog('_posthog/permission_request', QUESTION_REQUEST), 'log-1'),
                frame(posthog('_posthog/permission_resolved', { requestId: 'req-q' }), 'log-2'),
            ],
        ],
        [
            'the asked-about tool finishing',
            [
                frame(QUESTION_REQUEST, '1-0'),
                frame(update({ sessionUpdate: 'tool_call_update', toolCallId: 'tc-q', status: 'completed' }), '1-1'),
            ],
        ],
        ['the turn ending', [frame(QUESTION_REQUEST, '1-0'), frame(posthog('_posthog/turn_complete', {}), '1-1')]],
        [
            'the run ending',
            [
                frame(QUESTION_REQUEST, '1-0'),
                frame({ type: 'task_run_state', run_id: RUN, status: 'cancelled' }, '1-1'),
            ],
        ],
    ])('a pending question clears on %s', (_name, events) => {
        expect(feed(events).state.pending).toBeUndefined()
    })

    test('a resolved request does not come back when the log replays it', () => {
        const { state } = feed([
            frame(posthog('_posthog/permission_request', QUESTION_REQUEST), 'log-1'),
            frame(posthog('_posthog/permission_resolved', { requestId: 'req-q' }), 'log-2'),
            frame(QUESTION_REQUEST, '1-0'),
        ])
        expect(state.pending).toBeUndefined()
    })

    test('a replayed question from an earlier run in the log is ignored', () => {
        const { state } = feed([
            frame(posthog('_posthog/run_started', { runId: 'run-0', taskId: 'task-1' }), 'log-1'),
            frame(posthog('_posthog/permission_request', QUESTION_REQUEST), 'log-2'),
        ])
        expect(state.pending).toBeUndefined()
    })

    test('a frame delivered twice around a reconnect is applied once', () => {
        const chunk = update(
            { sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'Hello. ' } },
            'evt-1'
        )
        const { state } = feed([frame(chunk, '1-0'), frame(chunk, '1-0')])
        expect(state.lastMessage).toBe('Hello. ')
    })

    test('an ended turn waits for the user until the agent works again', () => {
        const ended = feed([
            frame(update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'Should I ' } }, 'e1')),
            frame(update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'proceed?' } }, 'e2')),
            frame(posthog('_posthog/turn_complete', { stopReason: 'end_turn' })),
        ])
        expect(ended.state).toMatchObject({ turnEnded: true, lastMessage: 'Should I proceed?' })

        const resumed = feed(
            [frame(update({ sessionUpdate: 'tool_call', toolCallId: 't9', title: 'Edit a.ts' }))],
            ended.state
        )
        expect(resumed.state.turnEnded).toBe(false)
    })

    test.each<[string, SseEvent, StreamControl, boolean]>([
        ['rotation keeps the cursor', { event: 'end', data: '{"type":"rotated"}' }, { type: 'rotated' }, true],
        ['resync drops the cursor', { event: 'end', data: '{"type":"resync"}' }, { type: 'resync' }, false],
        [
            'stream end drops the cursor',
            { event: 'stream-end', data: '{"status":"complete"}' },
            { type: 'ended' },
            false,
        ],
        [
            'an error keeps the cursor',
            { event: 'error', data: '{"error":"Backlog busy"}' },
            { type: 'error', message: 'Backlog busy' },
            true,
        ],
    ])('control: %s', (_name, event, control, keepsCursor) => {
        const result = feed([
            frame(update({ sessionUpdate: 'plan' }), '5-0'),
            { event: 'keepalive', data: '{}' },
            event,
        ])
        expect(result.controls).toEqual([control])
        expect(result.cursor.cursor).toBe(keepsCursor ? '5-0' : undefined)
    })

    test.each<[string, RunStreamState['status'], number, boolean]>([
        ['an active run reconnects', 'in_progress', 0, true],
        ['a finished run stops', 'completed', 0, false],
        ['a failed run stops', 'failed', 0, false],
        ['a spent retry budget stops', 'in_progress', RECONNECT_ATTEMPTS_PER_DROP, false],
    ])('shouldReconnect: %s', (_name, status, perDrop, expected) => {
        expect(shouldReconnect(initialRunState('task-1', RUN, status), { perDrop, total: perDrop })).toBe(expected)
    })
})
