import type { FrameContext } from '@/features/handoff/runStream'

import { chatPrompt } from '../contextPrompt'
import {
    historyFrames,
    initialSessionThread,
    type SessionThreadAction,
    type SessionThreadState,
    sessionThreadReducer,
} from './sessionReducer'
import type { SessionThreadItem } from './types'

const RUN = 'run-1'
const REPLAY: FrameContext = { source: 'replay', sourceRunId: RUN }
const LIVE: FrameContext = { source: 'live', sourceRunId: RUN }

function notification(method: string, params: Record<string, unknown>): Record<string, unknown> {
    return { type: 'notification', notification: { jsonrpc: '2.0', method, params } }
}

function update(update: Record<string, unknown>): Record<string, unknown> {
    return notification('session/update', { sessionId: 's', update })
}

function chunk(text: string, messageId?: string): Record<string, unknown> {
    return update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text }, messageId })
}

function message(text: string, messageId?: string): Record<string, unknown> {
    return update({ sessionUpdate: 'agent_message', content: { type: 'text', text }, messageId })
}

function userChunk(text: string): Record<string, unknown> {
    return update({ sessionUpdate: 'user_message_chunk', content: { type: 'text', text } })
}

const TURN_COMPLETE = notification('_posthog/turn_complete', {})

function link(runId: string, artifactId: string, name: string): Record<string, unknown> {
    return { type: 'resource_link', uri: `file:///workspace/.posthog/attachments/${runId}/${artifactId}/${name}`, name }
}

function play(
    steps: (SessionThreadAction | Record<string, unknown>)[],
    context: FrameContext = LIVE,
    state: SessionThreadState = initialSessionThread()
): SessionThreadState {
    return steps.reduce<SessionThreadState>((current, step) => {
        const action =
            'type' in step && typeof step.type === 'string' && step.type !== 'notification'
                ? (step as SessionThreadAction)
                : { type: 'frame' as const, frame: step, context }
        return sessionThreadReducer(current, action)
    }, state)
}

function row(state: SessionThreadState, item: SessionThreadItem): string {
    switch (item.kind) {
        case 'user':
            return `user: ${item.text}`
        case 'assistant':
            return `assistant${item.complete ? '' : '…'}: ${item.text}`
        case 'thought':
            return `thought${item.complete ? '' : '…'}: ${item.text}`
        case 'tool': {
            const invocation = state.invocations.get(item.toolCallId)
            return `tool: ${invocation?.toolName} ${invocation?.status}${invocation?.title ? ` "${invocation.title}"` : ''}`
        }
        case 'turn_end':
            return '---'
        case 'error':
            return `error(${item.variant}): ${item.message}`
        case 'notice':
            return `notice(${item.tone}${item.spinning ? ', spinning' : ''}): ${item.text}`
        case 'progress':
            return `progress: ${item.steps.map((step) => `${step.label} ${step.status}`).join(', ')}`
    }
}

function rows(state: SessionThreadState): string[] {
    return state.items.map((item) => row(state, item))
}

