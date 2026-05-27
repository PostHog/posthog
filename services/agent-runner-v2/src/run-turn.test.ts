import {
    AgentRevision,
    AgentSession,
    AgentSpecSchema,
    InProcessSandboxPool,
    MemoryBundleStore,
} from '@posthog/agent-shared-v2'
import { setPosthogInternalClient } from '@posthog/agent-tools'

import { endTurn, errorTurn, FauxPiClient, lengthCappedTurn, toolCall, toolUseTurn } from './faux-pi-client'
import { runSession } from './run-turn'

function makeRev(spec: Partial<Parameters<typeof AgentSpecSchema.parse>[0]> = {}): AgentRevision {
    return {
        id: 'rev1',
        application_id: 'app',
        parent_revision_id: null,
        created_by: 'u',
        created_at: '2026-05-27',
        state: 'live',
        bundle_uri: 's3://',
        bundle_sha256: null,
        spec: AgentSpecSchema.parse({ model: 'faux/test', ...spec }),
    }
}

function makeSession(): AgentSession {
    return {
        id: 'sess1',
        application_id: 'app',
        revision_id: 'rev1',
        team_id: 1,
        external_key: null,
        state: 'running',
        conversation: [{ role: 'user', content: 'hello', timestamp: Date.now() }],
        pending_inputs: [],
        created_at: '2026-05-27',
        updated_at: '2026-05-27',
    }
}

