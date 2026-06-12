/**
 * Hermetic unit test for the worker-integrated coding driver. Drives
 * `driveCodingSession` against a FAKE `CodingSandboxPool` that scripts ACP
 * frames in response to `user_message`, so the turn loop, event→bus mapping,
 * multi-turn `pending_inputs` drain, persistence, outcome, and shutdown are
 * all covered with no Docker. The real harness path is covered separately by
 * coding-supervisor.realharness.test.ts.
 */

import { describe, expect, it } from 'vitest'

import {
    AgentRevision,
    AgentSession,
    AgentSpecSchema,
    AnalyticsEvent,
    AnalyticsSink,
    CodingAcquireOpts,
    CodingSandbox,
    CodingSandboxPool,
    ConversationMessage,
    HarnessFrame,
    SessionEvent,
    SessionEventBus,
    SessionInputsStore,
    LogSink,
    verifyInferenceProxyToken,
} from '@posthog/agent-shared'

import { driveCodingSession } from './coding-driver'
import type { RunSessionDeps } from './driver'

function su(update: unknown): HarnessFrame {
    return { type: 'notification', notification: { jsonrpc: '2.0', method: 'session/update', params: { update } } }
}
function lifecycle(method: string): HarnessFrame {
    return { type: 'notification', notification: { jsonrpc: '2.0', method, params: {} } }
}

/** Fake harness: on each user_message, streams a scripted turn then completes. */
class FakeCodingSandbox implements CodingSandbox {
    onFrame: ((f: HarnessFrame) => void) | null = null
    constructor(
        readonly sessionId: string,
        private readonly scriptTurn: (n: number) => HarnessFrame[]
    ) {}
    readonly providerSandboxId = 'fake-container'
    readonly sent: string[] = []
    private turn = 0
    async command(cmd: {
        method: string
        params?: unknown
    }): Promise<{ jsonrpc: '2.0'; id: string; result?: unknown }> {
        if (cmd.method === 'user_message') {
            this.sent.push((cmd.params as { content: string }).content)
            this.turn += 1
            for (const f of this.scriptTurn(this.turn)) {
                this.onFrame?.(f)
            }
        }
        return { jsonrpc: '2.0', id: 'x', result: { accepted: true } }
    }
    openEvents(onFrame: (f: HarnessFrame) => void): { close: () => void } {
        this.onFrame = onFrame
        onFrame({ type: 'connected', run_id: this.sessionId })
        return { close: () => undefined }
    }
    async isAlive(): Promise<boolean> {
        return true
    }
    async logs(): Promise<string> {
        return ''
    }
    async destroy(): Promise<void> {}
}

class FakePool implements CodingSandboxPool {
    readonly kind = 'docker-coding' as const
    released: string[] = []
    sandbox: FakeCodingSandbox | null = null
    acquireOpts: CodingAcquireOpts | null = null
    constructor(private readonly scriptTurn: (n: number) => HarnessFrame[]) {}
    async acquireForSession(opts: CodingAcquireOpts): Promise<CodingSandbox> {
        this.acquireOpts = opts
        this.sandbox = new FakeCodingSandbox(opts.sessionId, this.scriptTurn)
        return this.sandbox
    }
    async release(sessionId: string): Promise<void> {
        this.released.push(sessionId)
    }
}

function rev(): AgentRevision {
    const spec = AgentSpecSchema.parse({
        model: 'anthropic/claude-sonnet-4-6',
        sandbox: { loop_location: 'in_sandbox', trust_profile: 'coding-write' },
        limits: { max_turns: 50 },
    })
    return { spec } as unknown as AgentRevision
}

function makeSession(initialUser: string): AgentSession {
    return {
        id: `sess-${Math.random().toString(36).slice(2, 8)}`,
        team_id: 1,
        application_id: 'app-1',
        conversation: [{ role: 'user', content: initialUser, timestamp: 1 }] as ConversationMessage[],
    } as unknown as AgentSession
}

interface Harness {
    events: SessionEvent[]
    analytics: AnalyticsEvent[]
    persists: number
    pending: ConversationMessage[][]
    deps: RunSessionDeps
}

