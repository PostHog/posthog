import {
    type AssistantMessage,
    fauxAssistantMessage,
    fauxToolCall,
    type Model,
    registerFauxProvider,
    type ToolCall,
} from '@earendil-works/pi-ai'
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js'
import { z } from 'zod'

import {
    AgentSession,
    AgentSpecSchema,
    EMPTY_USAGE_TOTAL,
    InMemoryLogSink,
    InProcessSandboxPool,
    MemoryBundleStore,
    MemoryRevisionStore,
    MemorySessionQueue,
    SecretBroker,
} from '@posthog/agent-shared'
import { setPosthogInternalClient } from '@posthog/agent-tools'

import type { McpTransportFactory } from '../loop/mcp-clients'
import { Worker } from './worker'

// The driver streams through pi-ai's registered faux provider (the same surface
// the e2e harness uses), so the worker is exercised via `resolveModel` returning
// a faux Model armed with a script — not an injected client.
let fauxHandle: ReturnType<typeof registerFauxProvider> | undefined
function fauxModel(script: Array<AssistantMessage | (() => AssistantMessage)>): Model<string> {
    if (!fauxHandle) {
        fauxHandle = registerFauxProvider({ api: 'faux', provider: 'faux', models: [{ id: 'faux' }] })
    }
    fauxHandle.setResponses(script.map((t) => (typeof t === 'function' ? () => t() : t)))
    return fauxHandle.getModel() as Model<string>
}
const endTurn = (text: string): AssistantMessage => fauxAssistantMessage(text, { stopReason: 'stop' })
const toolUseTurn = (calls: ToolCall[]): AssistantMessage => fauxAssistantMessage(calls, { stopReason: 'toolUse' })
const toolCall = (name: string, args: Record<string, unknown> = {}): ToolCall => fauxToolCall(name, args)