describe('runSession', () => {
    beforeEach(() => {
        setPosthogInternalClient({
            async runHogql() {
                return { rows: [], columns: [] }
            },
            async searchPersons() {
                return { persons: [] }
            },
        })
    })

    it('completes when the model returns stopReason=stop', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'you are a bot')
        const pi = new FauxPiClient([endTurn('hi back')])
        const rev = makeRev()
        const session = makeSession()
        const out = await runSession(rev, session, { pi, bundle, sandbox: null, integrations: {}, secrets: {} })
        expect(out.state).toBe('completed')
        expect(out.turns).toBe(1)
        expect(session.conversation).toHaveLength(2)
    })

    it('dispatches a native tool call, then completes', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([
            toolUseTurn([toolCall('posthog.query.v1', { query: 'select 1' }, 'tc_1')]),
            endTurn('query ran'),
        ])
        const rev = makeRev({ tools: [{ kind: 'native', id: 'posthog.query.v1' }] })
        const session = makeSession()
        const out = await runSession(rev, session, { pi, bundle, sandbox: null, integrations: {}, secrets: {} })
        expect(out.state).toBe('completed')
        expect(out.turns).toBe(2)
        // user + assistant(tool_use) + toolResult + assistant(final)
        expect(session.conversation).toHaveLength(4)
        const toolResult = session.conversation[2] as { role: 'toolResult'; toolCallId: string }
        expect(toolResult.role).toBe('toolResult')
        expect(toolResult.toolCallId).toBe('tc_1')
    })

    it('returns state=waiting on meta.ask_for_input.v1', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([toolUseTurn([toolCall('meta.ask_for_input.v1', { prompt: 'Continue?' })])])
        const out = await runSession(makeRev(), makeSession(), {
            pi,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('waiting')
        expect(out.state === 'waiting' && out.prompt).toBe('Continue?')
    })

    it('returns state=completed on meta.end_session.v1 with summary', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([toolUseTurn([toolCall('meta.end_session.v1', { summary: 'all done' })])])
        const out = await runSession(makeRev(), makeSession(), {
            pi,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('completed')
        expect(out.state === 'completed' && out.summary).toBe('all done')
    })

    it('returns state=failed when max_turns exhausted', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient(
            Array(5)
                .fill(null)
                .map(() => toolUseTurn([toolCall('posthog.query.v1', { query: 'x' })]))
        )
        const rev = makeRev({
            tools: [{ kind: 'native', id: 'posthog.query.v1' }],
            limits: { max_turns: 3, max_tool_calls: 10, max_wall_seconds: 60 },
        })
        const out = await runSession(rev, makeSession(), {
            pi,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('failed')
        expect(out.state === 'failed' && out.reason).toBe('max_turns_exceeded')
    })

    it('returns state=failed when model returns stopReason=length', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([lengthCappedTurn()])
        const out = await runSession(makeRev(), makeSession(), {
            pi,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('failed')
        expect(out.state === 'failed' && out.reason).toBe('max_tokens')
    })

    it('returns state=failed when model returns stopReason=error', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([errorTurn('rate_limit')])
        const out = await runSession(makeRev(), makeSession(), {
            pi,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('failed')
        expect(out.state === 'failed' && out.reason).toBe('rate_limit')
    })

    it('runs a custom tool through a sandbox', async () => {
        const COMPILED = `
            module.exports = {
                id: "echo",
                actions: { default: (args) => ({ echoed: args.x }) },
            }
        `
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        await bundle.write('rev1', 'tools/echo/compiled.js', COMPILED)
        await bundle.write('rev1', 'tools/echo/schema.json', JSON.stringify({ description: 'echo' }))
        const pool = new InProcessSandboxPool()
        const sandbox = await pool.acquireForSession({
            sessionId: 'sess1',
            teamId: 1,
            tools: [{ id: 'echo', compiledJs: COMPILED, schemaJson: {} }],
            nonces: {},
        })
        const pi = new FauxPiClient([toolUseTurn([toolCall('echo', { x: 42 })]), endTurn('done')])
        const rev = makeRev({ tools: [{ kind: 'custom', id: 'echo', path: 'tools/echo/' }] })
        const out = await runSession(rev, makeSession(), {
            pi,
            bundle,
            sandbox,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('completed')
        await pool.release('sess1')
    })

    it('propagates tool errors via toolResult.isError=true', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([toolUseTurn([toolCall('ghost-tool', {})]), endTurn('ok recovered')])
        const rev = makeRev()
        const session = makeSession()
        await runSession(rev, session, { pi, bundle, sandbox: null, integrations: {}, secrets: {} })
        const tr = session.conversation[2] as { role: 'toolResult'; isError: boolean }
        expect(tr.role).toBe('toolResult')
        expect(tr.isError).toBe(true)
    })

    it('drains pending_inputs into conversation at turn start', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([endTurn('ok')])
        const session = makeSession()
        session.pending_inputs = [{ role: 'user', content: 'queued follow-up', timestamp: Date.now() }]
        const out = await runSession(makeRev(), session, {
            pi,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('completed')
        expect(session.pending_inputs).toHaveLength(0)
        // original user + drained user + assistant
        expect(session.conversation).toHaveLength(3)
        const drained = session.conversation[1] as { role: 'user'; content: string }
        expect(drained.content).toBe('queued follow-up')
    })

    it('suspends to state=suspended when shutdown signal aborts before turn', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([endTurn('would never run')])
        const controller = new AbortController()
        controller.abort()
        const out = await runSession(makeRev(), makeSession(), {
            pi,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
            shutdownSignal: controller.signal,
        })
        expect(out.state).toBe('suspended')
        expect(out.turns).toBe(0)
    })

    it('suspends between turns when shutdown signal aborts mid-loop', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const controller = new AbortController()
        const pi = new FauxPiClient([
            (() => {
                // Abort right before returning — the next loop iteration sees it.
                queueMicrotask(() => controller.abort())
                return toolUseTurn([toolCall('posthog.query.v1', { query: 'x' })])
            }) as never,
            endTurn('would never run'),
        ])
        const rev = makeRev({ tools: [{ kind: 'native', id: 'posthog.query.v1' }] })
        const out = await runSession(rev, makeSession(), {
            pi,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
            shutdownSignal: controller.signal,
        })
        expect(out.state).toBe('suspended')
    })

    it('calls onTurnPersist after each turn', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([toolUseTurn([toolCall('posthog.query.v1', { query: 'x' })]), endTurn('done')])
        const persisted: number[] = []
        const rev = makeRev({ tools: [{ kind: 'native', id: 'posthog.query.v1' }] })
        const session = makeSession()
        await runSession(rev, session, {
            pi,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
            onTurnPersist: async (s) => {
                persisted.push(s.conversation.length)
            },
        })
        // At least one persist per turn (assistant message + post-tool dispatch)
        expect(persisted.length).toBeGreaterThanOrEqual(2)
    })
})