function makeDeps(pool: FakePool, opts: { pending?: ConversationMessage[][]; shutdown?: AbortSignal } = {}): Harness {
    const events: SessionEvent[] = []
    const analytics: AnalyticsEvent[] = []
    const pendingQueue = [...(opts.pending ?? [])]
    const h: Harness = {
        events,
        analytics,
        persists: 0,
        pending: pendingQueue,
        deps: {
            codingPool: pool,
            codingGateway: { baseUrl: 'http://gw', apiKey: 'k', projectId: 1 },
            posthogApiBaseUrl: 'http://api',
            applicationName: 'My coder',
            shutdownSignal: opts.shutdown,
            bus: { publish: async (e: SessionEvent) => void events.push(e) } as unknown as SessionEventBus,
            logs: { write: async () => undefined } as unknown as LogSink,
            analytics: { write: async (es: AnalyticsEvent[]) => void analytics.push(...es) } as AnalyticsSink,
            inputs: {
                drainPendingInputs: async () => pendingQueue.shift() ?? [],
                appendPendingInput: async () => undefined,
            } as unknown as SessionInputsStore,
            onTurnPersist: async () => void (h.persists += 1),
            approvals: {} as never,
        } as unknown as RunSessionDeps,
    }
    return h
}

const kinds = (events: SessionEvent[]): string[] => events.map((e) => e.kind)

