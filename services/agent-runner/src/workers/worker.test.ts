import {
    AgentSession,
    AgentSpecSchema,
    EMPTY_USAGE_TOTAL,
    InProcessSandboxPool,
    MemoryBundleStore,
    MemoryRevisionStore,
    MemorySessionQueue,
    SecretBroker,
} from '@posthog/agent-shared'
import { setPosthogInternalClient } from '@posthog/agent-tools'

import { endTurn, FauxPiClient, toolCall, toolUseTurn } from '../models/faux-pi-client'
import { Worker } from './worker'

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
            state: 'queued',
            conversation: [{ role: 'user', content: 'hello', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
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
            pi: new FauxPiClient([endTurn('hi back')]),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
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
            state: 'queued',
            conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
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
            pi: new FauxPiClient([toolUseTurn([toolCall('noop', {})]), endTurn('done')]),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({ ACME_KEY: 'topsecret' }),
        })

        await worker.loop({ iterations: 1, claimTimeoutMs: 10 })
        const after = await queue.get('sess2')
        expect(after!.state).toBe('completed')
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
            state: 'queued',
            conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
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
            pi: new FauxPiClient([
                (() => {
                    // Signal shutdown after the first turn so the next iteration sees it.
                    queueMicrotask(() => void worker.stop())
                    return toolUseTurn([toolCall('@posthog/query', { query: 'x' })])
                }) as never,
                endTurn('never reaches here'),
            ]),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
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
            state: 'queued',
            conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
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
            pi: new FauxPiClient([endTurn('would never run')]),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
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
                state: 'queued',
                conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
                pending_inputs: [],
                principal: null,
                retry_count: 0,
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
                pi: new FauxPiClient([endTurn('would never run')]),
                broker: new SecretBroker(),
                resolveIntegrations: async () => ({}),
                resolveSecrets: async () => ({}),
                ...overrides(failingPool),
            })

            await expect(worker.loop({ iterations: 1, claimTimeoutMs: 10 })).resolves.toBeUndefined()
            const after = await queue.get('sess-preflight')
            expect(after!.state).toBe('failed')
        }
    )

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
            pi: new FauxPiClient([]),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
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
