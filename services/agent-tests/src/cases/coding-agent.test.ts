/**
 * Coding agent — real worker e2e. Drives the full platform path for an
 * in-sandbox coding agent: a real `Worker` claims a seeded session, `runSession`
 * branches to `driveCodingSession`, and the turn runs against a FAKE
 * `CodingSandboxPool` that scripts ACP frames. Everything but the tier-2 sandbox
 * is real (Postgres queue, Redis bus, Kafka logs) — so this asserts the claim →
 * branch → driver → persist → outcome wiring without needing Docker or a model.
 *
 * The real harness path (real image + live gateway) is covered separately by
 * agent-runner/src/loop/coding-supervisor.realharness.test.ts.
 */

import { randomUUID } from 'node:crypto'
import { afterAll, afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
    AgentSession,
    CodingAcquireOpts,
    CodingSandbox,
    CodingSandboxPool,
    EMPTY_USAGE_TOTAL,
    HarnessFrame,
} from '@posthog/agent-shared'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

function sessionUpdate(update: unknown): HarnessFrame {
    return { type: 'notification', notification: { jsonrpc: '2.0', method: 'session/update', params: { update } } }
}
function lifecycle(method: string): HarnessFrame {
    return { type: 'notification', notification: { jsonrpc: '2.0', method, params: {} } }
}

/** Fake tier-2 harness: on each user_message, streams a scripted turn. */
class FakeCodingSandbox implements CodingSandbox {
    onFrame: ((f: HarnessFrame) => void) | null = null
    readonly providerSandboxId = 'fake-container'
    constructor(readonly sessionId: string) {}
    async command(cmd: { method: string }): Promise<{ jsonrpc: '2.0'; id: string; result?: unknown }> {
        if (cmd.method === 'user_message') {
            this.onFrame?.(
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'Listed the files.' } })
            )
            this.onFrame?.(
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't1',
                    _meta: { claudeCode: { toolName: 'Bash', bashCommand: 'ls /tmp/workspace' } },
                })
            )
            this.onFrame?.(lifecycle('_posthog/turn_complete'))
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

class FakeCodingPool implements CodingSandboxPool {
    readonly kind = 'docker-coding' as const
    acquired: string[] = []
    released: string[] = []
    async acquireForSession(opts: CodingAcquireOpts): Promise<CodingSandbox> {
        this.acquired.push(opts.sessionId)
        return new FakeCodingSandbox(opts.sessionId)
    }
    async release(sessionId: string): Promise<void> {
        this.released.push(sessionId)
    }
}

describe('coding agent: real worker e2e', () => {
    let c: Cluster
    let pool: FakeCodingPool

    beforeEach(async () => {
        pool = new FakeCodingPool()
        c = await buildCluster({ codingPool: pool, codingGateway: { baseUrl: 'http://gw', apiKey: 'k', projectId: 1 } })
    })
    afterEach(async () => {
        await c.teardown()
    })
    afterAll(async () => {
        await closeSharedPool()
    })

    it('claims a coding session, branches to the harness, persists the turn, completes', async () => {
        const { application, revision } = await c.deployAgent({
            slug: 'coder',
            spec: {
                model: 'faux/faux',
                sandbox: { trust_profile: 'coding-write', loop_location: 'in_sandbox' },
            },
            files: { 'agent.md': 'You are a coding agent.' },
        })

        const sessionId = randomUUID()
        await c.queue.enqueue({
            id: sessionId,
            application_id: application.id,
            revision_id: revision.id,
            team_id: 1,
            external_key: null,
            idempotency_key: null,
            trigger_metadata: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'list the files in the workspace', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            usage_total: { ...EMPTY_USAGE_TOTAL },
            acl: [],
            pending_elevation_requests: [],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
        } as unknown as AgentSession)

        await c.drain({ iterations: 20 })

        const session = await c.queue.get(sessionId)
        expect(session, 'session should exist').not.toBeNull()
        expect(session!.state).toBe('completed')

        // The harness turn was relayed + persisted into the conversation.
        const assistant = session!.conversation.find((m) => m.role === 'assistant') as
            | { content: { text?: string }[] }
            | undefined
        expect(assistant?.content?.[0]?.text).toBe('Listed the files.')

        // The worker drove the tier-2 pool for this session and released it.
        expect(pool.acquired).toContain(sessionId)
        expect(pool.released).toContain(sessionId)

        // Lifecycle events landed in the (real Kafka) log sink.
        const events = c.logs.forSession(sessionId).map((l) => l.event)
        expect(events).toContain('session_started')
        expect(events).toContain('completed')
    })
})
