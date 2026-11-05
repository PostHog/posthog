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
        [
            'a PostHog call by its inner tool, not the exec wrapper',
            [
                frame(
                    update({
                        sessionUpdate: 'tool_call',
                        toolCallId: 't1',
                        title: 'exec',
                        rawInput: { command: 'call reports-get {"id":"r1"}', context: 'Look up the newest report' },
                        _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
                    })
                ),
            ],
            'Call reports-get',
        ],
        [
            'a bare update to a PostHog call keeps the inner tool, not the exec wrapper',
            [
                frame(
                    update({
                        sessionUpdate: 'tool_call',
                        toolCallId: 't1',
                        title: 'exec',
                        rawInput: { command: 'call reports-get {"id":"r1"}' },
                        _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
                    })
                ),
                frame(
                    update({
                        sessionUpdate: 'tool_call_update',
                        toolCallId: 't1',
                        title: 'exec',
                        status: 'in_progress',
                    })
                ),
            ],
            'Call reports-get',
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

    test('live and replayed built-in permission requests both require an answer', () => {
        const live = feed([frame(BASH_REQUEST, '1-0')])
        expect(live.effects).toEqual([])
        expect(live.state.pending?.record.requestId).toBe('req-bash')

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
        expect(state.activity).toBe(1)
    })

    test('an ended turn clears activity until the agent works again', () => {
        const ended = feed([
            frame(update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'Should I ' } }, 'e1')),
            frame(update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'proceed?' } }, 'e2')),
            frame(posthog('_posthog/turn_complete', { stopReason: 'end_turn' })),
        ])
        expect(ended.state).toMatchObject({
            turnEnded: true,
            phase: 'idle',
            toolTitle: undefined,
            progressLabel: undefined,
        })

        const resumed = feed(
            [frame(update({ sessionUpdate: 'tool_call', toolCallId: 't9', title: 'Edit a.ts' }))],
            ended.state
        )
        expect(resumed.state.turnEnded).toBe(false)
    })

    test('old run messages, tools, progress and turn endings cannot change the current run', () => {
        const events = [
            frame(posthog('_posthog/run_started', { runId: 'run-0' }), 'log-1'),
            frame(update({ sessionUpdate: 'tool_call', toolCallId: 'old', title: 'Read old.ts' }), 'log-2'),
            frame(posthog('_posthog/progress', { status: 'in_progress', label: 'Old work' }), 'log-3'),
            frame(posthog('_posthog/turn_complete', {}), 'log-4'),
            frame({ type: 'task_run_state', status: 'failed' }, 'log-5'),
        ]
        const base = initialRunState('task-1', RUN, 'queued')
        expect(feed(events, base).state).toEqual(base)
    })

    test.each(['completed', 'failed', 'cancelled'] as const)(
        'a replayed current-run %s status clears pending input',
        (status) => {
            const { state } = feed([
                frame(posthog('_posthog/permission_request', QUESTION_REQUEST), 'log-1'),
                frame(
                    {
                        type: 'task_run_state',
                        run_id: RUN,
                        status,
                        error_message: status === 'failed' ? 'Run failed' : null,
                        output: { pr_url: 'https://github.com/example/app/pull/9' },
                    },
                    'log-2'
                ),
                frame({ type: 'task_run_state', run_id: RUN, status: 'in_progress' }, 'log-3'),
            ])
            expect(state).toMatchObject({
                status,
                phase: 'idle',
                pending: undefined,
                prUrls: ['https://github.com/example/app/pull/9'],
            })
            expect(state.errorMessage).toBe(status === 'failed' ? 'Run failed' : undefined)
        }
    )

    test('an unscoped terminal replay frame cannot settle the current run', () => {
        const { state } = feed([frame({ type: 'task_run_state', status: 'completed' }, 'log-1')])
        expect(state).toMatchObject({ status: 'in_progress', phase: 'unknown' })
    })

    test('terminal status cannot be revived by replay or live activity', () => {
        const { state } = feed([
            frame({ type: 'task_run_state', run_id: RUN, status: 'completed' }),
            frame(update({ sessionUpdate: 'tool_call', toolCallId: 'old', title: 'Read old.ts' }), 'log-1'),
            frame({ type: 'task_run_state', run_id: RUN, status: 'in_progress' }, 'log-2'),
            frame(update({ sessionUpdate: 'agent_message_chunk', text: 'Done' })),
        ])
        expect(state).toMatchObject({ status: 'completed', phase: 'idle', pending: undefined })
        expect(displayStage(state)).toBeUndefined()
    })

    test('an incomplete output snapshot retains all PR URLs already seen', () => {
        const { state } = feed([
            frame({
                type: 'task_run_state',
                output: {
                    pr_url: 'https://github.com/example/app/pull/1',
                    pr_urls: ['https://github.com/example/app/pull/2'],
                },
            }),
            frame({ type: 'task_run_state', output: { pr_url: 'https://github.com/example/app/pull/3' } }),
        ])
        expect(state.prUrls).toEqual([
            'https://github.com/example/app/pull/1',
            'https://github.com/example/app/pull/2',
            'https://github.com/example/app/pull/3',
        ])
    })

    test('a durable tool resolution clears a live request without reviving replay activity', () => {
        const { state } = feed([
            frame(QUESTION_REQUEST),
            frame(
                update({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 'tc-q',
                    status: 'completed',
                    title: 'Old title',
                }),
                'log-1'
            ),
        ])
        expect(state.pending).toBeUndefined()
        expect(state.toolTitle).toBeUndefined()
    })

    test('a new replayed request after reconnect surfaces while an ended request stays handled', () => {
        const { state } = feed([
            frame(QUESTION_REQUEST),
            frame(posthog('_posthog/turn_complete', {})),
            frame(posthog('_posthog/permission_request', QUESTION_REQUEST), 'log-1'),
            frame(posthog('_posthog/permission_request', { ...QUESTION_REQUEST, requestId: 'req-new' }), 'log-2'),
        ])
        expect(state.pending?.record.requestId).toBe('req-new')
    })

    test('typed PR progress discovers every PR without inferring GitHub state', () => {
        const { state } = feed([
            frame(
                posthog('_posthog/progress', {
                    step: 'pr',
                    status: 'completed',
                    label: 'Opened pull request',
                    detail: 'https://github.com/example/app/pull/9',
                })
            ),
            frame(
                posthog('_posthog/progress', {
                    step: 'pr',
                    status: 'completed',
                    label: 'Pull request merged',
                    detail: 'https://github.com/example/app/pull/10',
                })
            ),
        ])
        expect(state.prUrls).toEqual([
            'https://github.com/example/app/pull/9',
            'https://github.com/example/app/pull/10',
        ])
        expect(state.phase).toBe('unknown')
    })

    test('initial live run metadata does not suppress a pending request in replay', () => {
        const { state } = feed([
            frame({ type: 'task_run_state', run_id: RUN, status: 'in_progress' }),
            frame(posthog('_posthog/permission_request', QUESTION_REQUEST), 'log-1'),
        ])
        expect(state.pending?.record.requestId).toBe('req-q')
        expect(state.phase).toBe('unknown')
    })

    test('a monitoring progress label does not prove the agent is generating', () => {
        const { state } = feed([
            frame(posthog('_posthog/progress', { status: 'in_progress', label: 'Keeping CI green' })),
        ])
        expect(state.phase).toBe('unknown')
    })

    test('same-run replay cannot overwrite a live idle turn or status', () => {
        const { state } = feed([
            frame(posthog('_posthog/turn_complete', {})),
            frame(update({ sessionUpdate: 'tool_call', toolCallId: 'old', title: 'Read old.ts' }), 'log-1'),
            frame({ type: 'task_run_state', status: 'queued', stage: 'starting' }, 'log-2'),
        ])
        expect(state).toMatchObject({ status: 'in_progress', turnEnded: true, phase: 'idle' })
        expect(displayStage(state)).toBeUndefined()
    })

    test('deduped inherited run markers still scope frames after a cursor reset', () => {
        const cursor = new RunStreamCursor(RUN)
        const marker = { ...posthog('_posthog/run_started', { runId: 'run-old' }), event_id: 'old-marker' }
        cursor.accept(frame(marker, 'log-1'))
        cursor.resetCursor()
        expect(cursor.accept(frame(marker, 'log-1')).frame).toBeUndefined()
        const result = cursor.accept(
            frame(
                update({ sessionUpdate: 'tool_call', toolCallId: 'old-tool', title: 'Read old.ts' }, 'old-tool-event'),
                'log-2'
            )
        )
        expect(result.frame?.context).toEqual({ source: 'replay', sourceRunId: 'run-old' })
        const initial = initialRunState('task-1', RUN, 'in_progress')
        expect(result.frame && reduceFrame(initial, result.frame.data, result.frame.context).state).toBe(initial)
    })

    test('discarding a cursor fork cannot skip unpublished frames on reconnect', () => {
        const cursor = new RunStreamCursor(RUN)
        const marker = { ...posthog('_posthog/run_started', { runId: 'run-old' }), event_id: 'old-marker' }
        cursor.accept(frame(marker, 'log-1'))
        const fork = cursor.fork()
        expect(fork.accept(frame(marker, 'log-1')).frame).toBeUndefined()
        const unseen = frame(
            update({ sessionUpdate: 'agent_message_chunk', text: 'Historical reply' }, 'new-message'),
            'log-2'
        )
        expect(fork.accept(unseen).frame?.context.sourceRunId).toBe('run-old')
        expect(fork.cursor).toBe('log-2')
        expect(cursor.cursor).toBe('log-1')
        expect(cursor.accept(unseen).frame?.context.sourceRunId).toBe('run-old')
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
