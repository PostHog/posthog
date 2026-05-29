import type { Model } from '@earendil-works/pi-ai'

import {
    AgentRevision,
    AgentSession,
    AgentSpecSchema,
    EMPTY_USAGE_TOTAL,
    InMemoryAnalyticsSink,
    InProcessSandboxPool,
    MemoryBundleStore,
} from '@posthog/agent-shared'
import { setPosthogInternalClient } from '@posthog/agent-tools'

import {
    endTurn,
    errorTurn,
    FauxPiClient,
    lengthCappedTurn,
    toolCall,
    toolUseTurn,
    withUsage,
} from '../models/faux-pi-client'
import { runSession } from './run-turn'

// FauxPiClient ignores the model argument so a structural stub is fine.
const FAUX_MODEL = { id: 'stub', name: 'stub', api: 'faux', provider: 'faux' } as unknown as Model<string>

function makeRev(spec: Partial<Parameters<typeof AgentSpecSchema.parse>[0]> = {}): AgentRevision {
    return {
        id: 'rev1',
        application_id: 'app',
        parent_revision_id: null,
        created_by_id: null,
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
        principal: null,
        retry_count: 0,
        usage_total: { ...EMPTY_USAGE_TOTAL },
        acl: [],
        pending_elevation_requests: [],
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
        const out = await runSession(rev, session, {
            pi,
            model: FAUX_MODEL,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('completed')
        expect(out.turns).toBe(1)
        expect(session.conversation).toHaveLength(2)
    })

    it('dispatches a native tool call, then completes', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([
            toolUseTurn([toolCall('@posthog/query', { query: 'select 1' }, 'tc_1')]),
            endTurn('query ran'),
        ])
        const rev = makeRev({ tools: [{ kind: 'native', id: '@posthog/query' }] })
        const session = makeSession()
        const out = await runSession(rev, session, {
            pi,
            model: FAUX_MODEL,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('completed')
        expect(out.turns).toBe(2)
        // user + assistant(tool_use) + toolResult + assistant(final)
        expect(session.conversation).toHaveLength(4)
        const toolResult = session.conversation[2] as { role: 'toolResult'; toolCallId: string }
        expect(toolResult.role).toBe('toolResult')
        expect(toolResult.toolCallId).toBe('tc_1')
    })

    it('returns state=completed on @posthog/meta-ask-for-input (no longer parks)', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([toolUseTurn([toolCall('@posthog/meta-ask-for-input', { prompt: 'Continue?' })])])
        const out = await runSession(makeRev(), makeSession(), {
            pi,
            model: FAUX_MODEL,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        // Session-restart redesign: ask_for_input ends the turn (state=completed,
        // open). The prompt is surfaced via the `ask_for_input` bus event for
        // UI focus hints; it doesn't appear on the RunOutcome.
        expect(out.state).toBe('completed')
    })

    it('returns state=closed on @posthog/meta-end-session with summary', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([toolUseTurn([toolCall('@posthog/meta-end-session', { summary: 'all done' })])])
        const out = await runSession(makeRev(), makeSession(), {
            pi,
            model: FAUX_MODEL,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('closed')
        expect(out.state === 'closed' && out.summary).toBe('all done')
    })

    it('returns state=completed on @posthog/meta-end-turn', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([toolUseTurn([toolCall('@posthog/meta-end-turn', {})])])
        const out = await runSession(makeRev(), makeSession(), {
            pi,
            model: FAUX_MODEL,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(out.state).toBe('completed')
    })

    it('returns state=failed when max_turns exhausted', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient(
            Array(5)
                .fill(null)
                .map(() => toolUseTurn([toolCall('@posthog/query', { query: 'x' })]))
        )
        const rev = makeRev({
            tools: [{ kind: 'native', id: '@posthog/query' }],
            limits: { max_turns: 3, max_tool_calls: 10, max_wall_seconds: 60 },
        })
        const out = await runSession(rev, makeSession(), {
            pi,
            model: FAUX_MODEL,
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
            model: FAUX_MODEL,
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
            model: FAUX_MODEL,
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
            model: FAUX_MODEL,
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
        await runSession(rev, session, { pi, model: FAUX_MODEL, bundle, sandbox: null, integrations: {}, secrets: {} })
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
            model: FAUX_MODEL,
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
            model: FAUX_MODEL,
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
                return toolUseTurn([toolCall('@posthog/query', { query: 'x' })])
            }) as never,
            endTurn('would never run'),
        ])
        const rev = makeRev({ tools: [{ kind: 'native', id: '@posthog/query' }] })
        const out = await runSession(rev, makeSession(), {
            pi,
            model: FAUX_MODEL,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
            shutdownSignal: controller.signal,
        })
        expect(out.state).toBe('suspended')
    })

    it('forwards spec.reasoning to PiClient.stream()', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([endTurn('ok')])
        const rev = makeRev({ reasoning: 'high' })
        const session = makeSession()
        await runSession(rev, session, {
            pi,
            model: FAUX_MODEL,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        // The runner switched from invoke() to stream() in v1 — assertions
        // moved to streamCalls[] accordingly.
        expect(pi.streamCalls).toHaveLength(1)
        expect(pi.streamCalls[0].opts?.reasoning).toBe('high')
    })

    it('omits reasoning when spec.reasoning is not set (provider default)', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([endTurn('ok')])
        const rev = makeRev() // no reasoning field
        const session = makeSession()
        await runSession(rev, session, {
            pi,
            model: FAUX_MODEL,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(pi.streamCalls[0].opts?.reasoning).toBeUndefined()
    })

    it('accumulates session.usage_total across turns', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([
            withUsage(toolUseTurn([toolCall('@posthog/query', { query: 'x' })]), {
                input: 100,
                output: 20,
                cacheRead: 5,
                cacheWrite: 3,
                totalTokens: 128,
                cost: { input: 0.001, output: 0.0002, cacheRead: 0.00005, cacheWrite: 0.00003, total: 0.00128 },
            }),
            withUsage(endTurn('done'), {
                input: 50,
                output: 10,
                cacheRead: 0,
                cacheWrite: 0,
                totalTokens: 60,
                cost: { input: 0.0005, output: 0.0001, cacheRead: 0, cacheWrite: 0, total: 0.0006 },
            }),
        ])
        const rev = makeRev({ tools: [{ kind: 'native', id: '@posthog/query' }] })
        const session = makeSession()
        await runSession(rev, session, {
            pi,
            model: FAUX_MODEL,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
        })
        expect(session.usage_total.tokens_in).toBe(150)
        expect(session.usage_total.tokens_out).toBe(30)
        expect(session.usage_total.cache_read).toBe(5)
        expect(session.usage_total.cache_write).toBe(3)
        expect(session.usage_total.cost_total).toBeCloseTo(0.00188, 10)
    })

    it('drops cost but keeps tokens when useGatewayCost is true', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([
            withUsage(endTurn('done'), {
                input: 100,
                output: 20,
                cacheRead: 0,
                cacheWrite: 0,
                totalTokens: 120,
                cost: { input: 999, output: 999, cacheRead: 0, cacheWrite: 0, total: 1998 },
            }),
        ])
        const session = makeSession()
        await runSession(makeRev(), session, {
            pi,
            model: FAUX_MODEL,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
            useGatewayCost: true,
        })
        expect(session.usage_total.tokens_in).toBe(100)
        expect(session.usage_total.tokens_out).toBe(20)
        expect(session.usage_total.cost_total).toBe(0)
    })

    it('calls onTurnPersist after each turn', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([toolUseTurn([toolCall('@posthog/query', { query: 'x' })]), endTurn('done')])
        const persisted: number[] = []
        const rev = makeRev({ tools: [{ kind: 'native', id: '@posthog/query' }] })
        const session = makeSession()
        await runSession(rev, session, {
            pi,
            model: FAUX_MODEL,
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

    it('emits one $ai_generation per turn + one $ai_span per tool call', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([
            withUsage(toolUseTurn([toolCall('@posthog/query', { query: 'x' }, 'tc_1')]), {
                input: 100,
                output: 20,
                cacheRead: 0,
                cacheWrite: 0,
                totalTokens: 120,
                cost: { input: 0.001, output: 0.0002, cacheRead: 0, cacheWrite: 0, total: 0.0012 },
            }),
            withUsage(endTurn('done'), {
                input: 50,
                output: 10,
                cacheRead: 0,
                cacheWrite: 0,
                totalTokens: 60,
                cost: { input: 0.0005, output: 0.0001, cacheRead: 0, cacheWrite: 0, total: 0.0006 },
            }),
        ])
        const analytics = new InMemoryAnalyticsSink()
        const rev = makeRev({ tools: [{ kind: 'native', id: '@posthog/query' }] })
        const session = makeSession()
        await runSession(rev, session, {
            pi,
            model: FAUX_MODEL,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
            analytics,
        })
        const generations = analytics.generations(session.id)
        const spans = analytics.spans(session.id)
        expect(generations).toHaveLength(2)
        expect(spans).toHaveLength(1)
        // Trace + span ids chain consistently — span parent matches the generation that produced the toolCall.
        expect(spans[0].parent_span_id).toBe(generations[0].span_id)
        // Per-turn token counts are passed through.
        expect(generations[0].input_tokens).toBe(100)
        expect(generations[1].input_tokens).toBe(50)
        // Tool span carries the original tool name (not the provider-safe form).
        expect(spans[0].tool_name).toBe('@posthog/query')
        expect(spans[0].tool_call_id).toBe('tc_1')
    })

    it('drops cost_usd on the gateway path while keeping token counts', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([
            withUsage(endTurn('done'), {
                input: 100,
                output: 20,
                cacheRead: 0,
                cacheWrite: 0,
                totalTokens: 120,
                cost: { input: 999, output: 999, cacheRead: 0, cacheWrite: 0, total: 1998 },
            }),
        ])
        const analytics = new InMemoryAnalyticsSink()
        await runSession(makeRev(), makeSession(), {
            pi,
            model: FAUX_MODEL,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
            analytics,
            useGatewayCost: true,
        })
        const [gen] = analytics.generations()
        expect(gen.input_tokens).toBe(100)
        expect(gen.output_tokens).toBe(20)
        expect(gen.cost_usd).toBeUndefined()
    })

    it('emits assistant_text_delta events through the SSE bus during streaming turns', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([endTurn('streamed reply text')])
        const { MemorySessionEventBus } = await import('@posthog/agent-shared')
        const bus = new MemorySessionEventBus()
        const session = makeSession()
        const received: { kind: string; data: Record<string, unknown> }[] = []
        const unsub = bus.subscribe(session.id, (e) => received.push({ kind: e.kind, data: e.data }))
        await runSession(makeRev(), session, {
            pi,
            model: FAUX_MODEL,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
            bus,
        })
        unsub()
        const deltaTexts = received.filter((e) => e.kind === 'assistant_text_delta').map((e) => e.data.text as string)
        expect(deltaTexts).toEqual(['streamed', 'reply', 'text'])
        // The full-text `assistant_text` still fires at turn end for non-
        // streaming consumers.
        expect(received.some((e) => e.kind === 'assistant_text')).toBe(true)
    })

    it('records a failed $ai_generation when pi.invoke throws', async () => {
        const bundle = new MemoryBundleStore()
        await bundle.write('rev1', 'agent.md', 'x')
        const pi = new FauxPiClient([
            (() => {
                throw new Error('rate_limit')
            }) as never,
        ])
        const analytics = new InMemoryAnalyticsSink()
        const out = await runSession(makeRev(), makeSession(), {
            pi,
            model: FAUX_MODEL,
            bundle,
            sandbox: null,
            integrations: {},
            secrets: {},
            analytics,
        })
        expect(out.state).toBe('failed')
        const [gen] = analytics.generations()
        expect(gen.is_error).toBe(true)
        expect(gen.error).toBe('rate_limit')
    })
})
