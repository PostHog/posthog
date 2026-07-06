import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import { tasksRunsCommandCreate, tasksRunsStreamTokenRetrieve } from 'products/tasks/frontend/generated/api'

import type { PermissionRequestFrame, StoredLogEntry } from '../types/wireTypes'
import {
    extractRunArtifacts,
    mapHttpStatusToStreamError,
    MAX_CUMULATIVE_RECONNECT_ATTEMPTS,
    MAX_HISTORY_FETCH_ATTEMPTS,
    MAX_SSE_RECONNECT_ATTEMPTS,
    mergeResourceProducts,
    mergeRunArtifacts,
    parsePermissionRequestFrame,
    reconnectDelayMs,
    resolveStreamTarget,
    runStreamLogic,
    SSE_HEALTHY_CONNECTION_MS,
    SSE_RECONNECT_BASE_DELAY_MS,
    SSE_RECONNECT_MAX_DELAY_MS,
} from './runStreamLogic'
import { toolStreamEventsLogic } from './toolStreamEventsLogic'

jest.mock('products/tasks/frontend/generated/api', () => ({
    tasksRunsCommandCreate: jest.fn(),
    tasksRunsStreamTokenRetrieve: jest.fn(),
}))

function notification(method: string, params: Record<string, unknown>): StoredLogEntry {
    return { type: 'notification', notification: { method, params } }
}

function sessionUpdate(update: Record<string, unknown>): StoredLogEntry {
    return notification('session/update', { update })
}

function sessionPrompt(text: string, sessionId: string = 'session-1'): StoredLogEntry {
    return notification('session/prompt', {
        sessionId,
        prompt: [{ type: 'text', text }],
    })
}

function legacyNotification(method: string, params: Record<string, unknown>): Record<string, unknown> {
    return { notification: { method, params } }
}

type ReaderResult = { done: false; value: Uint8Array } | { done: true; value: undefined }

/**
 * Stand-in for one `api.tasks.runs.openStream` connection. Backs a fetch-style streaming `Response`
 * whose `body.getReader()` the logic pumps through `eventsource-parser`. Tests drive it by emitting
 * SSE-encoded frames; each `emit*` resolves the logic's pending `reader.read()` and drains the
 * microtask queue so the dispatched actions have settled before the test asserts.
 */
interface MockStreamOptions {
    signal: AbortSignal
    lastEventId?: string
    startLatest?: boolean
    proxyTarget?: { baseUrl: string; token: string }
}

class MockStreamConnection {
    readonly options: MockStreamOptions
    private pendingRead: ((r: ReaderResult) => void) | null = null
    private queued: ReaderResult[] = []
    private encoder = new TextEncoder()

    constructor(options: MockStreamOptions) {
        this.options = options
        // Teardown (dispose 'event-source') aborts the signal — unblock any pending read so the
        // logic's loop sees `done`/`aborted` and exits without scheduling a reconnect.
        options.signal.addEventListener('abort', () => this.deliver({ done: true, value: undefined }))
    }

    /** Mirrors `MockEventSource.closed`: the logic aborted the fetch (teardown / terminal / close). */
    get closed(): boolean {
        return this.options.signal.aborted
    }

    response(): Response {
        const reader = {
            read: (): Promise<ReaderResult> => {
                const next = this.queued.shift()
                if (next) {
                    return Promise.resolve(next)
                }
                if (this.options.signal.aborted) {
                    return Promise.resolve({ done: true, value: undefined })
                }
                return new Promise<ReaderResult>((resolve) => {
                    this.pendingRead = resolve
                })
            },
        }
        return { body: { getReader: () => reader } } as unknown as Response
    }

    private deliver(result: ReaderResult): void {
        if (this.pendingRead) {
            const resolve = this.pendingRead
            this.pendingRead = null
            resolve(result)
        } else {
            this.queued.push(result)
        }
    }

    private encodeFrame(fields: { data: string; event?: string; id?: string }): Uint8Array {
        const parts: string[] = []
        if (fields.event) {
            parts.push(`event: ${fields.event}`)
        }
        if (fields.id) {
            parts.push(`id: ${fields.id}`)
        }
        parts.push(`data: ${fields.data}`)
        return this.encoder.encode(parts.join('\n') + '\n\n')
    }

    /** The connection opens automatically once `openStream` resolves; this just drains the queue. */
    async emitOpen(): Promise<void> {
        await flushPromises()
    }

    /** Emit a default-channel data frame (optionally with the SSE `id:` = Redis stream id). */
    async emitMessage(data: object, id?: string): Promise<void> {
        this.deliver({ done: false, value: this.encodeFrame({ data: JSON.stringify(data), id }) })
        await flushPromises()
    }

    /** Emit a named `event: error` envelope frame. */
    async emitErrorFrame(envelope: Record<string, unknown>): Promise<void> {
        this.deliver({ done: false, value: this.encodeFrame({ data: JSON.stringify(envelope), event: 'error' }) })
        await flushPromises()
    }

    /** Emit the durable `event: stream-end` end-of-run sentinel, then close the body. */
    async emitStreamEnd(): Promise<void> {
        this.deliver({
            done: false,
            value: this.encodeFrame({ data: JSON.stringify({ status: 'complete' }), event: 'stream-end' }),
        })
        await flushPromises()
        this.deliver({ done: true, value: undefined })
        await flushPromises()
    }

    /** Server cleanly closes the stream body → the logic treats it as a drop. */
    async emitClose(): Promise<void> {
        this.deliver({ done: true, value: undefined })
        await flushPromises()
    }
}

class MockStream {
    static connections: MockStreamConnection[] = []

    static latest(): MockStreamConnection {
        return MockStream.connections[MockStream.connections.length - 1]
    }

    static reset(): void {
        MockStream.connections = []
    }

    /** Install the `api.tasks.runs.openStream` spy that records and backs each connection. */
    static install(): void {
        jest.spyOn(api.tasks.runs, 'openStream').mockImplementation((_taskId, _runId, options) => {
            const connection = new MockStreamConnection(options)
            MockStream.connections.push(connection)
            return Promise.resolve(connection.response())
        })
    }
}