describe('Worker', () => {
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

    it('claims a session, runs it, marks it completed', async () => {
        const revisions = new MemoryRevisionStore()
        const bundle = new MemoryBundleStore()
        const queue = new MemorySessionQueue()

        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'faux/test' }),
        })
        await bundle.write(rev.id, 'agent.md', 'you are a bot')

        const session: AgentSession = {
            id: 'sess1',
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            idempotency_key: null,
            trigger_metadata: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'hello', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            acl: [],
            pending_elevation_requests: [],
            failure_reason: null,
            usage_total: { ...EMPTY_USAGE_TOTAL },
            created_at: '2026-05-27',
            updated_at: '2026-05-27',
        }
        await queue.enqueue(session)

        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
            resolveModel: () => fauxModel([endTurn('hi back')]),
        })

        await worker.loop({ iterations: 1, claimTimeoutMs: 10 })
        const after = await queue.get('sess1')
        expect(after!.state).toBe('completed')
    })

    it('session with custom tool acquires + releases the sandbox', async () => {
        const revisions = new MemoryRevisionStore()
        const bundle = new MemoryBundleStore()
        const queue = new MemorySessionQueue()
        const COMPILED = `
            module.exports = {
                id: "noop",
                actions: { default: () => ({ ok: true }) },
            }
        `

        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({
                model: 'faux/test',
                tools: [{ kind: 'custom', id: 'noop', path: 'tools/noop/' }],
            }),
        })
        await bundle.write(rev.id, 'agent.md', 'x')
        await bundle.write(rev.id, 'tools/noop/compiled.js', COMPILED)
        await bundle.write(rev.id, 'tools/noop/schema.json', JSON.stringify({ description: 'noop' }))

        const session: AgentSession = {
            id: 'sess2',
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            idempotency_key: null,
            trigger_metadata: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            acl: [],
            pending_elevation_requests: [],
            failure_reason: null,
            usage_total: { ...EMPTY_USAGE_TOTAL },
            created_at: '2026-05-27',
            updated_at: '2026-05-27',
        }
        await queue.enqueue(session)

        const pool = new InProcessSandboxPool()
        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: pool,
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({ ACME_KEY: 'topsecret' }),
            resolveModel: () => fauxModel([toolUseTurn([toolCall('noop', {})]), endTurn('done')]),
        })

        await worker.loop({ iterations: 1, claimTimeoutMs: 10 })
        const after = await queue.get('sess2')
        expect(after!.state).toBe('completed')
    })

    it('opens spec.mcps[] at session start, dispatches a remote tool, closes on finish', async () => {
        // End-to-end shape: spec declares an MCP, the worker calls
        // `openMcpClients` via the injected transport factory (paired with an
        // in-process `McpServer`), the faux model invokes the prefixed tool,
        // the result lands in `session.conversation`, and the transport pair
        // is closed in the worker's `finally`.
        const revisions = new MemoryRevisionStore()
        const bundle = new MemoryBundleStore()
        const queue = new MemorySessionQueue()

        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({
                model: 'faux/test',
                mcps: [{ id: 'echo', url: 'https://example.com/echo' }],
            }),
        })
        await bundle.write(rev.id, 'agent.md', 'you are a bot')

        const session: AgentSession = {
            id: 'sess_mcp',
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            idempotency_key: null,
            trigger_metadata: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'say hi', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            acl: [],
            pending_elevation_requests: [],
            failure_reason: null,
            usage_total: { ...EMPTY_USAGE_TOTAL },
            created_at: '2026-05-27',
            updated_at: '2026-05-27',
        }
        await queue.enqueue(session)

        // Track whether the server-side transport got a close call — proves
        // the worker's `finally` ran. Each connect builds a fresh pair so
        // multiple sessions in the same suite stay isolated.
        const serverClosed = { count: 0 }
        const echoCalls: Array<{ msg: string }> = []
        const factory: McpTransportFactory = (): Transport => {
            const server = new McpServer({ name: 'echo-mcp', version: '1.0.0' })
            server.registerTool(
                'echo',
                {
                    title: 'Echo',
                    description: 'Echo input back.',
                    inputSchema: { msg: z.string() },
                },
                async ({ msg }) => {
                    echoCalls.push({ msg })
                    return { content: [{ type: 'text' as const, text: msg }] }
                }
            )
            const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
            const originalClose = serverTransport.close?.bind(serverTransport)
            serverTransport.close = async () => {
                serverClosed.count++
                await originalClose?.()
            }
            void server.server.connect(serverTransport)
            return clientTransport
        }

        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
            resolveModel: () =>
                fauxModel([toolUseTurn([toolCall('echo__echo', { msg: 'hi there' })]), endTurn('done')]),
            mcpTransportFactory: factory,
        })

        await worker.loop({ iterations: 1, claimTimeoutMs: 10 })
        const after = await queue.get('sess_mcp')
        expect(after!.state).toBe('completed')
        expect(echoCalls).toEqual([{ msg: 'hi there' }])
        // The transport pair is closed via the worker's `finally`. The
        // batched closer runs `client.close()`, which terminates the
        // paired server transport — we assert the count is ≥1 rather
        // than == to tolerate the SDK calling close again on its own
        // teardown path.
        expect(serverClosed.count).toBeGreaterThanOrEqual(1)
    })

    it('shutdown signal re-queues an in-flight session as queued for handoff', async () => {
        const revisions = new MemoryRevisionStore()
        const bundle = new MemoryBundleStore()
        const queue = new MemorySessionQueue()

        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({
                model: 'faux/test',
                tools: [{ kind: 'native', id: '@posthog/query' }],
            }),
        })
        await bundle.write(rev.id, 'agent.md', 'x')

        const session: AgentSession = {
            id: 'sess3',
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            idempotency_key: null,
            trigger_metadata: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            acl: [],
            pending_elevation_requests: [],
            failure_reason: null,
            usage_total: { ...EMPTY_USAGE_TOTAL },
            created_at: '2026-05-27',
            updated_at: '2026-05-27',
        }
        await queue.enqueue(session)

        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
            resolveModel: () =>
                fauxModel([
                    (() => {
                        // Signal shutdown after the first turn so the next iteration sees it.
                        queueMicrotask(() => void worker.stop())
                        return toolUseTurn([toolCall('@posthog/query', { query: 'x' })])
                    }) as () => AssistantMessage,
                    endTurn('never reaches here'),
                ]),
        })

        await worker.loop({ iterations: 1, claimTimeoutMs: 10 })
        const after = await queue.get('sess3')
        // After shutdown mid-loop, session is re-queued for sibling pickup.
        expect(after!.state).toBe('queued')
        // Conversation persists across the handoff.
        expect(after!.conversation.length).toBeGreaterThan(1)
    })

    // Regression: a malformed revision.spec used to throw a ZodError out of
    // PgRevisionStore.getRevision(), which propagated through runOne (then
    // outside the try/catch) and crashed the worker loop. The boundary now
    // sits at the top of runOne, so the bad session is marked failed and a
    // sibling can keep being processed.
    it('runOne catches errors from revisions.getRevision and fails the session', async () => {
        const revisions = new MemoryRevisionStore()
        const bundle = new MemoryBundleStore()
        const queue = new MemorySessionQueue()
        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const session: AgentSession = {
            id: 'sess-bad-rev',
            application_id: app.id,
            revision_id: 'rev-does-not-exist-and-throws',
            team_id: 1,
            external_key: null,
            idempotency_key: null,
            trigger_metadata: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            acl: [],
            pending_elevation_requests: [],
            failure_reason: null,
            usage_total: { ...EMPTY_USAGE_TOTAL },
            created_at: '2026-05-27',
            updated_at: '2026-05-27',
        }
        await queue.enqueue(session)

        // Stub getRevision to throw the kind of ZodError PgRevisionStore would
        // raise on a malformed spec column.
        const throwingRevisions = {
            ...revisions,
            getRevision: async () => {
                throw new Error('AgentSpecSchema parse error')
            },
        } as unknown as typeof revisions

        const worker = new Worker({
            queue,
            revisions: throwingRevisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
            resolveModel: () => fauxModel([endTurn('would never run')]),
        })

        // The loop should not throw — runOne owns the boundary.
        await expect(worker.loop({ iterations: 1, claimTimeoutMs: 10 })).resolves.toBeUndefined()
        const after = await queue.get('sess-bad-rev')
        expect(after!.state).toBe('failed')
    })

    // The pre-flight inside `runOne` (revision load, secrets, integrations,
    // sandbox acquire, custom-tool bundle reads) sits under one try/catch.
    // Each failure mode below would crash the worker loop pre-fix; the
    // boundary now fails just the one session.
    type FailureCase = {
        name: string
        withCustomTool: boolean
        overrides: (failingPool: InProcessSandboxPool) => Partial<{
            resolveSecrets: () => Promise<Record<string, string>>
            resolveIntegrations: () => Promise<Record<string, never>>
            sandboxes: InProcessSandboxPool
            resolveModel: (specModel: string) => never
        }>
    }
    const PREFLIGHT_CASES: FailureCase[] = [
        {
            name: 'resolveSecrets throws',
            withCustomTool: false,
            overrides: () => ({
                resolveSecrets: async () => {
                    throw new Error('decryption failed')
                },
            }),
        },
        {
            name: 'resolveIntegrations throws',
            withCustomTool: false,
            overrides: () => ({
                resolveIntegrations: async () => {
                    throw new Error('integrations service unavailable')
                },
            }),
        },
        {
            name: 'sandboxes.acquireForSession throws',
            withCustomTool: true,
            overrides: (failingPool) => ({ sandboxes: failingPool }),
        },
        {
            // Regression: pi-ai's `getModel(provider, modelId)` returns
            // undefined for an unknown id. Before the fix in pi-client.ts the
            // undefined Model flowed into runSession and crashed
            // `errorContext()` on `deps.model.id` with the cryptic
            // "Cannot read properties of undefined (reading 'id')". Now
            // `resolveModel` throws an explicit `unknown_model_id: …` error
            // pre-flight and the session is marked failed.
            name: 'resolveModel returns undefined (unknown model id)',
            withCustomTool: false,
            overrides: () => ({
                resolveModel: () => {
                    throw new Error(
                        'unknown_model_id: spec.model="anthropic/claude-sonnet-4-7" — pi-ai has no model "claude-sonnet-4-7" registered for provider "anthropic". Check the pi-ai models registry or upgrade @earendil-works/pi-ai.'
                    )
                },
            }),
        },
    ]

    it.each(PREFLIGHT_CASES)(
        'runOne fails the session (loop survives) when $name',
        async ({ withCustomTool, overrides }) => {
            const revisions = new MemoryRevisionStore()
            const bundle = new MemoryBundleStore()
            const queue = new MemorySessionQueue()
            const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
            const COMPILED = `module.exports = { id: "noop", actions: { default: () => ({}) } }`
            const rev = await revisions.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 's3://x/',
                spec: AgentSpecSchema.parse({
                    model: 'faux/test',
                    tools: withCustomTool ? [{ kind: 'custom', id: 'noop', path: 'tools/noop/' }] : [],
                }),
            })
            await bundle.write(rev.id, 'agent.md', 'x')
            if (withCustomTool) {
                await bundle.write(rev.id, 'tools/noop/compiled.js', COMPILED)
                await bundle.write(rev.id, 'tools/noop/schema.json', '{}')
            }
            const session: AgentSession = {
                id: 'sess-preflight',
                application_id: app.id,
                revision_id: rev.id,
                team_id: 1,
                external_key: null,
                idempotency_key: null,
                trigger_metadata: null,
                state: 'queued',
                conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
                pending_inputs: [],
                principal: null,
                retry_count: 0,
                acl: [],
                pending_elevation_requests: [],
                failure_reason: null,
                usage_total: { ...EMPTY_USAGE_TOTAL },
                created_at: '2026-05-27',
                updated_at: '2026-05-27',
            }
            await queue.enqueue(session)

            // A pool that always rejects acquireForSession — only matters for
            // the sandbox-failure case but cheap to construct unconditionally.
            const failingPool = new InProcessSandboxPool()
            failingPool.acquireForSession = async () => {
                throw new Error('sandbox pool exhausted')
            }

            const worker = new Worker({
                queue,
                revisions,
                bundle,
                sandboxes: new InProcessSandboxPool(),
                broker: new SecretBroker(),
                resolveIntegrations: async () => ({}),
                resolveSecrets: async () => ({}),
                resolveModel: () => fauxModel([endTurn('would never run')]),
                ...overrides(failingPool),
            })

            await expect(worker.loop({ iterations: 1, claimTimeoutMs: 10 })).resolves.toBeUndefined()
            const after = await queue.get('sess-preflight')
            expect(after!.state).toBe('failed')
        }
    )

    // Pre-fix: a thrown error inside runOne went only to the pino logger
    // (runner stdout, invisible to the platform UI). The user could see
    // `state=failed` in the console but no reason. Now the catch block
    // mirrors the scrubbed error message into the session LogSink so the
    // Logs tab in the console explains *why*.
    //
    // Also asserts the token scrubber is wired — if a bearer token ever
    // leaks into an error string (e.g. an MCP transport echoing the
    // Authorization header back in a 401), it must be redacted before
    // landing in operator-visible storage.
    it('mirrors a session crash into the LogSink with tokens scrubbed', async () => {
        const revisions = new MemoryRevisionStore()
        const bundle = new MemoryBundleStore()
        const queue = new MemorySessionQueue()
        const logs = new InMemoryLogSink()
        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'faux/test' }),
        })
        await bundle.write(rev.id, 'agent.md', 'x')
        const session: AgentSession = {
            id: 'sess-crash',
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            idempotency_key: null,
            trigger_metadata: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            acl: [],
            pending_elevation_requests: [],
            failure_reason: null,
            usage_total: { ...EMPTY_USAGE_TOTAL },
            created_at: '2026-05-27',
            updated_at: '2026-05-27',
        }
        await queue.enqueue(session)

        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            logs,
            resolveIntegrations: async () => ({}),
            // Throw an error that *contains* a token-shaped value, simulating
            // a downstream component (MCP transport, fetch wrapper, etc.)
            // echoing a bearer header into its error message.
            resolveSecrets: async () => {
                throw new Error('upstream auth failed: Bearer ghp_realsecretvalue1234 rejected')
            },
            resolveModel: () => fauxModel([endTurn('would never run')]),
        })

        await worker.loop({ iterations: 1, claimTimeoutMs: 10 })

        const entries = logs.forSession('sess-crash')
        const crash = entries.find((e) => e.event === 'session.crashed')
        expect(crash).not.toBeUndefined()
        expect(crash!.level).toBe('error')
        expect(crash!.team_id).toBe(1)
        expect(crash!.application_id).toBe(app.id)
        const message = (crash!.data as { message: string }).message
        // Token redacted, surrounding context preserved.
        expect(message).toContain('ghp_****')
        expect(message).not.toContain('realsecretvalue')
        expect(message).toContain('upstream auth failed')

        // Layer 2: the same scrubbed reason lands on the session row
        // for the console banner. The Logs tab still has the full
        // context; this is the at-a-glance summary.
        const after = await queue.get('sess-crash')
        expect(after!.state).toBe('failed')
        expect(after!.failure_reason).not.toBeNull()
        expect(after!.failure_reason).toContain('ghp_****')
        expect(after!.failure_reason).not.toContain('realsecretvalue')
    })

    // Layer 2: any session that crashes with a long, multi-line error
    // gets a one-line, capped failure_reason. The Logs tab carries the
    // raw multi-line form (Layer 1); the row keeps the banner sane.
    it('truncates multi-line crash messages into a single-line failure_reason', async () => {
        const revisions = new MemoryRevisionStore()
        const bundle = new MemoryBundleStore()
        const queue = new MemorySessionQueue()
        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'faux/test' }),
        })
        await bundle.write(rev.id, 'agent.md', 'x')
        const session: AgentSession = {
            id: 'sess-multiline-crash',
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            idempotency_key: null,
            trigger_metadata: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            acl: [],
            pending_elevation_requests: [],
            failure_reason: null,
            usage_total: { ...EMPTY_USAGE_TOTAL },
            created_at: '2026-05-27',
            updated_at: '2026-05-27',
        }
        await queue.enqueue(session)

        const longError = ['Streamable HTTP error:', 'bad request:', 'error:', 'x'.repeat(800)].join('\n')
        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => {
                throw new Error(longError)
            },
            resolveModel: () => fauxModel([endTurn('would never run')]),
        })

        await worker.loop({ iterations: 1, claimTimeoutMs: 10 })

        const after = await queue.get('sess-multiline-crash')
        expect(after!.state).toBe('failed')
        const reason = after!.failure_reason!
        // Cap is 512; ellipsis added when the source was longer.
        expect(reason.length).toBeLessThanOrEqual(512)
        expect(reason.endsWith('…')).toBe(true)
        // Whitespace collapsed — no embedded newlines.
        expect(reason).not.toContain('\n')
        // Leading context preserved.
        expect(reason.startsWith('Streamable HTTP error:')).toBe(true)
    })

    it('main loop swallows transient claim() errors instead of crashing', async () => {
        const revisions = new MemoryRevisionStore()
        const bundle = new MemoryBundleStore()
        const queue = new MemorySessionQueue()

        let claimCalls = 0
        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
            resolveModel: () => fauxModel([]),
        })
        // First claim throws (transient PG error). Second time, signal a clean
        // shutdown so the loop exits — confirming the worker survived the
        // throw and is still spinning afterward.
        queue.claim = async () => {
            claimCalls++
            if (claimCalls === 1) {
                throw new Error('transient PG error')
            }
            await worker.stop()
            return null
        }

        await expect(worker.loop({ iterations: 5, claimTimeoutMs: 5 })).resolves.toBeUndefined()
        expect(claimCalls).toBeGreaterThanOrEqual(2)
    })
})