describe('session thread reducer', () => {
    test('folds a stored run log into the thread the web shows', () => {
        const state = play(
            [
                notification('_posthog/run_started', { runId: RUN }),
                userChunk(
                    '<posthog_untrusted_context>\nThe user is looking at a report.\n</posthog_untrusted_context>\nFix the flaky checkout test'
                ),
                update({ sessionUpdate: 'agent_thought_chunk', content: { text: 'Find the test first.' } }),
                update({
                    sessionUpdate: 'tool_call',
                    toolCallId: 'tc-read',
                    title: 'Read /repo/tests/checkout.spec.ts',
                    kind: 'read',
                    status: 'pending',
                    _meta: { claudeCode: { toolName: 'Read' } },
                }),
                update({ sessionUpdate: 'tool_call_update', toolCallId: 'tc-read', status: 'completed' }),
                update({
                    sessionUpdate: 'tool_call',
                    toolCallId: 'tc-inner',
                    title: 'Grep retry',
                    _meta: { claudeCode: { toolName: 'Grep', parentToolCallId: 'tc-task' } },
                }),
                update({
                    sessionUpdate: 'tool_call',
                    toolCallId: 'tc-exec',
                    toolName: 'exec',
                    serverName: 'posthog',
                    rawInput: { command: 'call --json insights-get {"id": 1}' },
                    _meta: { posthog: { mcp: { server: 'posthog', tool: 'exec' } } },
                }),
                update({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 'tc-exec',
                    status: 'failed',
                    error: { message: 'Insight not found' },
                }),
                message('The test waited on a timer. I replaced it with a wait for the request.'),
                TURN_COMPLETE,
                notification('_posthog/console', { message: 'debug line', level: 'info' }),
                notification('_posthog/usage_update', { used: 1200 }),
            ],
            REPLAY
        )
        expect(rows(state)).toEqual([
            'user: Fix the flaky checkout test',
            'thought: Find the test first.',
            'tool: Read completed "Reading checkout.spec.ts"',
            'tool: insights-get failed "Call insights-get"',
            'assistant: The test waited on a timer. I replaced it with a wait for the request.',
            '---',
        ])
        expect(state.invocations.get('tc-exec')?.errorMessage).toBe('Insight not found')
        // The subagent's inner call keeps its invocation for the parent card but gets no row.
        expect(state.invocations.has('tc-inner')).toBe(true)
    })

    test.each<[string, Record<string, unknown>, string, string | undefined]>([
        [
            'a PostHog call by its inner tool',
            {
                title: 'exec',
                rawInput: {
                    command: 'call reports-get {"id":"r1"}',
                    context: 'Look up the newest report created today',
                },
                _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
            },
            'tool: reports-get in_progress "Call reports-get"',
            'Look up the newest report created today',
        ],
        [
            'a PostHog discovery command by its verb',
            {
                title: 'exec',
                rawInput: { command: 'tools', context: 'See which tools can read reports' },
                _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
            },
            'tool: mcp__posthog__exec in_progress "List tools"',
            'See which tools can read reports',
        ],
        [
            'another tool by its name when the title only repeats it',
            { title: 'Exec', toolName: 'exec', serverName: 'sandbox' },
            'tool: exec in_progress',
            undefined,
        ],
        [
            'another MCP tool by its short title',
            { title: 'search', _meta: { claudeCode: { toolName: 'mcp__linear__search' } } },
            'tool: mcp__linear__search in_progress "search"',
            undefined,
        ],
    ])('names %s', (_name, call, expectedRow, expectedDetail) => {
        const state = play([
            update({ sessionUpdate: 'tool_call', toolCallId: 'tc-1', kind: 'other', status: 'in_progress', ...call }),
        ])
        expect(rows(state)).toEqual([expectedRow])
        expect(state.invocations.get('tc-1')?.detail).toBe(expectedDetail)
    })

    test('names a PostHog call once its command streams in on an update', () => {
        const meta = { claudeCode: { toolName: 'mcp__posthog__exec' } }
        const started = play([
            update({
                sessionUpdate: 'tool_call',
                toolCallId: 'tc-1',
                title: 'exec',
                status: 'in_progress',
                _meta: meta,
            }),
        ])
        expect(rows(started)).toEqual(['tool: mcp__posthog__exec in_progress "Run command"'])
        const described = play(
            [
                update({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 'tc-1',
                    rawInput: { command: 'call reports-get {"id":"r1"}', context: 'Look up the newest report' },
                }),
            ],
            LIVE,
            started
        )
        expect(rows(described)).toEqual(['tool: reports-get in_progress "Call reports-get"'])
        expect(described.invocations.get('tc-1')?.detail).toBe('Look up the newest report')
    })

    test('streams chunks into one bubble, starts a new one after a tool call, and closes on a mismatched finalize', () => {
        const state = play([
            chunk('Looking at ', 'm1'),
            chunk('the test.', 'm1'),
            update({ sessionUpdate: 'tool_call', toolCallId: 'tc-1', title: 'Run tests', kind: 'execute' }),
            chunk('It passes ', 'm1'),
            chunk('now.', 'm1'),
            message('It passes now.'),
        ])
        expect(rows(state)).toEqual([
            'assistant…: Looking at the test.',
            'tool:  pending "Run tests"',
            'assistant: It passes now.',
        ])
        expect(new Set(state.items.map((item) => item.id)).size).toBe(state.items.length)
    })

    test('a thought ends when the next item arrives, so a settled activity group stops spinning', () => {
        const thought = update({
            sessionUpdate: 'agent_thought_chunk',
            content: { type: 'text', text: 'Check the test.' },
        })
        const streaming = play([thought])
        expect(rows(streaming)).toEqual(['thought…: Check the test.'])
        const settled = play(
            [update({ sessionUpdate: 'tool_call', toolCallId: 'tc-1', title: 'Read test' })],
            LIVE,
            streaming
        )
        expect(rows(settled)).toEqual(['thought: Check the test.', 'tool:  pending "Reading test"'])
        expect(rows(streaming)).toEqual(['thought…: Check the test.'])
    })

    test('finalizing an open assistant buffer leaves the previously published state unchanged', () => {
        const streaming = play([chunk('Working ', 'm1')])
        const complete = play([message('Working now.', 'm1')], LIVE, streaming)
        expect(rows(complete)).toEqual(['assistant: Working now.'])
        expect(rows(streaming)).toEqual(['assistant…: Working '])
    })

    test('an optimistic send is drawn once across both echoes, and a queued send stays below the running turn', () => {
        const prompt = chatPrompt('Also update the docs', {
            kind: 'reports',
            reports: [{ reportId: 'r1', title: 'Flaky checkout test', canAct: true }],
        })
        const queued = play([
            chunk('Working on the fix.', 'm1'),
            { type: 'local_user', id: 'local-1', text: 'Also update the docs' },
            chunk(' Tests pass.', 'm1'),
            message('Working on the fix. Tests pass.', 'm1'),
            TURN_COMPLETE,
        ])
        expect(rows(queued)).toEqual([
            'assistant: Working on the fix. Tests pass.',
            '---',
            'user: Also update the docs',
        ])

        const echoed = play(
            [
                notification('_posthog/user_message', { content: prompt }),
                userChunk(prompt),
                chunk('Updating the docs.', 'm2'),
            ],
            LIVE,
            queued
        )
        expect(rows(echoed)).toEqual([
            'assistant: Working on the fix. Tests pass.',
            '---',
            'user: Also update the docs',
            'assistant…: Updating the docs.',
        ])
        expect(echoed.items[2]?.id).toBe('local-1')
    })

    test('an echoed file joins its message once, and keeps the preview of the bubble the app drew', () => {
        const replayed = play(
            [
                notification('_posthog/user_message', {
                    content: [{ type: 'text', text: 'Read the report' }, link('run-0', 'art-1', 'report.pdf')],
                }),
                userChunk('Read the report'),
                update({ sessionUpdate: 'user_message_chunk', content: link('run-0', 'art-1', 'report.pdf') }),
            ],
            REPLAY
        )
        expect(replayed.items).toEqual([
            {
                kind: 'user',
                id: 'user-0',
                text: 'Read the report',
                attachments: [{ name: 'report.pdf', isImage: false, runId: 'run-0', artifactId: 'art-1' }],
            },
        ])

        const echoed = play([
            {
                type: 'local_user',
                id: 'local-1',
                text: 'What is this?',
                attachments: [{ name: 'shot.png', isImage: true, localUri: 'file:///picked/shot.png' }],
            },
            notification('_posthog/user_message', {
                content: [{ type: 'text', text: 'What is this?' }, link(RUN, 'art-2', 'shot.png')],
            }),
        ])
        expect(echoed.items).toEqual([
            {
                kind: 'user',
                id: 'local-1',
                text: 'What is this?',
                attachments: [
                    {
                        name: 'shot.png',
                        isImage: true,
                        localUri: 'file:///picked/shot.png',
                        runId: RUN,
                        artifactId: 'art-2',
                    },
                ],
            },
        ])
    })

    test('same-name files fill in send order, skip a send still waiting, and keep their previews through a rebuild', () => {
        const echo = notification('_posthog/user_message', {
            content: [
                { type: 'text', text: 'Compare these' },
                link(RUN, 'art-1', 'image.png'),
                link(RUN, 'art-2', 'image.png'),
            ],
        })
        const sent = play([
            {
                type: 'local_user',
                id: 'local-1',
                text: 'Compare these',
                attachments: [
                    { name: 'image.png', isImage: true, localUri: 'file:///picked/first.png' },
                    { name: 'image.png', isImage: true, localUri: 'file:///picked/second.png' },
                ],
            },
            echo,
            { type: 'local_user', id: 'local-2', text: 'And this one?' },
            update({ sessionUpdate: 'user_message_chunk', content: link(RUN, 'art-3', 'notes.md') }),
        ])
        const previews = (state: SessionThreadState): (string | undefined)[][] =>
            state.items.map((item) =>
                item.kind === 'user'
                    ? (item.attachments ?? []).map((file) => `${file.artifactId}:${file.localUri ?? '-'}`)
                    : []
            )
        expect(previews(sent)).toEqual([
            ['art-1:file:///picked/first.png', 'art-2:file:///picked/second.png', 'art-3:-'],
            [],
        ])

        const rebuilt = play([{ type: 'resuming' }, echo, TURN_COMPLETE], REPLAY, sent)
        expect(previews(rebuilt)[0]).toEqual(['art-1:file:///picked/first.png', 'art-2:file:///picked/second.png'])
    })

    test('resuming rebuilds from the replayed chain, keeps the pending send, and skips the resume prompt', () => {
        const before = play([
            userChunk('Fix the flaky checkout test'),
            message('Done. The PR is open.'),
            TURN_COMPLETE,
            { type: 'local_user', id: 'local-1', text: 'Rename the helper too' },
            { type: 'resuming', resumeRun: true },
        ])
        const rebuilt = play(
            [
                notification('_posthog/run_started', { runId: 'run-0' }),
                userChunk('Fix the flaky checkout test'),
                message('Done. The PR is open.'),
                TURN_COMPLETE,
                notification('_posthog/run_started', { runId: RUN }),
                userChunk('You are resuming a previous conversation. Here is what happened so far.'),
                userChunk('Rename the helper too'),
            ],
            REPLAY,
            before
        )
        expect(rows(rebuilt)).toEqual([
            'user: Fix the flaky checkout test',
            'assistant: Done. The PR is open.',
            '---',
            'user: Rename the helper too',
        ])

        const liveFirst = play([chunk('On it.')], LIVE, before)
        expect(rows(liveFirst)).toEqual([
            'user: Fix the flaky checkout test',
            'assistant: Done. The PR is open.',
            '---',
            'assistant…: On it.',
            'user: Rename the helper too',
        ])
    })

    test('folds errors that describe one failure, and an undelivered follow-up into the error', () => {
        const state = play([
            { type: 'local_user', id: 'local-1', text: 'Try again' },
            notification('_posthog/progress', {
                group: 'g1',
                step: 'followup_delivery',
                status: 'failed',
                label: 'Delivering message',
            }),
            notification('_posthog/error', { message: 'Sandbox crashed: out of memory' }),
            update({ sessionUpdate: 'error', message: 'out of memory' }),
        ])
        expect(rows(state)).toEqual(['user: Try again', 'error(undelivered): out of memory'])
    })

    test('progress steps group by id and status spinners leave when their work completes', () => {
        const state = play([
            notification('_posthog/progress', { group: 'setup', step: 'clone', status: 'in_progress', label: 'Clone' }),
            notification('_posthog/progress', { group: 'setup', step: 'clone', status: 'completed', label: 'Clone' }),
            notification('_posthog/progress', { group: 'setup', step: 'install', status: 'pending', label: 'Install' }),
            notification('_posthog/status', { status: 'compacting' }),
            notification('_posthog/compact_boundary', { trigger: 'auto' }),
            notification('_posthog/status', { status: 'clearing' }),
            notification('_posthog/status', { status: 'clearing_failed', error: 'busy' }),
            notification('_posthog/status', { status: 'compacting' }),
            { type: 'settle' },
        ])
        expect(rows(state)).toEqual([
            'progress: Clone completed, Install pending',
            'notice(info): Compacted the conversation',
            "notice(failed): Couldn't clear the conversation: busy",
        ])
    })
})

describe('historyFrames', () => {
    test('tags a resume chain by its run markers and leaves lines before the first marker unowned', () => {
        const frames = historyFrames(
            [
                userChunk('before any marker'),
                notification('_posthog/run_started', { runId: 'run-0' }),
                userChunk('first run'),
                'not a record',
                notification('_posthog/sdk_session', { taskRunId: RUN }),
                userChunk('second run'),
            ],
            RUN,
            true
        )
        expect(frames.map((frame) => frame.context.sourceRunId)).toEqual(['', 'run-0', 'run-0', RUN, RUN])
        expect(historyFrames([userChunk('only run')], RUN, false)[0]?.context).toEqual(REPLAY)
    })
})