describe('driveCodingSession', () => {
    it('runs a single turn: structured transcript (text + tool call + tool result) + usage, completes', async () => {
        const usageFrame = (): ReturnType<typeof lifecycle> => ({
            type: 'notification',
            notification: {
                jsonrpc: '2.0',
                method: '_posthog/usage_update',
                params: {
                    used: { inputTokens: 10, outputTokens: 20, cachedReadTokens: 5, cachedWriteTokens: 3 },
                    cost: 0.01,
                },
            },
        })
        const pool = new FakePool(() => [
            su({ sessionUpdate: 'agent_message_chunk', content: { text: 'Listed the files.' } }),
            su({
                sessionUpdate: 'tool_call_update',
                toolCallId: 't1',
                _meta: { claudeCode: { toolName: 'Bash', bashCommand: 'ls' } },
            }),
            su({
                sessionUpdate: 'tool_call_update',
                toolCallId: 't1',
                status: 'completed',
                rawOutput: { stdout: 'file.txt', isError: false },
            }),
            usageFrame(),
            lifecycle('_posthog/turn_complete'),
        ])
        const h = makeDeps(pool)
        const session = makeSession('list the files')

        const outcome = await driveCodingSession(rev(), session, h.deps)

        expect(outcome).toEqual({ state: 'completed', turns: 1 })
        expect(kinds(h.events)).toEqual([
            'session_started',
            'turn_started',
            'assistant_text_delta',
            'tool_call',
            'tool_result',
            'assistant_text',
            'completed',
        ])

        // Structured transcript: assistant text + toolCall block, then a toolResult.
        const assistant = session.conversation.find((m) => m.role === 'assistant') as {
            content: (
                | { type: 'text'; text: string }
                | { type: 'toolCall'; id: string; name: string; arguments: Record<string, unknown> }
            )[]
        }
        expect(assistant.content).toEqual([
            { type: 'text', text: 'Listed the files.' },
            { type: 'toolCall', id: 't1', name: 'Bash', arguments: { command: 'ls' } },
        ])
        const toolResult = session.conversation.find((m) => m.role === 'toolResult') as {
            toolCallId: string
            toolName: string
            isError: boolean
            content: { text: string }[]
        }
        expect(toolResult).toMatchObject({ toolCallId: 't1', toolName: 'Bash', isError: false })
        expect(toolResult.content[0].text).toBe('file.txt')

        // Usage accumulated into usage_total.
        expect(session.usage_total).toMatchObject({
            tokens_in: 10,
            tokens_out: 20,
            cache_read: 5,
            cache_write: 3,
            cost_total: 0.01,
        })
        expect(h.persists).toBe(1)
        expect(pool.released).toContain(session.id)

        // Analytics: a span for the tool, a generation for the turn, a trace at the end.
        const span = h.analytics.find((e) => e.kind === 'span')
        expect(span).toMatchObject({
            kind: 'span',
            tool_name: 'Bash',
            tool_call_id: 't1',
            input: { command: 'ls' },
            output: 'file.txt',
            is_error: false,
        })
        const generation = h.analytics.find((e) => e.kind === 'generation')
        expect(generation).toMatchObject({
            kind: 'generation',
            input_tokens: 10,
            output_tokens: 20,
            cache_read_tokens: 5,
            cache_write_tokens: 3,
            cost_usd: 0.01,
            stop_reason: 'stop',
        })
        // The span hangs off the turn's generation.
        expect((span as { parent_span_id?: string }).parent_span_id).toBe((generation as { span_id: string }).span_id)
        const trace = h.analytics.find((e) => e.kind === 'trace')
        expect(trace).toMatchObject({ kind: 'trace', trace_name: 'My coder', input_state: 'list the files' })
    })

    it('handles a multi-turn session via drained pending_inputs', async () => {
        const pool = new FakePool((n) => [
            su({ sessionUpdate: 'agent_message_chunk', content: { text: `turn ${n}` } }),
            lifecycle('_posthog/turn_complete'),
        ])
        // After turn 1, a /send lands; after turn 2, nothing.
        const h = makeDeps(pool, {
            pending: [[{ role: 'user', content: 'now do step two', timestamp: 2 }] as ConversationMessage[]],
        })
        const session = makeSession('do step one')

        const outcome = await driveCodingSession(rev(), session, h.deps)

        expect(outcome).toEqual({ state: 'completed', turns: 2 })
        expect(kinds(h.events).filter((k) => k === 'turn_started')).toHaveLength(2)
        expect(session.conversation.filter((m) => m.role === 'assistant')).toHaveLength(2)
        expect(h.persists).toBe(2)
        // Same-invocation turns reach the harness raw — it has its own context.
        expect(pool.sandbox?.sent).toEqual(['do step one', 'now do step two'])
    })

    it('on a follow-up re-claim, runs the pending /send with prior history replayed — not the original prompt', async () => {
        const pool = new FakePool((n) => [
            su({ sessionUpdate: 'agent_message_chunk', content: { text: `reply ${n}` } }),
            lifecycle('_posthog/turn_complete'),
        ])
        // A prior invocation already completed: the conversation ends with an
        // assistant turn, and the new /send sits in pending_inputs. Re-running
        // the trailing *user* message here would replay the original prompt.
        const h = makeDeps(pool, {
            pending: [[{ role: 'user', content: 'do step two', timestamp: 3 }] as ConversationMessage[]],
        })
        const session = makeSession('original prompt')
        session.conversation.push({
            role: 'assistant',
            content: [{ type: 'text', text: 'done step one' }],
            timestamp: 2,
        } as ConversationMessage)

        const outcome = await driveCodingSession(rev(), session, h.deps)

        expect(outcome).toEqual({ state: 'completed', turns: 1 })
        // One send: the new message wrapped in the resume preamble — the fresh
        // harness gets the prior conversation as context, but the original
        // prompt is not replayed as its own turn.
        expect(pool.sandbox?.sent).toHaveLength(1)
        const sent = pool.sandbox!.sent[0]
        expect(sent).toContain('You are resuming a previous conversation')
        expect(sent).toContain('**User**: original prompt')
        expect(sent).toContain('**Assistant**: done step one')
        expect(sent).toContain('The user has sent a new message:\n\ndo step two')
        // Persisted transcript + analytics keep the raw message, not the wrapper.
        expect(session.conversation.filter((m) => m.role === 'user').map((m) => m.content)).toEqual([
            'original prompt',
            'do step two',
        ])
        const generation = h.analytics.find((e) => e.kind === 'generation')
        expect(generation).toMatchObject({ input: [{ role: 'user', content: 'do step two' }] })
        const trace = h.analytics.find((e) => e.kind === 'trace')
        expect(trace).toMatchObject({ input_state: 'do step two' })
    })

    it('on a re-claim, wraps only the first send — later same-invocation turns go raw', async () => {
        const pool = new FakePool((n) => [
            su({ sessionUpdate: 'agent_message_chunk', content: { text: `reply ${n}` } }),
            lifecycle('_posthog/turn_complete'),
        ])
        // Re-claim with a /send queued, then another /send lands after turn 1.
        const h = makeDeps(pool, {
            pending: [
                [{ role: 'user', content: 'do step two', timestamp: 3 }] as ConversationMessage[],
                [{ role: 'user', content: 'do step three', timestamp: 4 }] as ConversationMessage[],
            ],
        })
        const session = makeSession('original prompt')
        session.conversation.push({
            role: 'assistant',
            content: [{ type: 'text', text: 'done step one' }],
            timestamp: 2,
        } as ConversationMessage)

        const outcome = await driveCodingSession(rev(), session, h.deps)

        expect(outcome).toEqual({ state: 'completed', turns: 2 })
        expect(pool.sandbox?.sent).toHaveLength(2)
        expect(pool.sandbox!.sent[0]).toContain('You are resuming a previous conversation')
        expect(pool.sandbox!.sent[1]).toBe('do step three')
    })

    it('fails the turn when the harness streams an error', async () => {
        const pool = new FakePool(() => [
            {
                type: 'notification',
                notification: {
                    jsonrpc: '2.0',
                    id: 2,
                    method: 'session/prompt',
                    error: { code: -32603, message: 'API Error: 400 unknown model' },
                },
            },
            lifecycle('_posthog/turn_complete'),
        ])
        const h = makeDeps(pool)
        const outcome = await driveCodingSession(rev(), makeSession('go'), h.deps)
        expect(outcome.state).toBe('failed')
        if (outcome.state === 'failed') {
            expect(outcome.reason).toContain('unknown model')
        }
        expect(kinds(h.events)).toContain('failed')
    })

    it('suspends cleanly when the shutdown signal is already aborted', async () => {
        const pool = new FakePool(() => [lifecycle('_posthog/turn_complete')])
        const controller = new AbortController()
        controller.abort()
        const h = makeDeps(pool, { shutdown: controller.signal })
        const outcome = await driveCodingSession(rev(), makeSession('go'), h.deps)
        expect(outcome).toEqual({ state: 'suspended', reason: 'shutdown', turns: 0 })
    })

    it('with an inference proxy configured, the harness gets a session token — never the gateway key', async () => {
        const pool = new FakePool(() => [
            su({ sessionUpdate: 'agent_message_chunk', content: { text: 'ok' } }),
            lifecycle('_posthog/turn_complete'),
        ])
        const h = makeDeps(pool)
        ;(h.deps as { codingGateway?: unknown }).codingGateway = {
            baseUrl: 'http://ingress:3210/inference',
            projectId: 1,
            inferenceProxy: { signingKey: 'test-signing-key' },
        }
        const session = makeSession('go')

        const outcome = await driveCodingSession(rev(), session, h.deps)

        expect(outcome).toEqual({ state: 'completed', turns: 1 })
        const launch = pool.acquireOpts!.launch
        expect(launch.modelBaseUrl).toBe('http://ingress:3210/inference')
        // The launch carries a session-bound capability token, not a credential.
        const claims = await verifyInferenceProxyToken({ token: launch.apiKey!, signingKey: 'test-signing-key' })
        expect(claims.sessionId).toBe(session.id)
    })

    it('without a proxy, the legacy direct-gateway key still flows (interim)', async () => {
        const pool = new FakePool(() => [
            su({ sessionUpdate: 'agent_message_chunk', content: { text: 'ok' } }),
            lifecycle('_posthog/turn_complete'),
        ])
        const h = makeDeps(pool)
        await driveCodingSession(rev(), makeSession('go'), h.deps)
        expect(pool.acquireOpts!.launch).toMatchObject({ modelBaseUrl: 'http://gw', apiKey: 'k' })
    })

    it('fails closed when no coding pool is wired', async () => {
        const h = makeDeps(new FakePool(() => []))
        ;(h.deps as { codingPool?: unknown }).codingPool = undefined
        const outcome = await driveCodingSession(rev(), makeSession('go'), h.deps)
        expect(outcome).toMatchObject({ state: 'failed', reason: 'coding_pool_unavailable' })
    })
})
