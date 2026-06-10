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
    CodingAcquireOpts,
    CodingSandbox,
    CodingSandboxPool,
    ConversationMessage,
    HarnessFrame,
    SessionEvent,
    SessionEventBus,
    SessionInputsStore,
    LogSink,
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
    private turn = 0
    async command(cmd: {
        method: string
        params?: unknown
    }): Promise<{ jsonrpc: '2.0'; id: string; result?: unknown }> {
        if (cmd.method === 'user_message') {
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
    async destroy(): Promise<void> {}
}

class FakePool implements CodingSandboxPool {
    readonly kind = 'docker-coding' as const
    released: string[] = []
    sandbox: FakeCodingSandbox | null = null
    constructor(private readonly scriptTurn: (n: number) => HarnessFrame[]) {}
    async acquireForSession(opts: CodingAcquireOpts): Promise<CodingSandbox> {
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
    persists: number
    pending: ConversationMessage[][]
    deps: RunSessionDeps
}

function makeDeps(pool: FakePool, opts: { pending?: ConversationMessage[][]; shutdown?: AbortSignal } = {}): Harness {
    const events: SessionEvent[] = []
    const pendingQueue = [...(opts.pending ?? [])]
    const h: Harness = {
        events,
        persists: 0,
        pending: pendingQueue,
        deps: {
            codingPool: pool,
            codingGateway: { baseUrl: 'http://gw', apiKey: 'k', projectId: 1 },
            posthogApiBaseUrl: 'http://api',
            shutdownSignal: opts.shutdown,
            bus: { publish: async (e: SessionEvent) => void events.push(e) } as unknown as SessionEventBus,
            logs: { write: async () => undefined } as unknown as LogSink,
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
    it('runs a single turn: emits lifecycle, captures assistant text + tool call, persists, completes', async () => {
        const pool = new FakePool(() => [
            su({ sessionUpdate: 'agent_message_chunk', content: { text: 'Hello from harness' } }),
            su({
                sessionUpdate: 'tool_call_update',
                toolCallId: 't1',
                _meta: { claudeCode: { toolName: 'Bash', bashCommand: 'ls' } },
            }),
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
            'assistant_text',
            'completed',
        ])
        const assistant = session.conversation.find((m) => m.role === 'assistant') as { content: { text: string }[] }
        expect(assistant.content[0].text).toBe('Hello from harness')
        expect(h.persists).toBe(1)
        expect(pool.released).toContain(session.id)
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

    it('fails closed when no coding pool is wired', async () => {
        const h = makeDeps(new FakePool(() => []))
        ;(h.deps as { codingPool?: unknown }).codingPool = undefined
        const outcome = await driveCodingSession(rev(), makeSession('go'), h.deps)
        expect(outcome).toMatchObject({ state: 'failed', reason: 'coding_pool_unavailable' })
    })
})