describe('runStreamLogic', () => {
    let logic: ReturnType<typeof runStreamLogic.build>

    beforeEach(() => {
        // featureFlagLogic persists flags to localStorage; clear before init so a flag set by one
        // test (e.g. `enableProxy()`) can't leak into a later test's flag-off assertions.
        window.localStorage.clear()
        initKeaTests()
        // The logic mirrors the live resume cursor to sessionStorage — clear it so a cursor written
        // by one test can't seed another test's reconnect.
        window.sessionStorage.clear()
        MockStream.reset()
        MockStream.install()
        projectLogic.mount()
        projectLogic.actions.loadCurrentProjectSuccess({ id: 997 } as any)
        ;(tasksRunsCommandCreate as jest.Mock).mockReset().mockResolvedValue({ jsonrpc: '2.0' })
        logic = runStreamLogic({ streamKey: 'test-conversation', conversationId: 'test-conversation' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    describe('ingestAcpFrame replay', () => {
        it('folds a stream of StoredLogEntry frames into thread items', async () => {
            const frames: StoredLogEntry[] = [
                notification('_posthog/run_started', {}),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { text: 'Hel' } }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { text: 'lo' } }),
                sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'Hello' } }),
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't1',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: { command: 'call execute-sql {"query":"select 1"}' },
                    status: 'in_progress',
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't1',
                    status: 'completed',
                    rawOutput: { rows: 1 },
                    content: [{ type: 'text', text: 'done' }],
                }),
                notification('_posthog/turn_complete', {}),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            expect(logic.values.runStarted).toEqual(true)
            expect(logic.values.turnComplete).toEqual(true)

            const assistantItem = logic.values.threadItems.find((item) => item.type === 'assistant_message')
            expect(assistantItem?.text).toEqual('Hello')
            expect(assistantItem?.complete).toEqual(true)

            const toolItem = logic.values.threadItems.find((item) => item.type === 'tool_invocation')
            expect(toolItem?.toolCallId).toEqual('t1')

            const invocation = logic.values.toolInvocations.get('t1')
            expect(invocation?.rawServerName).toEqual('posthog')
            expect(invocation?.rawToolName).toEqual('exec')
            expect(invocation?.input).toEqual({ command: 'call execute-sql {"query":"select 1"}' })
            expect(invocation?.status).toEqual('completed')
            expect(invocation?.output).toEqual({ rows: 1 })
            expect(invocation?.contentBlocks).toEqual([{ type: 'text', text: 'done' }])

            expect(logic.values.threadItems.some((item) => item.type === 'turn_separator')).toEqual(true)
        })

        it('sets currentMode on a current_mode_update frame', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'current_mode_update', currentModeId: 'plan' })
                )
            }).toFinishAllListeners()

            expect(logic.values.currentMode).toEqual('plan')
        })

        it('sets currentProgress on a _posthog/progress frame and clears it on turn complete', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(notification('_posthog/progress', { label: 'Querying events' }))
            }).toFinishAllListeners()

            expect(logic.values.currentProgress).toEqual('Querying events')

            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(notification('_posthog/turn_complete', {}))
            }).toFinishAllListeners()

            expect(logic.values.currentProgress).toBeNull()
        })

        it('drives terminal status off handleTerminalStatus', async () => {
            await expectLogic(logic, () => {
                logic.actions.handleTerminalStatus({ status: 'completed' })
            }).toFinishAllListeners()

            expect(logic.values.currentRunStatus).toEqual('completed')
        })
    })

    describe('tool stream events', () => {
        const issueCall = sessionUpdate({
            sessionUpdate: 'tool_call',
            toolCallId: 'tse1',
            serverName: 'github',
            toolName: 'create_issue',
            status: 'in_progress',
        })
        const issueDone = sessionUpdate({ sessionUpdate: 'tool_call_update', toolCallId: 'tse1', status: 'completed' })

        it('publishes started/completed with resolved names for live frames; replay only reaches includeReplay listeners', async () => {
            const liveListener = jest.fn()
            const replayListener = jest.fn()
            // The bus is connect-mounted by the stream logic, so listeners can register directly.
            toolStreamEventsLogic.actions.registerToolListener('live', {
                tools: ['create_issue'],
                onEvent: liveListener,
            })
            toolStreamEventsLogic.actions.registerToolListener('replay', {
                tools: '*',
                onEvent: replayListener,
                includeReplay: true,
            })

            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(issueCall)
                logic.actions.ingestAcpFrame(issueDone)
            }).toFinishAllListeners()

            expect(liveListener.mock.calls.map(([event]) => [event.phase, event.toolName])).toEqual([
                ['started', 'create_issue'],
                ['completed', 'create_issue'],
            ])

            liveListener.mockClear()
            replayListener.mockClear()
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    sessionUpdate({
                        sessionUpdate: 'tool_call',
                        toolCallId: 'tse2',
                        serverName: 'github',
                        toolName: 'create_issue',
                        status: 'in_progress',
                    }),
                    'replay'
                )
            }).toFinishAllListeners()

            expect(liveListener).not.toHaveBeenCalled()
            expect(replayListener).toHaveBeenCalledTimes(1)
            expect(replayListener.mock.calls[0][0].source).toEqual('replay')
        })
    })

    describe('showThinkingIndicator', () => {
        const runStartedFrame = notification('_posthog/run_started', {})
        const messageChunk = sessionUpdate({
            sessionUpdate: 'agent_message_chunk',
            messageId: 'm1',
            content: { text: 'Hi' },
        })
        const messageFinal = sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'Hi' } })
        const toolStart = sessionUpdate({
            sessionUpdate: 'tool_call',
            toolCallId: 't1',
            serverName: 'posthog',
            toolName: 'exec',
            status: 'in_progress',
        })
        const toolDone = sessionUpdate({ sessionUpdate: 'tool_call_update', toolCallId: 't1', status: 'completed' })
        const progressActive = notification('_posthog/progress', {
            group: 'g',
            step: 's',
            label: 'Working',
            status: 'in_progress',
        })
        const turnComplete = notification('_posthog/turn_complete', {})

        it.each<[string, StoredLogEntry[], boolean]>([
            ['idle gap after run start shows the loader', [runStartedFrame], true],
            ['a streaming answer hides the loader', [runStartedFrame, messageChunk], false],
            ['a finalized answer mid-turn shows the loader', [runStartedFrame, messageChunk, messageFinal], true],
            ['a running tool hides the loader', [runStartedFrame, toolStart], false],
            ['a completed tool shows the loader', [runStartedFrame, toolStart, toolDone], true],
            ['a running progress step hides the loader', [runStartedFrame, progressActive], false],
            ['no run in flight hides the loader', [], false],
            ['a completed turn hides the loader', [runStartedFrame, messageFinal, turnComplete], false],
        ])('%s', async (_name, frames, expected) => {
            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            expect(logic.values.showThinkingIndicator).toEqual(expected)
        })
    })

    describe('assistant message buffering without messageId', () => {
        it('keeps two consecutive turns without a messageId in separate thread items', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'One' } }),
                sessionUpdate({ sessionUpdate: 'agent_message', content: { text: 'One' } }),
                notification('_posthog/turn_complete', {}),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'Tw' } }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'o' } }),
                sessionUpdate({ sessionUpdate: 'agent_message', content: { text: 'Two' } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const assistantItems = logic.values.threadItems.filter((item) => item.type === 'assistant_message')
            expect(assistantItems).toHaveLength(2)
            expect(assistantItems[0].text).toEqual('One')
            expect(assistantItems[0].complete).toEqual(true)
            expect(assistantItems[1].text).toEqual('Two')
            expect(assistantItems[1].complete).toEqual(true)
            expect(assistantItems[0].id).not.toEqual(assistantItems[1].id)
        })

        it('keeps text before and after a tool call as separate items in wire order', async () => {
            // Real wire pattern: streamed text, a tool call, then more streamed text — all in one
            // turn with no agent_message finalize between them and no messageId on any chunk.
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'Let me ' } }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'check.' } }),
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't1',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: { command: 'tools' },
                    status: 'in_progress',
                }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'All ' } }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'set.' } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            expect(logic.values.threadItems.map((item) => item.type)).toEqual([
                'assistant_message',
                'tool_invocation',
                'assistant_message',
            ])
            const assistantItems = logic.values.threadItems.filter((item) => item.type === 'assistant_message')
            expect(assistantItems[0].text).toEqual('Let me check.')
            expect(assistantItems[1].text).toEqual('All set.')
            expect(assistantItems[0].id).not.toEqual(assistantItems[1].id)
        })

        it('starts a new bubble for a chunk arriving after finalize instead of mutating the finalized one', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { text: 'Done' } }),
                sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'Done' } }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { text: 'More' } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const assistantItems = logic.values.threadItems.filter((item) => item.type === 'assistant_message')
            expect(assistantItems).toHaveLength(2)
            expect(assistantItems[0].text).toEqual('Done')
            expect(assistantItems[0].complete).toEqual(true)
            expect(assistantItems[1].text).toEqual('More')
            expect(assistantItems[1].complete).toEqual(false)
            expect(assistantItems[0].id).not.toEqual(assistantItems[1].id)
        })

        it('finalizes the streamed message when chunks carry a messageId but the finalize omits it', async () => {
            // The live wire often streams `agent_message_chunk`s with a messageId but closes the turn
            // with an `agent_message` that has none. The finalize must close the in-flight bubble, not
            // append a second one with the same text.
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'agent_message_chunk',
                    messageId: 'm1',
                    content: { text: "I'll query. " },
                }),
                sessionUpdate({
                    sessionUpdate: 'agent_message_chunk',
                    messageId: 'm1',
                    content: { text: 'Loading tools.' },
                }),
                sessionUpdate({ sessionUpdate: 'agent_message', content: { text: "I'll query. Loading tools." } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const assistantItems = logic.values.threadItems.filter((item) => item.type === 'assistant_message')
            expect(assistantItems).toHaveLength(1)
            expect(assistantItems[0].text).toEqual("I'll query. Loading tools.")
            expect(assistantItems[0].complete).toEqual(true)
        })

        it('finalizes the streamed message when chunks omit the messageId but the finalize carries it', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: "I'll query. " } }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'Loading tools.' } }),
                sessionUpdate({
                    sessionUpdate: 'agent_message',
                    messageId: 'm1',
                    content: { text: "I'll query. Loading tools." },
                }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const assistantItems = logic.values.threadItems.filter((item) => item.type === 'assistant_message')
            expect(assistantItems).toHaveLength(1)
            expect(assistantItems[0].text).toEqual("I'll query. Loading tools.")
            expect(assistantItems[0].complete).toEqual(true)
        })

        it('does not let an id-less finalize reach back across a turn separator', async () => {
            // A finalize with no matching buffer falls back to the in-flight message, but must not
            // close a still-open bubble from a previous turn.
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'agent_message_chunk',
                    messageId: 'm1',
                    content: { text: 'First turn' },
                }),
                notification('_posthog/turn_complete', {}),
                sessionUpdate({ sessionUpdate: 'agent_message', content: { text: 'Second turn' } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const assistantItems = logic.values.threadItems.filter((item) => item.type === 'assistant_message')
            expect(assistantItems.map((item) => item.text)).toEqual(['First turn', 'Second turn'])
            // The first turn's bubble stayed open (never finalized); the second turn's finalize made
            // its own complete bubble rather than closing the first.
            expect(assistantItems[0].complete).toEqual(false)
            expect(assistantItems[1].complete).toEqual(true)
        })
    })

    describe('agent thought buffering', () => {
        it('folds consecutive thought chunks into one assistant_thought item', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'agent_thought_chunk', content: { text: 'Let me ' } }),
                sessionUpdate({ sessionUpdate: 'agent_thought_chunk', content: { text: 'think.' } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const thoughtItems = logic.values.threadItems.filter((item) => item.type === 'assistant_thought')
            expect(thoughtItems).toHaveLength(1)
            expect(thoughtItems[0].text).toEqual('Let me think.')
        })

        it('keeps thoughts, messages, and tool calls as separate items in wire order', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'agent_thought_chunk', content: { text: 'Checking the data' } }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'Let me look.' } }),
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't1',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: { command: 'tools' },
                    status: 'in_progress',
                }),
                sessionUpdate({ sessionUpdate: 'agent_thought_chunk', content: { text: 'Now I know.' } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            expect(logic.values.threadItems.map((item) => item.type)).toEqual([
                'assistant_thought',
                'assistant_message',
                'tool_invocation',
                'assistant_thought',
            ])
            const thoughtItems = logic.values.threadItems.filter((item) => item.type === 'assistant_thought')
            expect(thoughtItems[0].text).toEqual('Checking the data')
            expect(thoughtItems[1].text).toEqual('Now I know.')
            expect(thoughtItems[0].id).not.toEqual(thoughtItems[1].id)
        })

        it('does not collide thought and message buffers that share the fallback id', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'agent_thought_chunk', content: { text: 'Thinking' } }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'Answer' } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const thought = logic.values.threadItems.find((item) => item.type === 'assistant_thought')
            const message = logic.values.threadItems.find((item) => item.type === 'assistant_message')
            expect(thought?.text).toEqual('Thinking')
            expect(message?.text).toEqual('Answer')
            expect(thought?.id).not.toEqual(message?.id)
        })
    })

    describe('streamed tool input', () => {
        it('folds rawInput arriving on a later update into a built-in tool call and keeps _meta raw', async () => {
            // Built-ins carry no top-level toolName — the SDK name arrives only on `_meta.claudeCode`.
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't1',
                    title: 'ToolSearch',
                    rawInput: {},
                    status: 'pending',
                    _meta: { claudeCode: { toolName: 'ToolSearch' } },
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't1',
                    rawInput: { query: 'find recordings', max_results: 10 },
                    status: 'completed',
                }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const invocation = logic.values.toolInvocations.get('t1')
            expect(invocation?.input).toEqual({ query: 'find recordings', max_results: 10 })
            expect(invocation?.rawToolName).toEqual('')
            expect(invocation?.meta).toEqual({ claudeCode: { toolName: 'ToolSearch' } })
        })

        it('folds an exec command that streams in after an empty tool_call without resolving it', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't2',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: {},
                    status: 'pending',
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't2',
                    rawInput: { command: 'call insight-create {"name":"Signups"}' },
                    status: 'in_progress',
                }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const invocation = logic.values.toolInvocations.get('t2')
            expect(invocation?.rawServerName).toEqual('posthog')
            expect(invocation?.rawToolName).toEqual('exec')
            expect(invocation?.input).toEqual({ command: 'call insight-create {"name":"Signups"}' })
        })

        it('keeps a subagent inner tool call out of the top-level thread but in the invocation map', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 'parent',
                    title: 'Task `review`',
                    rawInput: { subagent_type: 'code-reviewer', description: 'review', prompt: 'check it' },
                    status: 'in_progress',
                    _meta: { claudeCode: { toolName: 'Task' } },
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 'inner',
                    title: 'Bash `echo hi`',
                    rawInput: { command: 'echo hi' },
                    status: 'completed',
                    _meta: { claudeCode: { toolName: 'Bash', parentToolCallId: 'parent' } },
                }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const toolItems = logic.values.threadItems.filter((item) => item.type === 'tool_invocation')
            expect(toolItems).toHaveLength(1)
            expect(toolItems[0]).toEqual({ id: 'parent', type: 'tool_invocation', toolCallId: 'parent' })
            // The inner call is still resolvable (so a parent card could render it) — it just isn't a sibling.
            expect(logic.values.toolInvocations.get('inner')?.title).toEqual('Bash `echo hi`')
        })

        it.each(['Edit', 'TodoWrite', 'Grep', 'Task'])(
            'keeps a built-in %s tool_call raw despite an empty wire toolName',
            async (sdkName) => {
                const frames: StoredLogEntry[] = [
                    sessionUpdate({
                        sessionUpdate: 'tool_call',
                        toolCallId: 'tb',
                        title: `${sdkName} \`foo.ts\``,
                        rawInput: {},
                        status: 'in_progress',
                        _meta: { claudeCode: { toolName: sdkName } },
                    }),
                ]

                await expectLogic(logic, () => {
                    frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
                }).toFinishAllListeners()

                const invocation = logic.values.toolInvocations.get('tb')
                expect(invocation?.rawToolName).toEqual('')
                expect(invocation?.meta).toEqual({ claudeCode: { toolName: sdkName } })
            }
        )

        it('keeps the raw input when a later update carries none', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't3',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: { command: 'call execute-sql {"query":"select 1"}' },
                    status: 'in_progress',
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't3',
                    status: 'completed',
                    rawOutput: { rows: 1 },
                }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const invocation = logic.values.toolInvocations.get('t3')
            expect(invocation?.rawToolName).toEqual('exec')
            expect(invocation?.input).toEqual({ command: 'call execute-sql {"query":"select 1"}' })
        })
    })

    describe('tool_call_update collapse', () => {
        it('retains one merged update entry per tool call without losing early-update fields or duplicating content', async () => {
            // The agent re-sends the full accumulated output on every update — retaining each
            // snapshot in the log is the memory balloon this pins. A verbatim keep-latest would pass
            // the length check but drop the rawInput that arrived only on the first update.
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'tool_call', toolCallId: 't1', rawInput: {}, status: 'pending' }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't1',
                    rawInput: { command: 'ls -la' },
                    status: 'in_progress',
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't1',
                    content: [{ type: 'text', text: 'chunk1' }],
                    rawOutput: 'chunk1',
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't1',
                    content: [
                        { type: 'text', text: 'chunk1' },
                        { type: 'text', text: 'chunk2' },
                    ],
                    rawOutput: 'chunk1chunk2',
                }),
                // Terminal status-only update: must not erase the accumulated content/output.
                sessionUpdate({ sessionUpdate: 'tool_call_update', toolCallId: 't1', status: 'completed' }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            expect(logic.values.log.entries).toHaveLength(2)

            const invocation = logic.values.toolInvocations.get('t1')
            expect(invocation?.status).toEqual('completed')
            expect(invocation?.input).toEqual({ command: 'ls -la' })
            expect(invocation?.output).toEqual('chunk1chunk2')
            // Cumulative content replaces — appending would render chunk1 twice.
            expect(invocation?.contentBlocks).toEqual([
                { type: 'text', text: 'chunk1' },
                { type: 'text', text: 'chunk2' },
            ])
        })

        it('collapses interleaved updates of concurrent tool calls independently', async () => {
            // Dropping a superseded entry shifts later indexes — a stale toolUpdateIndex would merge
            // one tool call's update into another's entry.
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'tool_call', toolCallId: 'a', rawInput: {}, status: 'in_progress' }),
                sessionUpdate({ sessionUpdate: 'tool_call', toolCallId: 'b', rawInput: {}, status: 'in_progress' }),
                sessionUpdate({ sessionUpdate: 'tool_call_update', toolCallId: 'a', rawOutput: 'a1' }),
                sessionUpdate({ sessionUpdate: 'tool_call_update', toolCallId: 'b', rawOutput: 'b1' }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 'a',
                    rawOutput: 'a1a2',
                    status: 'completed',
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 'b',
                    rawOutput: 'b1b2',
                    status: 'failed',
                }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            expect(logic.values.log.entries).toHaveLength(4)
            expect(logic.values.toolInvocations.get('a')).toEqual(
                expect.objectContaining({ status: 'completed', output: 'a1a2' })
            )
            expect(logic.values.toolInvocations.get('b')).toEqual(
                expect.objectContaining({ status: 'failed', output: 'b1b2' })
            )
        })
    })

    describe('pushHumanMessage', () => {
        it('appends a human_message item ordered before subsequently ingested assistant frames', async () => {
            await expectLogic(logic, () => {
                logic.actions.pushHumanMessage('hello agent')
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'Hi!' } })
                )
            }).toFinishAllListeners()

            expect(logic.values.threadItems).toHaveLength(2)
            expect(logic.values.threadItems[0]).toEqual({
                id: 'human-0',
                type: 'human_message',
                text: 'hello agent',
                complete: true,
            })
            expect(logic.values.threadItems[1].type).toEqual('assistant_message')
        })
    })

    describe('_posthog/user_message rendering', () => {
        it('renders a seeded user turn into the thread on bootstrap replay', async () => {
            const frames: StoredLogEntry[] = [
                notification('_posthog/user_message', { content: 'Why did checkout drop?' }),
                sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'Let me check.' } }),
            ]
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue(frames as any)
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            await expectLogic(logic, () => {
                logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            // Both the human question and the assistant reply must render, in order.
            expect(logic.values.threadItems).toHaveLength(2)
            expect(logic.values.threadItems[0]).toEqual({
                id: 'human-0',
                type: 'human_message',
                text: 'Why did checkout drop?',
                complete: true,
            })
            expect(logic.values.threadItems[1].type).toEqual('assistant_message')
        })

        it('extracts text from ACP content blocks', async () => {
            const frames: StoredLogEntry[] = [
                notification('_posthog/user_message', {
                    content: [
                        { type: 'text', text: 'first ' },
                        { type: 'text', text: 'second' },
                    ],
                }),
            ]
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue(frames as any)
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            await expectLogic(logic, () => {
                logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            expect(logic.values.threadItems).toHaveLength(1)
            expect(logic.values.threadItems[0]).toMatchObject({ type: 'human_message', text: 'first second' })
        })

        it('strips the posthog_context wrapper so a replayed prompt matches the live one', async () => {
            const wrapped =
                '<posthog_context>\nThe user attached the following PostHog entities.\n- Insight #1\n</posthog_context>\n\nWhy did signups drop?'
            const frames: StoredLogEntry[] = [notification('_posthog/user_message', { content: wrapped })]
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue(frames as any)
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            await expectLogic(logic, () => {
                logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            expect(logic.values.threadItems.find((item) => item.type === 'human_message')?.text).toEqual(
                'Why did signups drop?'
            )
        })

        it('renders a live (non-replay) user_message frame with no optimistic echo (queue drain)', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(notification('_posthog/user_message', { content: 'drained message' }))
            }).toFinishAllListeners()

            expect(logic.values.threadItems).toHaveLength(1)
            expect(logic.values.threadItems[0]).toMatchObject({ type: 'human_message', text: 'drained message' })
        })

        it('does not double a live user_message frame already echoed optimistically on send', async () => {
            await expectLogic(logic, () => {
                logic.actions.pushHumanMessage('hello agent')
                logic.actions.ingestAcpFrame(notification('_posthog/user_message', { content: 'hello agent' }))
            }).toFinishAllListeners()

            expect(logic.values.threadItems.filter((item) => item.type === 'human_message')).toHaveLength(1)
        })

        // The backend persists the human turn as a session/update `user_message_chunk`, not a
        // `_posthog/user_message` ext-notification — this is the frame a thread actually loads from logs.
        it('renders a persisted user_message_chunk session update on bootstrap replay', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'user_message_chunk',
                    content: { type: 'text', text: 'what posthog tools do you have?' },
                }),
                sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'Several.' } }),
            ]
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue(frames as any)
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            await expectLogic(logic, () => {
                logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            expect(logic.values.threadItems).toHaveLength(2)
            expect(logic.values.threadItems[0]).toEqual({
                id: 'human-0',
                type: 'human_message',
                text: 'what posthog tools do you have?',
                complete: true,
            })
            expect(logic.values.threadItems[1].type).toEqual('assistant_message')
        })

        it('renders a legacy notification-only user message and suppresses resume prompt echoes', async () => {
            const resumePrompt =
                'You are resuming a previous conversation. Here is the conversation history. Continue from where you left off.'
            const frames: unknown[] = [
                notification('session/update', {
                    sessionId: 'ancestor-session',
                    update: {
                        sessionUpdate: 'user_message_chunk',
                        content: { type: 'text', text: "what's my pageview count" },
                    },
                }),
                notification('_posthog/console', { sessionId: 'run-1', level: 'debug', message: 'Starting resume' }),
                legacyNotification('_posthog/user_message', {
                    content: 'break down by a country',
                    _meta: { attached_context: [] },
                }),
                notification('_posthog/sdk_session', {
                    taskRunId: 'run-1',
                    sessionId: 'acp-session-1',
                    adapter: 'claude',
                }),
                notification('_posthog/run_started', {
                    runId: 'run-1',
                    taskId: 'task-1',
                    sessionId: 'acp-session-1',
                }),
                sessionPrompt(resumePrompt, 'acp-session-1'),
                notification('session/update', {
                    sessionId: 'acp-session-1',
                    update: {
                        sessionUpdate: 'user_message_chunk',
                        content: { type: 'text', text: resumePrompt },
                    },
                }),
                sessionPrompt('break down by a country', 'acp-session-1'),
                notification('session/update', {
                    sessionId: 'acp-session-1',
                    update: {
                        sessionUpdate: 'user_message_chunk',
                        content: { type: 'text', text: 'break down by a country' },
                    },
                }),
                sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'Here you go.' } }),
            ]
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue(frames as any)
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({
                status: 'completed',
                state: { resume_from_run_id: 'ancestor-run' },
            } as any)

            await expectLogic(logic, () => {
                logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            expect(
                logic.values.threadItems.filter((item) => item.type === 'human_message').map((item) => item.text)
            ).toEqual(["what's my pageview count", 'break down by a country'])
            expect(
                logic.values.threadItems.some((item) => item.type === 'human_message' && item.text === resumePrompt)
            ).toBe(false)
            expect(logic.values.threadItems.find((item) => item.type === 'assistant_message')?.text).toEqual(
                'Here you go.'
            )
        })

        it('hides a resume prompt with no canonical user message on bootstrap replay', async () => {
            const resumePrompt =
                'You are resuming a previous conversation. Here is the conversation history. Continue from where you left off.'
            const frames: StoredLogEntry[] = [
                notification('_posthog/console', { sessionId: 'run-1', level: 'debug', message: 'Starting resume' }),
                notification('_posthog/sdk_session', {
                    taskRunId: 'run-1',
                    sessionId: 'acp-session-1',
                    adapter: 'claude',
                }),
                notification('_posthog/run_started', {
                    runId: 'run-1',
                    taskId: 'task-1',
                    sessionId: 'acp-session-1',
                }),
                sessionPrompt(resumePrompt, 'acp-session-1'),
                notification('session/update', {
                    sessionId: 'acp-session-1',
                    update: {
                        sessionUpdate: 'user_message_chunk',
                        content: { type: 'text', text: resumePrompt },
                    },
                }),
                sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'Continuing.' } }),
            ]
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue(frames as any)
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({
                status: 'completed',
                state: { resume_from_run_id: 'ancestor-run' },
            } as any)

            await expectLogic(logic, () => {
                logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            expect(logic.values.threadItems.some((item) => item.type === 'human_message')).toBe(false)
            expect(logic.values.threadItems.find((item) => item.type === 'assistant_message')?.text).toEqual(
                'Continuing.'
            )
        })

        it('places replayed setup progress below the human turn it belongs to', async () => {
            const frames: StoredLogEntry[] = [
                notification('_posthog/progress', {
                    sessionId: 's',
                    step: 'agent',
                    status: 'completed',
                    label: 'Started agent',
                    group: 'setup:run-1',
                }),
                sessionUpdate({
                    sessionUpdate: 'user_message_chunk',
                    content: { type: 'text', text: 'build me a dashboard' },
                }),
            ]
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue(frames as any)
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            await expectLogic(logic, () => {
                logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            expect(logic.values.threadItems.map((item) => item.type)).toEqual(['human_message', 'progress'])
            expect(logic.values.threadItems[0]).toMatchObject({
                type: 'human_message',
                text: 'build me a dashboard',
            })
            expect(logic.values.threadItems[1]).toMatchObject({
                type: 'progress',
                progressSteps: [{ key: 'agent', status: 'completed', label: 'Started agent' }],
            })
        })

        it('renders a live (non-replay) user_message_chunk with no optimistic echo (queue drain)', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'user_message_chunk', content: { type: 'text', text: 'drained' } })
                )
            }).toFinishAllListeners()

            expect(logic.values.threadItems).toHaveLength(1)
            expect(logic.values.threadItems[0]).toMatchObject({ type: 'human_message', text: 'drained' })
        })

        it('dedupes a drained send echoed in both user_message wire forms into one bubble', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(notification('_posthog/user_message', { content: 'drained' }))
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'user_message_chunk', content: { type: 'text', text: 'drained' } })
                )
            }).toFinishAllListeners()

            expect(logic.values.threadItems.filter((item) => item.type === 'human_message')).toHaveLength(1)
        })
    })

    describe('per-conversation isolation', () => {
        it('keeps thread state independent between two mounted conversations', async () => {
            const otherLogic = runStreamLogic({ streamKey: 'other-conversation' })
            otherLogic.mount()

            await expectLogic(logic, () => {
                logic.actions.pushHumanMessage('hello agent')
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'Hi!' } })
                )
            }).toFinishAllListeners()

            expect(logic.values.threadItems).toHaveLength(2)
            expect(otherLogic.values.threadItems).toHaveLength(0)

            otherLogic.unmount()
        })
    })

    describe('tool call errors', () => {
        it('populates error from a failed tool_call_update carrying an error message', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't1',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: { command: 'tools' },
                    status: 'in_progress',
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't1',
                    status: 'failed',
                    error: { message: 'command exploded' },
                }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const invocation = logic.values.toolInvocations.get('t1')
            expect(invocation?.status).toEqual('failed')
            expect(invocation?.error?.message).toEqual('command exploded')
        })

        it('falls back to the notification-level error when a failed update has none', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't2',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: { command: 'tools' },
                    status: 'in_progress',
                }),
                {
                    type: 'notification',
                    notification: {
                        method: 'session/update',
                        params: { update: { sessionUpdate: 'tool_call_update', toolCallId: 't2', status: 'failed' } },
                        error: { message: 'sandbox crashed' },
                    },
                },
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            expect(logic.values.toolInvocations.get('t2')?.error?.message).toEqual('sandbox crashed')
        })

        it('surfaces the _meta.claudeCode denial reason on a failed update with no explicit error', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't3',
                    title: 'Edit `foo.ts`',
                    rawInput: {},
                    status: 'in_progress',
                    _meta: { claudeCode: { toolName: 'Edit' } },
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't3',
                    status: 'failed',
                    content: [
                        { type: 'content', content: { type: 'text', text: 'Permission denied: writes blocked' } },
                    ],
                    _meta: {
                        claudeCode: {
                            toolName: 'Edit',
                            toolResponse: {
                                decisionReason: 'Edits are not allowed in read-only mode',
                                decisionReasonType: 'policy',
                                message: 'denied',
                            },
                        },
                    },
                }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const invocation = logic.values.toolInvocations.get('t3')
            expect(invocation?.status).toEqual('failed')
            expect(invocation?.error?.message).toEqual('Edits are not allowed in read-only mode')
        })

        it('upserts a renderable invocation from a terminal update whose tool_call frame was lost', async () => {
            // A reconnect with ?start=latest can drop the creating frame; the terminal update must
            // still render a card, and must not fire completion telemetry with an undefined name.
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)

            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'tool_call_update', toolCallId: 'orphan', status: 'completed' })
                )
            }).toFinishAllListeners()

            expect(logic.values.toolInvocations.get('orphan')?.status).toEqual('completed')
            expect(logic.values.threadItems.some((item) => item.toolCallId === 'orphan')).toEqual(true)
            expect(captureSpy.mock.calls.filter((c) => c[0] === 'tool_call_completed')).toHaveLength(0)
        })

        it('does not throw and keeps no error on the inline-denial path (failed, no _meta)', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't4',
                    title: 'Bash `rm -rf`',
                    rawInput: {},
                    status: 'in_progress',
                    _meta: { claudeCode: { toolName: 'Bash' } },
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't4',
                    status: 'failed',
                    content: [
                        { type: 'content', content: { type: 'text', text: 'User refused permission to run Bash' } },
                    ],
                }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const invocation = logic.values.toolInvocations.get('t4')
            expect(invocation?.status).toEqual('failed')
            // No _meta and no explicit error → the renderer falls back to the content text; no error.message synthesized.
            expect(invocation?.error?.message).toBeUndefined()
            expect(invocation?.contentBlocks).toHaveLength(1)
        })
    })

    describe('chunk folding', () => {
        it('folds distinct chunks of the same message into one growing buffer', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { text: 'A' } })
                )
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { text: 'B' } })
                )
            }).toFinishAllListeners()

            const assistantItem = logic.values.threadItems.find((item) => item.type === 'assistant_message')
            expect(assistantItem?.text).toEqual('AB')
        })

        it('keeps two chunks with identical text instead of collapsing them', async () => {
            // A repeated identical token is real content, not a duplicate — the append-only log keeps
            // both and they fold into one growing buffer (no per-frame content dedup at ingest).
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { text: 'tok ' } })
                )
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { text: 'tok ' } })
                )
            }).toFinishAllListeners()

            const assistant = logic.values.threadItems.find((item) => item.type === 'assistant_message')
            expect(assistant?.text).toEqual('tok tok ')
            expect(logic.values.log.entries).toHaveLength(2)
        })
    })

    describe('assistant message id uniqueness', () => {
        it('assigns unique ids to no-messageId finalized messages across turns (no React key collision)', async () => {
            // S3 replay drops `agent_message_chunk`, so each prior turn arrives as a bare finalized
            // `agent_message` with no `messageId` — they all fall back to the same id base. Each must
            // still get a unique thread-item id, or they collide as React keys and render duplicated.
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'agent_message', content: { text: 'first answer' } }),
                notification('_posthog/turn_complete', {}),
                sessionUpdate({ sessionUpdate: 'agent_message', content: { text: 'second answer' } }),
                notification('_posthog/turn_complete', {}),
                sessionUpdate({ sessionUpdate: 'agent_message', content: { text: 'third answer' } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame, 'replay'))
            }).toFinishAllListeners()

            const assistants = logic.values.threadItems.filter((item) => item.type === 'assistant_message')
            expect(assistants.map((item) => item.text)).toEqual(['first answer', 'second answer', 'third answer'])
            const ids = assistants.map((item) => item.id)
            expect(new Set(ids).size).toEqual(ids.length)
        })

        it('assigns unique ids to no-messageId chunked messages across turns', async () => {
            // The live path: each turn streams chunks with no `messageId` (so the same `current` base),
            // closed by a finalize. Distinct turns must still produce distinct bubble ids.
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'one' } }),
                sessionUpdate({ sessionUpdate: 'agent_message', content: { text: 'one' } }),
                notification('_posthog/turn_complete', {}),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'two' } }),
                sessionUpdate({ sessionUpdate: 'agent_message', content: { text: 'two' } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame, 'live'))
            }).toFinishAllListeners()

            const assistants = logic.values.threadItems.filter((item) => item.type === 'assistant_message')
            expect(assistants.map((item) => item.text)).toEqual(['one', 'two'])
            const ids = assistants.map((item) => item.id)
            expect(new Set(ids).size).toEqual(ids.length)
        })
    })

    describe('resume-context filter (§6)', () => {
        it('drops the synthetic resume-context prompt on a resume run but keeps the genuine turn (§6)', async () => {
            const resumePrompt =
                'You are resuming a previous conversation. Here is the conversation history. Continue from where you left off.'
            const frames: StoredLogEntry[] = [
                notification('_posthog/run_started', { runId: 'run-1', sessionId: 'acp-1' }),
                sessionUpdate({ sessionUpdate: 'user_message_chunk', content: { type: 'text', text: resumePrompt } }),
                sessionUpdate({
                    sessionUpdate: 'user_message_chunk',
                    content: { type: 'text', text: 'break it down by country' },
                }),
            ]
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue(frames as any)
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({
                status: 'completed',
                state: { resume_from_run_id: 'run-0' },
            } as any)

            await expectLogic(logic, () => {
                logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            expect(
                logic.values.threadItems.filter((item) => item.type === 'human_message').map((item) => item.text)
            ).toEqual(['break it down by country'])
        })

        it('keeps a "You are resuming…" message when the run is NOT a resume run (gate is resume-only)', async () => {
            const looksLikeResume = 'You are resuming a previous conversation. (but the user actually typed this)'
            const frames: StoredLogEntry[] = [
                notification('_posthog/run_started', { runId: 'run-1' }),
                sessionUpdate({
                    sessionUpdate: 'user_message_chunk',
                    content: { type: 'text', text: looksLikeResume },
                }),
            ]
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue(frames as any)
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            await expectLogic(logic, () => {
                logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            expect(
                logic.values.threadItems.filter((item) => item.type === 'human_message').map((item) => item.text)
            ).toEqual([looksLikeResume])
        })
    })

    describe('error mapping', () => {
        it('maps HTTP statuses to error envelopes', () => {
            expect(mapHttpStatusToStreamError(401)).toEqual({
                errorTitle: 'Cloud authentication expired',
                retryable: true,
                status: 401,
            })
            expect(mapHttpStatusToStreamError(403)).toEqual({
                errorTitle: 'Cloud access denied',
                retryable: true,
                status: 403,
            })
            expect(mapHttpStatusToStreamError(404)).toEqual({
                errorTitle: 'Conversation backing run not found',
                retryable: false,
                status: 404,
            })
            expect(mapHttpStatusToStreamError(406)).toEqual({
                errorTitle: 'Cloud stream unavailable',
                retryable: true,
                status: 406,
            })
            expect(mapHttpStatusToStreamError(500)).toEqual({
                errorTitle: 'Cloud stream failed',
                retryable: true,
                status: 500,
            })
            expect(mapHttpStatusToStreamError(undefined)).toEqual({
                errorTitle: 'Cloud stream failed',
                retryable: true,
            })
        })

        it('caps the backoff schedule at 2s/4s/8s/16s/30s', () => {
            expect([1, 2, 3, 4, 5].map(reconnectDelayMs)).toEqual([2000, 4000, 8000, 16000, 30000])
            expect(reconnectDelayMs(6)).toEqual(SSE_RECONNECT_MAX_DELAY_MS)
        })

        it('surfaces a named event:error frame verbatim', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })

            await MockStream.latest().emitErrorFrame({
                errorTitle: 'Sandbox crashed',
                errorMessage: 'boom',
                retryable: false,
            })

            expect(logic.values.sseStatus).toEqual('error')
        })
    })

    describe('bootstrap log loading state', () => {
        it('keeps log bootstrap loading after SSE opens until history is ready', async () => {
            let resolveRun: (run: { status: string }) => void = () => {}
            jest.spyOn(api.tasks.runs, 'get').mockReturnValue(
                new Promise((resolve) => {
                    resolveRun = resolve
                }) as Promise<any>
            )
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([])

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })

            expect(logic.values.bootstrapLoading).toBe(true)
            expect(logic.values.logBootstrapLoading).toBe(true)

            logic.actions.sseOpened()

            expect(logic.values.bootstrapLoading).toBe(false)
            expect(logic.values.logBootstrapLoading).toBe(true)

            logic.actions.bootstrapLogReady()

            expect(logic.values.logBootstrapLoading).toBe(false)

            resolveRun({ status: 'completed' })
            await expectLogic(logic).toFinishAllListeners()
        })

        it('stores bootstrap errors for inline task-run error UI', async () => {
            const error = mapHttpStatusToStreamError(404)

            await expectLogic(logic, () => {
                logic.actions.handleStreamError(error)
            }).toFinishAllListeners()

            expect(logic.values.logBootstrapLoading).toBe(false)
            expect(logic.values.bootstrapError).toEqual(error)
        })
    })

    describe('isThinking', () => {
        it('is on only while a started turn is incomplete, surviving non-terminal status updates', () => {
            expect(logic.values.isThinking).toEqual(false)

            logic.actions.ingestAcpFrame(notification('_posthog/run_started', {}))
            expect(logic.values.isThinking).toEqual(true)

            logic.actions.handleTerminalStatus({ status: 'queued' })
            expect(logic.values.isThinking).toEqual(true)

            logic.actions.ingestAcpFrame(notification('_posthog/turn_complete', {}))
            expect(logic.values.isThinking).toEqual(false)
        })

        it.each([
            ['a terminal run status', (): void => logic.actions.handleTerminalStatus({ status: 'failed' })],
            ['a stream error', (): void => logic.actions.handleStreamError({ errorTitle: 'x', retryable: true })],
        ])('turns off on %s even when turn_complete never arrives', (_case, act) => {
            logic.actions.ingestAcpFrame(notification('_posthog/run_started', {}))
            expect(logic.values.isThinking).toEqual(true)

            act()
            expect(logic.values.isThinking).toEqual(false)
        })

        it('re-raises on a follow-up turn opened by a human message, with no new run_started', () => {
            logic.actions.ingestAcpFrame(notification('_posthog/run_started', {}))
            logic.actions.ingestAcpFrame(notification('_posthog/turn_complete', {}))
            expect(logic.values.isThinking).toEqual(false)

            // A follow-up on the same run starts a new turn — no second run_started frame arrives.
            logic.actions.pushHumanMessage('and the mobile funnel?')
            expect(logic.values.isThinking).toEqual(true)
        })

        it('is on during the cold-boot queued window before the first run_started', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            // currentRunStatus is 'queued' and runStarted is still false — the indicator must show.
            expect(logic.values.currentRunStatus).toEqual('queued')
            expect(logic.values.isThinking).toEqual(true)
        })
    })

    describe('streamPhase provisioning during open', () => {
        it('is provisioning while the open POST is in flight, before any SSE state exists', () => {
            expect(logic.values.streamPhase).toEqual('idle')

            // The conversations/open POST has started — no SSE/run status yet.
            logic.actions.setRunOpening(true)
            expect(logic.values.sseStatus).toEqual('idle')
            expect(logic.values.currentRunStatus).toEqual(null)
            expect(logic.values.streamPhase).toEqual('provisioning')
        })

        it.each([
            ['a stream error', (): void => logic.actions.handleStreamError({ errorTitle: 'x', retryable: true })],
            ['an injected error item', (): void => logic.actions.pushErrorItem('boom')],
        ])('clears the optimistic flag on %s', (_case, act) => {
            logic.actions.setRunOpening(true)
            expect(logic.values.runOpening).toEqual(true)

            act()
            expect(logic.values.runOpening).toEqual(false)
        })

        it('clears the optimistic flag once the SSE opens (openSseForRun)', async () => {
            logic.actions.setRunOpening(true)
            expect(logic.values.runOpening).toEqual(true)

            // openSseForRun runs an async listener that opens a stream — await it so no work leaks.
            await expectLogic(logic, () => {
                logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()
            expect(logic.values.runOpening).toEqual(false)
        })

        it('lets run_started win over the optimistic flag (thinking, not provisioning)', () => {
            logic.actions.setRunOpening(true)
            expect(logic.values.streamPhase).toEqual('provisioning')

            logic.actions.ingestAcpFrame(notification('_posthog/run_started', {}))
            expect(logic.values.streamPhase).toEqual('thinking')
        })
    })

    describe('terminal-status handling', () => {
        it('closes the SSE and stops reconnects on a terminal task_run_state', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockStream.latest()
            await source.emitOpen()

            await expectLogic(logic, () => {
                logic.actions.handleTerminalStatus({ status: 'completed' })
            }).toFinishAllListeners()

            expect(logic.values.currentRunStatus).toEqual('completed')
            expect(source.closed).toEqual(true)
        })

        it('keeps the stream open on a non-terminal task_run_state', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockStream.latest()
            await source.emitOpen()

            await expectLogic(logic, () => {
                logic.actions.handleTerminalStatus({ status: 'in_progress' })
            }).toFinishAllListeners()

            expect(logic.values.currentRunStatus).toEqual('in_progress')
            expect(source.closed).toEqual(false)
        })
    })

    describe('runArtifacts (git context)', () => {
        const PR_URL = 'https://github.com/PostHog/posthog/pull/123'

        it('mergeRunArtifacts is latest-wins and ignores undefined/empty values', () => {
            const base = mergeRunArtifacts({}, { branch: 'feat/a', baseBranch: 'master' })
            expect(base).toEqual({ branch: 'feat/a', baseBranch: 'master' })

            // A later non-empty value overwrites; undefined/empty fields leave the prior value intact.
            const next = mergeRunArtifacts(base, { branch: 'feat/b', baseBranch: undefined, prUrl: '' })
            expect(next).toEqual({ branch: 'feat/b', baseBranch: 'master' })
        })

        it('extractRunArtifacts reads branch/base/pr from a bootstrap run and a live frame', () => {
            expect(
                extractRunArtifacts({
                    branch: 'feat/x',
                    state: { pr_base_branch: 'master', repository: 'PostHog/posthog' },
                    output: { pr_url: PR_URL },
                })
            ).toEqual({ branch: 'feat/x', baseBranch: 'master', repo: 'PostHog/posthog', prUrl: PR_URL })

            // A live task_run_state frame has no `state`, so only branch + pr_url are extracted.
            expect(extractRunArtifacts({ branch: 'feat/x', output: { pr_url: PR_URL } })).toEqual({
                branch: 'feat/x',
                prUrl: PR_URL,
            })
        })

        it('captures branch / base / pr from the bootstrap run fetch', async () => {
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([] as any)
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({
                status: 'completed',
                branch: 'feat/posthog-ai-sandboxes',
                state: { pr_base_branch: 'master' },
                output: { pr_url: PR_URL },
            } as any)

            await expectLogic(logic, () => {
                logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            expect(logic.values.runArtifacts).toEqual({
                branch: 'feat/posthog-ai-sandboxes',
                baseBranch: 'master',
                prUrl: PR_URL,
            })
            expect(logic.values.hasGitArtifacts).toBe(true)
        })

        it('captures the pr url from a live task_run_state frame', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            await MockStream.latest().emitOpen()

            await expectLogic(logic, async () => {
                await MockStream.latest().emitMessage({
                    type: 'task_run_state',
                    status: 'in_progress',
                    branch: 'feat/x',
                    output: { pr_url: PR_URL },
                })
            }).toFinishAllListeners()

            expect(logic.values.runArtifacts).toMatchObject({ branch: 'feat/x', prUrl: PR_URL })
            expect(logic.values.hasGitArtifacts).toBe(true)
        })

        it('stays empty and self-hideable for a run with no git context', async () => {
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([] as any)
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            await expectLogic(logic, () => {
                logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            expect(logic.values.runArtifacts).toEqual({})
            expect(logic.values.hasGitArtifacts).toBe(false)
        })

        it('clears runArtifacts on reset', async () => {
            await expectLogic(logic, () => {
                logic.actions.mergeRunArtifacts({ branch: 'feat/x', prUrl: PR_URL })
            }).toFinishAllListeners()
            expect(logic.values.hasGitArtifacts).toBe(true)

            await expectLogic(logic, () => {
                logic.actions.reset()
            }).toFinishAllListeners()
            expect(logic.values.runArtifacts).toEqual({})
            expect(logic.values.hasGitArtifacts).toBe(false)
        })
    })

    describe('reconnect / backoff', () => {
        it('refetches and surfaces terminal status on a drop, without reopening', async () => {
            const getSpy = jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            await MockStream.latest().emitOpen()

            const beforeDrop = MockStream.connections.length
            logic.actions.sseDropped()
            await flushPromises()

            expect(getSpy).toHaveBeenCalledWith('task-1', 'run-1')
            expect(logic.values.currentRunStatus).toEqual('completed')
            // No new connection was opened (terminal → no reconnect).
            expect(MockStream.connections.length).toEqual(beforeDrop)
        })

        it('backs off and reopens on a drop while the run is non-terminal', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            await MockStream.latest().emitOpen()
            const beforeDrop = MockStream.connections.length

            jest.useFakeTimers()
            logic.actions.sseDropped()
            await flushPromises()

            expect(logic.values.sseStatus).toEqual('reconnecting')
            expect(logic.values.reconnectAttempt).toEqual(1)

            jest.advanceTimersByTime(2000)
            expect(MockStream.connections.length).toEqual(beforeDrop + 1)
            // No frame carried an id before the drop, so there's nothing to resume from — the reopen
            // requests start=latest (only new frames) rather than re-broadcasting the whole stream.
            expect(MockStream.latest().options.startLatest).toEqual(true)
            expect(MockStream.latest().options.lastEventId).toBeUndefined()
            jest.useRealTimers()
        })

        it('resumes from the last-seen event id via the Last-Event-ID header on reconnect', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            // A live frame stamps its Redis stream id as the resume cursor.
            await MockStream.latest().emitMessage(notification('_posthog/run_started', {}), '1700-0')

            jest.useFakeTimers()
            logic.actions.sseDropped()
            await flushPromises()
            jest.advanceTimersByTime(2000)

            // The reconnect resumes exactly after the last-seen frame — header set, no start=latest.
            expect(MockStream.latest().options.lastEventId).toEqual('1700-0')
            jest.useRealTimers()
        })

        it('preserves a known in-flight status when the reconnect reopens the stream', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            logic.actions.handleTerminalStatus({ status: 'in_progress' })
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1', startLatest: false })

            expect(logic.values.currentRunStatus).toEqual('in_progress')
        })

        it('abandons the drop loop when the stream is closed mid-refetch', async () => {
            let resolveGet: (value: unknown) => void = () => {}
            jest.spyOn(api.tasks.runs, 'get').mockReturnValue(new Promise((resolve) => (resolveGet = resolve)) as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            logic.actions.sseDropped()
            logic.actions.closeSse()

            resolveGet({ status: 'in_progress' })
            await flushPromises()

            expect(logic.values.sseStatus).toEqual('closed')
            expect(logic.values.reconnectAttempt).toEqual(0)
        })

        it('surfaces a retryable error after exhausting the attempt cap', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            // Drive the attempt counter to the cap without an intervening successful open.
            logic.actions.sseReconnecting(MAX_SSE_RECONNECT_ATTEMPTS)

            logic.actions.sseDropped()
            await flushPromises()

            expect(logic.values.sseStatus).toEqual('error')
        })

        it('maps a refetch failure through the HTTP-status table', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockRejectedValue({ status: 404 })

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            logic.actions.sseDropped()
            await flushPromises()

            expect(logic.values.sseStatus).toEqual('error')
        })
    })

    describe('connection teardown', () => {
        // The keyed log store makes duplicate ingestion idempotent, so correctness no longer depends
        // on closing the exact connection a hot reload orphaned (the old EventSource registry is
        // gone). Teardown still aborts the active fetch so it stops streaming.
        it('aborts the active stream on closeSse', () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockStream.latest()

            logic.actions.closeSse()

            expect(source.closed).toEqual(true)
        })

        it('aborts the active stream on reset', () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockStream.latest()

            logic.actions.reset()

            expect(source.closed).toEqual(true)
        })
    })

    describe('bootstrapRun', () => {
        it('skips logs/ and opens SSE directly on the fresh-run fast path', async () => {
            const logsSpy = jest.spyOn(api.tasks.runs, 'getLogEntries')

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1', justCreatedRun: true })
            await flushPromises()

            expect(logsSpy).not.toHaveBeenCalled()
            expect(MockStream.connections.length).toEqual(1)
            expect(MockStream.latest().options.startLatest).toEqual(false)
        })

        it('opens SSE with start=latest and replays history for a non-terminal run', async () => {
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([
                notification('_posthog/run_started', {}) as any,
                sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'history' } }) as any,
            ])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            expect(logic.values.runStarted).toEqual(true)
            const assistantItem = logic.values.threadItems.find((item) => item.type === 'assistant_message')
            expect(assistantItem?.text).toEqual('history')
            // No live frame carried an id, so the connect opens from latest (no resume cursor).
            expect(MockStream.latest().options.startLatest).toEqual(true)
            expect(MockStream.latest().options.lastEventId).toBeUndefined()
        })

        it('replays logs/ and stays read-only for a terminal run', async () => {
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            expect(logic.values.currentRunStatus).toEqual('completed')
            expect(MockStream.connections.length).toEqual(0)
        })

        it('fetches history exactly once for a terminal run (no terminal reconcile pass)', async () => {
            const logsSpy = jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            expect(logsSpy).toHaveBeenCalledTimes(1)
        })

        it('connects the SSE before reading history and buffers live frames until the snapshot drains', async () => {
            // Connect-first is what closes the seam: a frame the agent emits while the history fetch
            // is in flight is captured by the (already-open) live stream and buffered, not gapped.
            let resolveLogs: (value: unknown) => void = () => {}
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockReturnValue(
                new Promise((resolve) => (resolveLogs = resolve)) as any
            )
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            // The SSE is open before the (still-pending) history fetch resolves.
            expect(MockStream.connections.length).toEqual(1)
            expect(MockStream.latest().options.startLatest).toEqual(true)

            // A live frame arriving now is buffered, not yet rendered.
            await MockStream.latest().emitOpen()
            await MockStream.latest().emitMessage(
                sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm-live', content: { text: 'live tail' } }),
                '5-0'
            )
            expect(logic.values.threadItems.filter((item) => item.type === 'assistant_message')).toHaveLength(0)

            // Snapshot lands → history renders, then the buffered live tail drains in after it.
            resolveLogs([
                notification('_posthog/run_started', {}) as any,
                sessionUpdate({
                    sessionUpdate: 'agent_message',
                    messageId: 'm-hist',
                    content: { text: 'history' },
                }) as any,
            ])
            await flushPromises()

            expect(
                logic.values.threadItems.filter((item) => item.type === 'assistant_message').map((item) => item.text)
            ).toEqual(['history', 'live tail'])
        })

        it('drains the seam by content: a frame in both history and the buffered live tail renders once', async () => {
            // The exact keyless-`agent_message` duplication: the same finalized message is delivered
            // live during the fetch AND persisted in the snapshot. The multiset absorbs the live copy.
            let resolveLogs: (value: unknown) => void = () => {}
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockReturnValue(
                new Promise((resolve) => (resolveLogs = resolve)) as any
            )
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()
            await MockStream.latest().emitOpen()

            const overlap = sessionUpdate({ sessionUpdate: 'agent_message', content: { text: 'overlap' } })
            await MockStream.latest().emitMessage(overlap, '9-0')

            resolveLogs([overlap as any])
            await flushPromises()

            expect(
                logic.values.threadItems.filter((item) => item.type === 'assistant_message').map((item) => item.text)
            ).toEqual(['overlap'])
        })

        it('keeps a genuinely repeated payload when the buffer holds more copies than history (multiset)', async () => {
            // The agent legitimately emitted the same message twice live; the snapshot captured only
            // one (the second landed after the snapshot read). One historical copy absorbs one buffered
            // copy; the surplus survives — counts, not a set.
            let resolveLogs: (value: unknown) => void = () => {}
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockReturnValue(
                new Promise((resolve) => (resolveLogs = resolve)) as any
            )
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()
            await MockStream.latest().emitOpen()

            const repeated = sessionUpdate({
                sessionUpdate: 'agent_message',
                messageId: 'm1',
                content: { text: 'ping' },
            })
            await MockStream.latest().emitMessage(repeated, '1-0')
            await MockStream.latest().emitMessage(repeated, '2-0')

            resolveLogs([repeated as any])
            await flushPromises()

            expect(
                logic.values.threadItems.filter((item) => item.type === 'assistant_message').map((item) => item.text)
            ).toEqual(['ping', 'ping'])
        })
    })

    describe('replayOnly viewer (read-only)', () => {
        function mountViewer(streamKey: string): ReturnType<typeof runStreamLogic.build> {
            const viewer = runStreamLogic({ streamKey, replayOnly: true })
            viewer.mount()
            return viewer
        }

        it('replays a terminal run read-only without opening SSE and never thinks', async () => {
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([
                notification('_posthog/run_started', {}) as any,
                sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'done' } }) as any,
            ])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            const viewer = mountViewer('run-ro-terminal')
            viewer.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            expect(viewer.values.threadItems.find((item) => item.type === 'assistant_message')?.text).toEqual('done')
            expect(viewer.values.currentRunStatus).toEqual('completed')
            expect(MockStream.connections.length).toEqual(0)
            expect(viewer.values.isThinking).toEqual(false)
            expect(viewer.values.bootstrapLoading).toEqual(false)

            viewer.unmount()
        })

        it('replays an in-progress snapshot without opening SSE and stays idle', async () => {
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([
                notification('_posthog/run_started', {}) as any,
                sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'partial' } }) as any,
            ])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            const viewer = mountViewer('run-ro-inprogress')
            viewer.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-2' })
            await flushPromises()

            expect(viewer.values.threadItems.find((item) => item.type === 'assistant_message')?.text).toEqual('partial')
            // run_started replayed, but a read-only snapshot never streams and never spins the indicator.
            expect(MockStream.connections.length).toEqual(0)
            expect(viewer.values.streamPhase).toEqual('idle')
            expect(viewer.values.isThinking).toEqual(false)

            viewer.unmount()
        })

        it('folds the snapshot only once across a re-bootstrap of the shared instance', async () => {
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([
                sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'once' } }) as any,
            ])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            const viewer = mountViewer('run-ro-idempotent')
            viewer.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-3' })
            await flushPromises()
            // A second mounted viewer of the same run re-bootstraps the shared keyed instance.
            viewer.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-3' })
            await flushPromises()

            expect(viewer.values.threadItems.filter((item) => item.type === 'assistant_message')).toHaveLength(1)

            viewer.unmount()
        })

        it('retries the snapshot then surfaces the connection-failed banner (not an inline error), no SSE', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)
            const getLogEntriesSpy = jest.spyOn(api.tasks.runs, 'getLogEntries').mockRejectedValue({ status: 500 })

            jest.useFakeTimers()
            const viewer = mountViewer('run-ro-error')
            viewer.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-4' })
            // Advance past the inter-attempt backoff so every retry runs and the terminal state lands.
            await jest.advanceTimersByTimeAsync(10_000)
            await flushPromises()

            expect(getLogEntriesSpy).toHaveBeenCalledTimes(MAX_HISTORY_FETCH_ATTEMPTS)
            // The failure drives the footer banner via `runConnectionState`, not a spammy inline error item.
            expect(viewer.values.runConnectionState?.kind).toEqual('connection_failed')
            expect(viewer.values.threadItems.some((item) => item.type === 'error')).toEqual(false)
            expect(MockStream.connections.length).toEqual(0)
            expect(viewer.values.bootstrapLoading).toEqual(false)

            jest.useRealTimers()
            viewer.unmount()
        })

        it('keys read-only instances apart from a live stream of the same run', async () => {
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([
                sessionUpdate({
                    sessionUpdate: 'agent_message',
                    messageId: 'm1',
                    content: { text: 'replayed' },
                }) as any,
            ])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            const live = runStreamLogic({ streamKey: 'run-shared' })
            live.mount()
            const viewer = mountViewer('run-shared')

            // Same streamKey, but the read-only `replay:` namespace resolves a distinct instance.
            expect(viewer).not.toBe(live)

            viewer.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-5' })
            await flushPromises()

            // The replay folds into the viewer only; the live instance is untouched — streaming can't bleed in.
            expect(viewer.values.threadItems.find((item) => item.type === 'assistant_message')?.text).toEqual(
                'replayed'
            )
            expect(live.values.threadItems).toHaveLength(0)

            viewer.unmount()
            live.unmount()
        })
    })

    describe('wire frame parsing through the SSE reader', () => {
        it('reads the snake_case error_message off task_run_state frames', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockStream.latest()
            await source.emitOpen()

            await source.emitMessage({
                type: 'task_run_state',
                run_id: 'run-1',
                task_id: 'task-1',
                status: 'failed',
                error_message: 'sandbox exploded',
            })

            expect(logic.values.currentRunStatus).toEqual('failed')
            expect(source.closed).toEqual(true)
        })

        it('keeps the stream open for non-terminal task_run_state frames', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockStream.latest()
            await source.emitOpen()

            await source.emitMessage({ type: 'task_run_state', status: 'in_progress', error_message: null })

            expect(logic.values.currentRunStatus).toEqual('in_progress')
            expect(source.closed).toEqual(false)
        })

        it('ignores unrecognized frame types', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockStream.latest()
            await source.emitOpen()

            await source.emitMessage({ type: 'telemetry_v2', payload: { value: 1 } })

            expect(logic.values.threadItems).toEqual([])
            expect(logic.values.log.entries).toHaveLength(0)
        })
    })

    describe('_posthog/progress handling', () => {
        it('renders the emitter label as current progress and stores a progress thread item', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    notification('_posthog/progress', {
                        sessionId: 's',
                        step: 'clone',
                        status: 'in_progress',
                        label: 'Cloning repository',
                        group: 'setup:run-1',
                    })
                )
            }).toMatchValues({ currentProgress: 'Cloning repository' })

            expect(logic.values.threadItems).toEqual([
                {
                    id: 'progress-setup:run-1',
                    type: 'progress',
                    progressGroup: 'setup:run-1',
                    progressSteps: [
                        {
                            key: 'clone',
                            status: 'in_progress',
                            label: 'Cloning repository',
                        },
                    ],
                },
            ])
        })

        it('coalesces setup progress by group and updates repeated steps in place', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    notification('_posthog/progress', {
                        sessionId: 's',
                        step: 'sandbox',
                        status: 'in_progress',
                        label: 'Setting up sandbox',
                        group: 'setup:run-1',
                    })
                )
                logic.actions.ingestAcpFrame(
                    notification('_posthog/progress', {
                        sessionId: 's',
                        step: 'sandbox',
                        status: 'completed',
                        label: 'Set up sandbox',
                        group: 'setup:run-1',
                    })
                )
                logic.actions.ingestAcpFrame(
                    notification('_posthog/progress', {
                        sessionId: 's',
                        step: 'clone',
                        status: 'in_progress',
                        label: 'Cloning repository',
                        group: 'setup:run-1',
                    })
                )
            }).toFinishAllListeners()

            expect(logic.values.threadItems).toEqual([
                {
                    id: 'progress-setup:run-1',
                    type: 'progress',
                    progressGroup: 'setup:run-1',
                    progressSteps: [
                        {
                            key: 'sandbox',
                            status: 'completed',
                            label: 'Set up sandbox',
                        },
                        {
                            key: 'clone',
                            status: 'in_progress',
                            label: 'Cloning repository',
                        },
                    ],
                },
            ])
        })

        it('falls back to detail when label is absent', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    notification('_posthog/progress', { sessionId: 's', detail: 'PostHog/posthog @ master' })
                )
            }).toMatchValues({ currentProgress: 'PostHog/posthog @ master' })

            expect(logic.values.threadItems).toEqual([])
        })
    })

    describe('mergeResourceProducts', () => {
        it('unions by id, preserves first-seen order, and tolerates empty/idless input', () => {
            const first = mergeResourceProducts([], [{ id: 'product_analytics', label: 'Product analytics' }])
            expect(first).toEqual([{ id: 'product_analytics', label: 'Product analytics' }])

            const second = mergeResourceProducts(first, [
                { id: 'product_analytics', label: 'dup' },
                { id: 'session_replay', label: 'Session replay' },
                { label: 'no id' },
                { id: '' },
            ])
            expect(second.map((p) => p.id)).toEqual(['product_analytics', 'session_replay'])
            // First-seen label wins for an id already present.
            expect(second[0].label).toEqual('Product analytics')
        })
    })

    describe('_posthog/resources_used handling', () => {
        it('unions products into resourcesUsed by id in first-seen order', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    notification('_posthog/resources_used', {
                        products: [
                            { id: 'product_analytics', label: 'Product analytics' },
                            { id: 'session_replay', label: 'Session replay' },
                        ],
                    })
                )
                logic.actions.ingestAcpFrame(
                    notification('_posthog/resources_used', {
                        products: [
                            { id: 'session_replay', label: 'Session replay' },
                            { id: 'sql', label: 'SQL' },
                        ],
                    })
                )
            }).toFinishAllListeners()

            expect(logic.values.resourcesUsed.map((p) => p.id)).toEqual(['product_analytics', 'session_replay', 'sql'])
        })

        it('survives bootstrap replay without double-counting (same frame twice → one entry set)', async () => {
            const frame = notification('_posthog/resources_used', {
                products: [{ id: 'product_analytics', label: 'Product analytics' }],
            })
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([frame as any, frame as any])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            // Content-dedup drops the identical replay; the union would dedup by id regardless.
            expect(logic.values.resourcesUsed.map((p) => p.id)).toEqual(['product_analytics'])
        })
    })

    describe('_posthog/usage_update handling', () => {
        it('folds the Codex split frames (used + cost, then breakdown) into contextUsage', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    notification('_posthog/usage_update', {
                        used: { inputTokens: 100, outputTokens: 20 },
                        cost: { amount: 0.42, currency: 'USD' },
                    })
                )
                logic.actions.ingestAcpFrame(
                    notification('_posthog/usage_update', { breakdown: { systemPrompt: 10, tools: 5 } })
                )
            }).toFinishAllListeners()

            expect(logic.values.contextUsage?.tokens).toEqual({ inputTokens: 100, outputTokens: 20 })
            expect(logic.values.contextUsage?.cost).toEqual(0.42)
            expect(logic.values.contextUsage?.breakdown).toEqual({ systemPrompt: 10, tools: 5 })
        })

        it('folds the Claude combined frame (used + numeric cost + breakdown) into contextUsage', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    notification('_posthog/usage_update', {
                        used: { inputTokens: 5000, outputTokens: 600 },
                        cost: 0.18,
                        breakdown: { conversation: 9000 },
                    })
                )
            }).toFinishAllListeners()

            expect(logic.values.contextUsage?.tokens).toEqual({ inputTokens: 5000, outputTokens: 600 })
            expect(logic.values.contextUsage?.cost).toEqual(0.18)
            expect(logic.values.contextUsage?.breakdown).toEqual({ conversation: 9000 })
        })

        it('lands the numeric used/size aggregate from a session/update-framed usage_update', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    sessionUpdate({
                        sessionUpdate: 'usage_update',
                        used: 168000,
                        size: 200000,
                        cost: { amount: 1.2, currency: 'USD' },
                    })
                )
            }).toFinishAllListeners()

            expect(logic.values.contextUsage?.used).toEqual(168000)
            expect(logic.values.contextUsage?.size).toEqual(200000)
            expect(logic.values.contextUsage?.cost).toEqual(1.2)
            // The aggregate must not be misrouted into a thread item.
            expect(logic.values.threadItems).toEqual([])
        })

        it('merges the aggregate ring numbers with the ext-notification tokens/breakdown', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    notification('_posthog/usage_update', {
                        used: { inputTokens: 100 },
                        breakdown: { tools: 5 },
                    })
                )
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'usage_update', used: 12000, size: 200000 })
                )
            }).toFinishAllListeners()

            expect(logic.values.contextUsage).toEqual({
                tokens: { inputTokens: 100 },
                breakdown: { tools: 5 },
                used: 12000,
                size: 200000,
            })
        })
    })

    describe('_posthog/status + compact_boundary inline items', () => {
        it('pushes a status item for an in-progress compaction', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(notification('_posthog/status', { status: 'compacting' }))
            }).toFinishAllListeners()

            const item = logic.values.threadItems.find((i) => i.type === 'status')
            expect(item).toEqual(expect.objectContaining({ type: 'status', status: 'compacting', isComplete: false }))
        })

        it('pushes nothing for a completed compaction status', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    notification('_posthog/status', { status: 'compacting', isComplete: true })
                )
            }).toFinishAllListeners()

            expect(logic.values.threadItems).toEqual([])
        })

        it('pushes a compact_boundary item carrying trigger/preTokens/contextSize', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    notification('_posthog/compact_boundary', {
                        trigger: 'auto',
                        preTokens: 168000,
                        contextSize: 54000,
                    })
                )
            }).toFinishAllListeners()

            const item = logic.values.threadItems.find((i) => i.type === 'compact_boundary')
            expect(item).toEqual(
                expect.objectContaining({
                    type: 'compact_boundary',
                    trigger: 'auto',
                    preTokens: 168000,
                    contextSize: 54000,
                })
            )
        })

        it('clears the in-progress compaction spinner once compaction completes', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(notification('_posthog/status', { status: 'compacting' }))
                logic.actions.ingestAcpFrame(
                    notification('_posthog/status', { status: 'compacting', isComplete: true })
                )
            }).toFinishAllListeners()

            expect(logic.values.threadItems.filter((i) => i.type === 'status')).toEqual([])
        })

        it('replaces the in-progress spinner with the compact_boundary divider', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(notification('_posthog/status', { status: 'compacting' }))
                logic.actions.ingestAcpFrame(notification('_posthog/compact_boundary', { trigger: 'auto' }))
            }).toFinishAllListeners()

            const items = logic.values.threadItems
            expect(items.some((i) => i.type === 'status')).toBe(false)
            expect(items.some((i) => i.type === 'compact_boundary')).toBe(true)
        })
    })

    describe('_posthog/task_notification inline item', () => {
        it('pushes a task_notification item carrying status + summary', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    notification('_posthog/task_notification', {
                        status: 'completed',
                        summary: 'Analysis written to report.md',
                    })
                )
            }).toFinishAllListeners()

            const item = logic.values.threadItems.find((i) => i.type === 'task_notification')
            expect(item).toEqual(
                expect.objectContaining({
                    type: 'task_notification',
                    status: 'completed',
                    summary: 'Analysis written to report.md',
                })
            )
        })
    })

    describe('_posthog/sdk_session handling', () => {
        it('stashes the adapter/session identity without rendering UI', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    notification('_posthog/sdk_session', {
                        taskRunId: 'run-1',
                        sessionId: 'sess_a1b2c3',
                        adapter: 'claude',
                    })
                )
            }).toFinishAllListeners()

            expect(logic.values.sdkSession).toEqual({ sessionId: 'sess_a1b2c3', adapter: 'claude' })
            expect(logic.values.threadItems).toEqual([])
        })
    })

    describe('reset clears notification state', () => {
        it('clears resourcesUsed, contextUsage, and sdkSession on reset', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    notification('_posthog/resources_used', { products: [{ id: 'sql', label: 'SQL' }] })
                )
                logic.actions.ingestAcpFrame(notification('_posthog/usage_update', { used: { inputTokens: 1 } }))
                logic.actions.ingestAcpFrame(notification('_posthog/sdk_session', { adapter: 'codex' }))
            }).toFinishAllListeners()

            expect(logic.values.resourcesUsed).toHaveLength(1)
            expect(logic.values.contextUsage).not.toBeNull()
            expect(logic.values.sdkSession).not.toBeNull()

            await expectLogic(logic, () => {
                logic.actions.reset()
            }).toFinishAllListeners()

            expect(logic.values.resourcesUsed).toEqual([])
            expect(logic.values.contextUsage).toBeNull()
            expect(logic.values.sdkSession).toBeNull()
        })

        it('keeps resourcesUsed across markTurnComplete (accumulates over the session)', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    notification('_posthog/resources_used', { products: [{ id: 'sql', label: 'SQL' }] })
                )
                logic.actions.markTurnComplete()
            }).toFinishAllListeners()

            expect(logic.values.resourcesUsed.map((p) => p.id)).toEqual(['sql'])
        })
    })

    describe('mixed notification replay', () => {
        it('ingests known, unknown, and degenerate notifications without throwing, appending each once', async () => {
            const corpus: StoredLogEntry[] = [
                notification('_posthog/run_started', { runId: 'run-1' }),
                notification('_posthog/usage_update', { used: { inputTokens: 1 }, cost: null }),
                notification('_posthog/hologram_sync', { shards: 3 }),
                { type: 'notification', notification: { method: '_posthog/turn_complete' } },
                { type: 'notification', notification: { method: '_posthog/console', params: 'not-an-object' as any } },
                sessionUpdate({ sessionUpdate: 'plan_delta', entries: [] }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', text: 'hi' }),
            ]

            await expectLogic(logic, () => {
                corpus.forEach((entry) => logic.actions.ingestAcpFrame(entry))
            }).toFinishAllListeners()

            // The log is append-only — every frame lands once, in order.
            expect(logic.values.log.entries).toHaveLength(corpus.length)
        })
    })

    describe('telemetry parity', () => {
        it('emits TASK_RUN_STARTED once on the first run_started frame, always cold (wire carries no warmth)', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({
                taskId: 'task-1',
                runId: 'run-1',
                traceId: 'trace-1',
            })

            await expectLogic(logic, () => {
                // A stray cold_start hint on the wire is ignored — pre-warming isn't wired yet.
                logic.actions.ingestAcpFrame(notification('_posthog/run_started', { cold_start: false }))
                logic.actions.ingestAcpFrame(notification('_posthog/run_started', {}))
            }).toFinishAllListeners()

            const startedCalls = captureSpy.mock.calls.filter((c) => c[0] === 'task_run_started')
            expect(startedCalls.length).toEqual(1)
            expect(startedCalls[0][1]).toEqual(
                expect.objectContaining({
                    conversation_id: 'test-conversation',
                    trace_id: 'trace-1',
                    run_id: 'run-1',
                    task_id: 'task-1',
                    execution_type: 'sandbox',
                    cold_start: true,
                })
            )
        })

        it('emits TASK_RUN_TERMINATED with duration_ms measured from run start', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({
                taskId: 'task-1',
                runId: 'run-1',
                traceId: 'trace-1',
            })

            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(notification('_posthog/run_started', {}))
                logic.actions.handleTerminalStatus({ status: 'failed', errorMessage: 'boom' })
            }).toFinishAllListeners()

            const call = captureSpy.mock.calls.find((c) => c[0] === 'task_run_terminated')
            expect(call?.[1]).toEqual(
                expect.objectContaining({
                    conversation_id: 'test-conversation',
                    trace_id: 'trace-1',
                    run_id: 'run-1',
                    status: 'failed',
                    error_message: 'boom',
                    execution_type: 'sandbox',
                })
            )
            expect((call![1] as any).duration_ms).toBeGreaterThanOrEqual(0)
        })

        it('emits TOOL_CALL_COMPLETED once when a tool call reaches a terminal status', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({
                taskId: 'task-1',
                runId: 'run-1',
                traceId: 'trace-1',
            })

            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    sessionUpdate({
                        sessionUpdate: 'tool_call',
                        toolCallId: 't1',
                        serverName: 'posthog',
                        toolName: 'exec',
                        rawInput: { command: 'call execute-sql {"query":"select 1"}' },
                        status: 'in_progress',
                    })
                )
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'tool_call_update', toolCallId: 't1', status: 'completed' })
                )
                // A second terminal update must not re-emit.
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'tool_call_update', toolCallId: 't1', status: 'completed' })
                )
            }).toFinishAllListeners()

            const toolCalls = captureSpy.mock.calls.filter((c) => c[0] === 'tool_call_completed')
            expect(toolCalls.length).toEqual(1)
            expect(toolCalls[0][1]).toEqual(
                expect.objectContaining({
                    conversation_id: 'test-conversation',
                    trace_id: 'trace-1',
                    tool_call_id: 't1',
                    tool_qualified_name: 'execute-sql',
                    status: 'completed',
                    execution_type: 'sandbox',
                })
            )
        })

        it('commands the streamed run via the tasks relay on respondToPermission', async () => {
            logic.actions.openSseForRun({
                taskId: 'task-1',
                runId: 'run-1',
                traceId: 'trace-1',
            })

            await expectLogic(logic, () => {
                logic.actions.respondToPermission({
                    requestId: 'req-1',
                    optionId: 'allow_once',
                })
            }).toFinishAllListeners()

            // "Command the latest run": the reply targets the (task, run) the renderer is streaming.
            expect(tasksRunsCommandCreate).toHaveBeenCalledWith('997', 'task-1', 'run-1', {
                jsonrpc: '2.0',
                method: 'permission_response',
                params: { requestId: 'req-1', optionId: 'allow_once', customInput: undefined, answers: undefined },
            })
        })

        it('cancelRun cancels the streamed run via the tasks relay', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })

            await expectLogic(logic, () => {
                logic.actions.cancelRun()
            }).toFinishAllListeners()

            expect(tasksRunsCommandCreate).toHaveBeenCalledWith('997', 'task-1', 'run-1', {
                jsonrpc: '2.0',
                method: 'cancel',
            })
        })

        it('cancelRun cancels an explicit (warm) run the renderer is not streaming', async () => {
            // A warm Run is released by id without the renderer ever opening SSE against it.
            await expectLogic(logic, () => {
                logic.actions.cancelRun({ taskId: 'warm-task', runId: 'warm-run' })
            }).toFinishAllListeners()

            expect(tasksRunsCommandCreate).toHaveBeenCalledWith('997', 'warm-task', 'warm-run', {
                jsonrpc: '2.0',
                method: 'cancel',
            })
        })

        it('suppresses run lifecycle telemetry while replaying history on bootstrap', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([
                notification('_posthog/run_started', {}) as any,
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't1',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: { command: 'call execute-sql {"query":"select 1"}' },
                    status: 'in_progress',
                }) as any,
                sessionUpdate({ sessionUpdate: 'tool_call_update', toolCallId: 't1', status: 'completed' }) as any,
            ])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            // History is folded in (run marked started, status terminal) but none of the lifecycle
            // events re-fire — the run lived and died in a prior session.
            expect(logic.values.runStarted).toEqual(true)
            expect(logic.values.currentRunStatus).toEqual('completed')
            const lifecycleEvents = ['task_run_started', 'task_run_terminated', 'tool_call_completed']
            expect(captureSpy.mock.calls.filter((c) => lifecycleEvents.includes(c[0] as string))).toEqual([])
        })
    })

    describe('crash affordance', () => {
        it('pushes a crash-variant error item and still captures task_run_terminated', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1', traceId: 'trace-1' })

            await expectLogic(logic, () => {
                logic.actions.handleTerminalStatus({
                    status: 'failed',
                    errorMessage: 'Agent server crashed: boom',
                })
            }).toFinishAllListeners()

            const errorItem = logic.values.threadItems.find((item) => item.type === 'error')
            expect(errorItem?.variant).toEqual('crash')
            expect(errorItem?.errorMessage).toEqual('Agent server crashed: boom')
            // The existing termination telemetry is unchanged.
            const terminated = captureSpy.mock.calls.find((c) => c[0] === 'task_run_terminated')
            expect(terminated?.[1]).toEqual(
                expect.objectContaining({ status: 'failed', error_message: 'Agent server crashed: boom' })
            )
        })

        it('renders a plain failed run without the crash prefix as a raw error item', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })

            await expectLogic(logic, () => {
                logic.actions.handleTerminalStatus({ status: 'failed', errorMessage: 'usage limit reached' })
            }).toFinishAllListeners()

            const errorItem = logic.values.threadItems.find((item) => item.type === 'error')
            expect(errorItem?.variant).toEqual('error')
            expect(errorItem?.errorMessage).toEqual('usage limit reached')
        })

        it('does not push an error item for a failed run carrying no error message', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })

            await expectLogic(logic, () => {
                logic.actions.handleTerminalStatus({ status: 'failed' })
            }).toFinishAllListeners()

            expect(logic.values.threadItems.some((item) => item.type === 'error')).toEqual(false)
        })

        it('does not push an error item for a failed run replayed from history', async () => {
            await expectLogic(logic, () => {
                logic.actions.handleTerminalStatus({
                    status: 'failed',
                    errorMessage: 'Agent server crashed: old',
                    replayedFromHistory: true,
                })
            }).toFinishAllListeners()

            expect(logic.values.threadItems.some((item) => item.type === 'error')).toEqual(false)
        })
    })

    describe('stream-disconnect telemetry', () => {
        it('captures sandbox_stream_disconnected and surfaces the banner without spamming error items', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1', traceId: 'trace-1' })
            // Drive the per-drop counter to the cap so the next drop exhausts the budget.
            logic.actions.sseReconnecting(MAX_SSE_RECONNECT_ATTEMPTS)

            logic.actions.sseDropped()
            await flushPromises()

            expect(logic.values.sseStatus).toEqual('error')
            const disconnect = captureSpy.mock.calls.find((c) => c[0] === 'sandbox_stream_disconnected')
            expect(disconnect?.[1]).toEqual(
                expect.objectContaining({
                    conversation_id: 'test-conversation',
                    trace_id: 'trace-1',
                    run_id: 'run-1',
                    task_id: 'task-1',
                    error_title: 'Cloud stream failed',
                    retryable: true,
                    reconnect_attempts: MAX_SSE_RECONNECT_ATTEMPTS,
                    cumulative_reconnect_attempts: 1,
                    was_bootstrapping: false,
                    execution_type: 'sandbox',
                })
            )
            // The failure surfaces via the single footer banner, NOT an appended inline error item (the
            // old behavior stacked a fresh red bubble on every drop — the spam this change removes).
            expect(logic.values.runConnectionState?.kind).toEqual('connection_failed')
            expect(logic.values.threadItems.some((item) => item.type === 'error')).toEqual(false)
        })

        it('projects the reconnect attempt counter into runConnectionState for the footer banner', () => {
            logic.actions.sseReconnecting(3)
            expect(logic.values.runConnectionState).toEqual({
                kind: 'reconnecting',
                attempt: 3,
                maxAttempts: MAX_SSE_RECONNECT_ATTEMPTS,
            })
        })

        it('retries the snapshot before teardown and reports was_bootstrapping=true on exhaustion', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)
            const getLogEntriesSpy = jest.spyOn(api.tasks.runs, 'getLogEntries').mockRejectedValue({ status: 500 })

            jest.useFakeTimers()
            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            // The snapshot is retried before the live stream is torn down; advance past the backoff.
            await jest.advanceTimersByTimeAsync(10_000)
            await flushPromises()

            // A transient history blip must not tear down on the first failure — only exhausting the retries does.
            expect(getLogEntriesSpy).toHaveBeenCalledTimes(MAX_HISTORY_FETCH_ATTEMPTS)
            // The history fetch failed during bootstrap and no `_posthog/run_started` ever arrived, so
            // the provisioning flag is still set even though the SSE briefly opened (connect-first).
            const disconnect = captureSpy.mock.calls.find((c) => c[0] === 'sandbox_stream_disconnected')
            expect(disconnect?.[1]).toEqual(expect.objectContaining({ was_bootstrapping: true }))

            jest.useRealTimers()
        })
    })

    describe('stream phase', () => {
        it('is provisioning while the stream is open before run_started, then flips to thinking', async () => {
            expect(logic.values.streamPhase).toEqual('idle')

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            await MockStream.latest().emitOpen()

            // SSE open, agent not started yet — provisioning, surfacing _posthog/progress.
            logic.actions.ingestAcpFrame(notification('_posthog/progress', { label: 'Setting up sandbox' }))
            expect(logic.values.streamPhase).toEqual('provisioning')
            expect(logic.values.currentProgress).toEqual('Setting up sandbox')

            // run_started arrives — phase flips to thinking.
            logic.actions.ingestAcpFrame(notification('_posthog/run_started', {}))
            expect(logic.values.streamPhase).toEqual('thinking')

            // turn_complete ends the turn — back to idle.
            logic.actions.ingestAcpFrame(notification('_posthog/turn_complete', {}))
            expect(logic.values.streamPhase).toEqual('idle')
        })

        it('tracks the optional task_run_state stage off the wire', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockStream.latest()
            await source.emitOpen()

            await source.emitMessage({ type: 'task_run_state', status: 'in_progress', stage: 'build' })

            expect(logic.values.currentStage).toEqual('build')
        })
    })

    describe('reconnect refinements', () => {
        it('forgives a healthy connection drop — no reconnectAttempt increment but still schedules a reopen', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockStream.latest()

            jest.useFakeTimers()
            // sseOpened stamps cache.sseConnectedAtMs in fake-time; drain the open then advance past
            // the healthy threshold before dropping.
            await source.emitOpen()
            const beforeDrop = MockStream.connections.length
            jest.advanceTimersByTime(SSE_HEALTHY_CONNECTION_MS + 1_000)

            logic.actions.sseDropped()
            await flushPromises()

            // Healthy drop: per-drop budget untouched, but cumulative still grows and a reopen is scheduled.
            expect(logic.values.reconnectAttempt).toEqual(0)
            expect(logic.values.cumulativeReconnectAttempt).toEqual(1)
            expect(logic.values.sseStatus).toEqual('reconnecting')

            jest.advanceTimersByTime(SSE_RECONNECT_BASE_DELAY_MS)
            expect(MockStream.connections.length).toEqual(beforeDrop + 1)
            jest.useRealTimers()
        })

        it('fails on the cumulative cap even when the per-drop counter keeps resetting', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            await MockStream.latest().emitOpen()
            // Drive the cumulative counter to the cap without growing the per-drop counter, as a
            // clean-EOF reopen loop would (every reopen resets reconnectAttempt to 0).
            for (let i = 0; i < MAX_CUMULATIVE_RECONNECT_ATTEMPTS; i++) {
                logic.actions.sseReconnecting(0)
            }
            expect(logic.values.cumulativeReconnectAttempt).toEqual(MAX_CUMULATIVE_RECONNECT_ATTEMPTS)

            logic.actions.sseDropped()
            await flushPromises()

            // The (cumulative + 1)th reconnect crosses the bound → terminal error.
            expect(logic.values.sseStatus).toEqual('error')
        })
    })

    describe('permission_request ingest', () => {
        // A destructive exec (`insight-update`) so the default policy prompts (shows a card) rather
        // than auto-approving — the lifecycle tests below all assume a card appears.
        const permissionFrame: PermissionRequestFrame = {
            type: 'permission_request',
            requestId: 'req-1',
            toolCall: {
                toolCallId: 't1',
                serverName: 'posthog',
                toolName: 'exec',
                _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
                rawInput: { command: 'call insight-update {"id":"abc"}' },
                title: 'Update insight',
                status: 'pending',
            },
            options: [
                { optionId: 'allow_once', name: 'Approve', kind: 'allow_once' },
                { optionId: 'reject', name: 'Decline', kind: 'reject' },
            ],
        }

        it('parses a permission_request frame into a PermissionRequestRecord', () => {
            const record = parsePermissionRequestFrame(permissionFrame)
            expect(record).not.toBeNull()
            expect(record?.requestId).toEqual('req-1')
            expect(record?.toolCallId).toEqual('t1')
            expect(record?.toolName).toEqual('mcp__posthog__exec')
            expect(record?.options.map((o) => o.kind)).toEqual(['allow_once', 'reject'])
            expect(record?.rawToolCall.rawServerName).toEqual('posthog')
            expect(record?.rawToolCall.rawToolName).toEqual('exec')
            expect(record?.rawToolCall.input).toEqual({ command: 'call insight-update {"id":"abc"}' })
            expect(record?.rawToolCall.meta).toEqual({ claudeCode: { toolName: 'mcp__posthog__exec' } })
        })

        it('returns null for a frame with no usable options', () => {
            expect(parsePermissionRequestFrame({ ...permissionFrame, options: [] })).toBeNull()
            expect(parsePermissionRequestFrame({ type: 'permission_request', requestId: 'r', toolCall: {} })).toBeNull()
        })

        it('keeps a reject_once option and parses _meta.customInput (the previously-dropped decline)', () => {
            // Exact shape the agent adapter emits (see ee/hogai/sandbox/log.jsonl): the decline option
            // is `reject_once` carrying `_meta.customInput`, which the old exact-match allowlist dropped.
            const frame = {
                type: 'permission_request',
                requestId: 'req-2',
                toolCall: { toolCallId: 't2', title: 'exec' },
                options: [
                    { optionId: 'allow', name: 'Yes', kind: 'allow_once' },
                    { optionId: 'allow_always', name: 'Yes, always allow', kind: 'allow_always' },
                    {
                        optionId: 'reject',
                        name: 'No, and tell the agent what to do differently',
                        kind: 'reject_once',
                        _meta: { customInput: true },
                    },
                ],
            }
            const record = parsePermissionRequestFrame(frame as unknown as PermissionRequestFrame)
            expect(record?.options.map((o) => o.kind)).toEqual(['allow_once', 'allow_always', 'reject_once'])
            expect(record?.options.find((o) => o.kind === 'reject_once')?.customInput).toEqual(true)
        })

        it('keeps Claude tool metadata on the raw tool call', () => {
            const record = parsePermissionRequestFrame({
                type: 'permission_request',
                requestId: 'req-2',
                toolCall: {
                    toolCallId: 't9',
                    title: 'Edit `app.ts`',
                    status: 'pending',
                    _meta: { claudeCode: { toolName: 'Edit' } },
                },
                options: [{ optionId: 'allow_once', name: 'Approve', kind: 'allow_once' }],
            })
            expect(record).not.toBeNull()
            expect(record?.toolName).toEqual('Edit')
            expect(record?.rawToolCall.rawToolName).toEqual('')
            expect(record?.rawToolCall.meta).toEqual({ claudeCode: { toolName: 'Edit' } })
        })

        it('populates pendingPermissionRequest off a permission_request SSE frame', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)

            await MockStream.latest().emitMessage({ ...permissionFrame })

            expect(logic.values.pendingPermissionRequest?.requestId).toEqual('req-1')
            expect(logic.values.pendingPermissionRequest?.toolCallId).toEqual('t1')
            expect(captureSpy).toHaveBeenCalledWith(
                'permission_requested',
                expect.objectContaining({ request_id: 'req-1', execution_type: 'sandbox' })
            )
        })

        it('auto-approves a non-destructive PostHog exec without showing a card', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            // Resolving the proxy stream target mints a token before `openStream`, so the connection
            // registers a microtask later — flush before grabbing it.
            await flushPromises()
            const source = MockStream.latest()

            await source.emitMessage({
                ...permissionFrame,
                requestId: 'req-auto',
                toolCall: {
                    ...permissionFrame.toolCall,
                    rawInput: { command: 'call insight-create {"name":"x"}' },
                },
            })

            expect(logic.values.pendingPermissionRequest).toBeNull()
            expect(tasksRunsCommandCreate).toHaveBeenCalledWith('997', 'task-1', 'run-1', {
                jsonrpc: '2.0',
                method: 'permission_response',
                params: { requestId: 'req-auto', optionId: 'allow_once' },
            })
            expect(captureSpy).toHaveBeenCalledWith(
                'permission_auto_approved',
                expect.objectContaining({ request_id: 'req-auto', execution_type: 'sandbox' })
            )
        })

        it('auto-approves a built-in tool without showing a card', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()
            const source = MockStream.latest()

            await source.emitMessage({
                type: 'permission_request',
                requestId: 'req-bash',
                toolCall: {
                    toolCallId: 't-bash',
                    _meta: { claudeCode: { toolName: 'Bash' } },
                    title: 'Bash',
                    rawInput: { command: 'ls -la' },
                },
                options: [{ optionId: 'allow', name: 'Yes', kind: 'allow_once' }],
            })

            expect(logic.values.pendingPermissionRequest).toBeNull()
            expect(tasksRunsCommandCreate).toHaveBeenCalledWith('997', 'task-1', 'run-1', {
                jsonrpc: '2.0',
                method: 'permission_response',
                params: { requestId: 'req-bash', optionId: 'allow' },
            })
        })

        it('falls back to a manual card when the auto-approve POST fails', async () => {
            ;(tasksRunsCommandCreate as jest.Mock).mockRejectedValue({ status: 502 })
            jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockStream.latest()

            await source.emitMessage({
                ...permissionFrame,
                requestId: 'req-fail',
                toolCall: {
                    ...permissionFrame.toolCall,
                    rawInput: { command: 'call insight-create {"name":"x"}' },
                },
            })

            expect(logic.values.pendingPermissionRequest?.requestId).toEqual('req-fail')
        })

        it('drives a generic task viewer with no conversation id', async () => {
            expect.assertions(4)
            // The renderer must work for runs created by other products that never mint a Conversation:
            // keyed by task id, commanding the relay by (task, run), with conversation_id absent from telemetry.
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            const viewerLogic = runStreamLogic({ streamKey: 'task-7' })
            viewerLogic.mount()
            try {
                viewerLogic.actions.openSseForRun({ taskId: 'task-7', runId: 'run-7' })
                viewerLogic.actions.ingestPermissionRequest(parsePermissionRequestFrame(permissionFrame)!)
                await expectLogic(viewerLogic, () => {
                    viewerLogic.actions.respondToPermission({ requestId: 'req-1', optionId: 'allow_once' })
                }).toFinishAllListeners()

                expect(tasksRunsCommandCreate).toHaveBeenCalledWith('997', 'task-7', 'run-7', {
                    jsonrpc: '2.0',
                    method: 'permission_response',
                    params: { requestId: 'req-1', optionId: 'allow_once', customInput: undefined, answers: undefined },
                })
                const permRequested = captureSpy.mock.calls.find((c) => c[0] === 'permission_requested')
                expect(permRequested).not.toBeUndefined()
                if (!permRequested) {
                    throw new Error('permission_requested telemetry was not captured')
                }
                const telemetryPayload = permRequested[1] as any
                expect(telemetryPayload.conversation_id).toBeUndefined()
                expect(telemetryPayload.task_id).toEqual('task-7')
            } finally {
                viewerLogic.unmount()
            }
        })

        it('clears the pending request and commands the run on respondToPermission', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            logic.actions.ingestPermissionRequest(parsePermissionRequestFrame(permissionFrame)!)

            await expectLogic(logic, () => {
                logic.actions.respondToPermission({
                    requestId: 'req-1',
                    optionId: 'allow_once',
                })
            }).toFinishAllListeners()

            expect(logic.values.pendingPermissionRequest).toBeNull()
            expect(logic.values.respondingToPermission).toEqual(false)
            expect(tasksRunsCommandCreate).toHaveBeenCalledWith('997', 'task-1', 'run-1', {
                jsonrpc: '2.0',
                method: 'permission_response',
                params: { requestId: 'req-1', optionId: 'allow_once', customInput: undefined, answers: undefined },
            })
        })

        it('keeps the card pending and surfaces an error when the reply command fails', async () => {
            ;(tasksRunsCommandCreate as jest.Mock).mockRejectedValue({ status: 502 })
            const exceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
            const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            logic.actions.ingestPermissionRequest(parsePermissionRequestFrame(permissionFrame)!)

            await expectLogic(logic, () => {
                logic.actions.respondToPermission({
                    requestId: 'req-1',
                    optionId: 'allow_once',
                })
            }).toFinishAllListeners()

            expect(logic.values.pendingPermissionRequest?.requestId).toEqual('req-1')
            // A failed reply POST must not tear down the live stream — the run is still alive and
            // blocked on this approval; only the card's buttons re-enable for a retry.
            expect(logic.values.sseStatus).not.toEqual('error')
            expect(logic.values.respondingToPermission).toEqual(false)
            expect(exceptionSpy).toHaveBeenCalled()
            expect(toastSpy).toHaveBeenCalled()
        })

        it('ignores a replayed permission_request envelope once the request is resolved', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockStream.latest()

            await source.emitMessage({ ...permissionFrame })
            await expectLogic(logic, () => {
                logic.actions.respondToPermission({
                    requestId: 'req-1',
                    optionId: 'allow_once',
                })
            }).toFinishAllListeners()
            expect(logic.values.pendingPermissionRequest).toBeNull()

            // A reconnect's resume re-delivers the envelope verbatim.
            await source.emitMessage({ ...permissionFrame })

            expect(logic.values.pendingPermissionRequest).toBeNull()
            expect(captureSpy).toHaveBeenCalledTimes(1)
        })

        it('does not double-capture telemetry when the same envelope arrives twice while pending', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockStream.latest()

            await source.emitMessage({ ...permissionFrame })
            await source.emitMessage({ ...permissionFrame })

            expect(logic.values.pendingPermissionRequest?.requestId).toEqual('req-1')
            expect(captureSpy).toHaveBeenCalledTimes(1)
        })

        it('re-derives a pending approval from a logged _posthog/permission_request without telemetry', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([
                notification('_posthog/permission_request', {
                    requestId: 'req-1',
                    toolCall: permissionFrame.toolCall,
                    options: permissionFrame.options,
                }) as any,
            ])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            expect(logic.values.pendingPermissionRequest?.requestId).toEqual('req-1')
            expect(captureSpy).not.toHaveBeenCalled()
        })

        it('drops a logged permission_request that has a matching permission_resolved entry', async () => {
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([
                notification('_posthog/permission_request', {
                    requestId: 'req-1',
                    toolCall: permissionFrame.toolCall,
                    options: permissionFrame.options,
                }) as any,
                notification('_posthog/permission_resolved', { requestId: 'req-1', optionId: 'allow_once' }) as any,
            ])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            expect(logic.values.pendingPermissionRequest).toBeNull()
        })

        it('clears the pending card when another client resolves the request', async () => {
            logic.actions.ingestPermissionRequest(parsePermissionRequestFrame(permissionFrame)!)
            expect(logic.values.pendingPermissionRequest?.requestId).toEqual('req-1')

            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(notification('_posthog/permission_resolved', { requestId: 'req-1' }))
            }).toFinishAllListeners()

            expect(logic.values.pendingPermissionRequest).toBeNull()
        })

        it('drops the pending card when the run reaches a terminal status, but not before', () => {
            logic.actions.ingestPermissionRequest(parsePermissionRequestFrame(permissionFrame)!)

            logic.actions.handleTerminalStatus({ status: 'queued' })
            expect(logic.values.pendingPermissionRequest?.requestId).toEqual('req-1')

            logic.actions.handleTerminalStatus({ status: 'completed' })
            expect(logic.values.pendingPermissionRequest).toBeNull()
        })
    })

    describe('agent-proxy stream routing', () => {
        const enableProxy = (): void =>
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TASKS_STREAM_VIA_PROXY], {
                [FEATURE_FLAGS.TASKS_STREAM_VIA_PROXY]: true,
            })

        beforeEach(() => {
            ;(tasksRunsStreamTokenRetrieve as jest.Mock).mockReset()
        })

        describe('resolveStreamTarget', () => {
            it('skips the token mint and streams from Django when the rollout is off', async () => {
                expect(await resolveStreamTarget('997', 'task-1', 'run-1', false)).toBeNull()
                expect(tasksRunsStreamTokenRetrieve).not.toHaveBeenCalled()
            })

            it('routes to the proxy when the server resolves a base URL', async () => {
                ;(tasksRunsStreamTokenRetrieve as jest.Mock).mockResolvedValue({
                    token: 'tok-1',
                    stream_base_url: 'https://proxy.example/',
                })
                expect(await resolveStreamTarget('997', 'task-1', 'run-1', true)).toEqual({
                    baseUrl: 'https://proxy.example/',
                    token: 'tok-1',
                })
            })

            it('falls back to Django when the server resolves no base URL', async () => {
                ;(tasksRunsStreamTokenRetrieve as jest.Mock).mockResolvedValue({
                    token: 'tok-1',
                    stream_base_url: null,
                })
                expect(await resolveStreamTarget('997', 'task-1', 'run-1', true)).toBeNull()
            })

            it('falls back to Django when minting the token throws', async () => {
                ;(tasksRunsStreamTokenRetrieve as jest.Mock).mockRejectedValue(new Error('forbidden'))
                expect(await resolveStreamTarget('997', 'task-1', 'run-1', true)).toBeNull()
            })
        })

        it('passes the resolved proxy target to openStream when the rollout is on', async () => {
            enableProxy()
            ;(tasksRunsStreamTokenRetrieve as jest.Mock).mockResolvedValue({
                token: 'tok-1',
                stream_base_url: 'https://proxy.example',
            })

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            expect(tasksRunsStreamTokenRetrieve).toHaveBeenCalledWith('997', 'task-1', 'run-1')
            expect(MockStream.latest().options.proxyTarget).toEqual({
                baseUrl: 'https://proxy.example',
                token: 'tok-1',
            })
        })

        it('never mints a token or sets a proxy target when the rollout is off', async () => {
            // The flag is off by default here. Opening the stream must take the same-origin Django
            // path (no token mint, no proxy target) — guards against re-adding a debug/non-flag force
            // that would break flag-off streaming (the reported local bug).
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            expect(tasksRunsStreamTokenRetrieve).not.toHaveBeenCalled()
            expect(MockStream.latest().options.proxyTarget).toBeUndefined()
        })

        it('re-mints the read token and retries once on a 401 from the proxy leg', async () => {
            enableProxy()
            ;(tasksRunsStreamTokenRetrieve as jest.Mock).mockResolvedValue({
                token: 'tok-1',
                stream_base_url: 'https://proxy.example',
            })
            // The first open fails with an expired-token 401; the retry must mint a fresh token
            // rather than surface an auth error.
            ;(api.tasks.runs.openStream as jest.Mock).mockRejectedValueOnce({ status: 401 })

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            expect((tasksRunsStreamTokenRetrieve as jest.Mock).mock.calls.length).toBeGreaterThanOrEqual(2)
            expect(logic.values.sseStatus).toEqual('open')
        })

        it('finalizes on the stream-end sentinel without reconnecting, and clears the resume cursor', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()
            const source = MockStream.latest()
            // A live frame seeds the persisted resume cursor.
            await source.emitMessage(notification('_posthog/run_started', {}), '1700-5')
            expect(window.sessionStorage.getItem('posthog-ai:stream-resume:run-1')).toEqual('1700-5')

            const connectionsBefore = MockStream.connections.length
            await source.emitStreamEnd()

            // The sentinel finalizes via a status refetch — no reconnect, and the cursor is dropped so
            // a reload can't try to resume a finished run.
            expect(logic.values.currentRunStatus).toEqual('completed')
            expect(MockStream.connections.length).toEqual(connectionsBefore)
            expect(window.sessionStorage.getItem('posthog-ai:stream-resume:run-1')).toBeNull()
        })
    })
})

// Drain queued microtasks (chained `await`s in async listeners) without relying on timers, so it
// works under both real and fake timers.
async function flushPromises(): Promise<void> {
    for (let i = 0; i < 10; i++) {
        await Promise.resolve()
    }
}
