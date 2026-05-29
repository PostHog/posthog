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

import { endTurn, FauxPiClient, ScriptedTurn, toolCall, toolUseTurn } from '../models/faux-pi-client'
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

    // Regression: the loop used to await Promise.allSettled on the inflight
    // set when at capacity, which meant N sessions had to ALL finish before
    // the next one could be claimed — a wave pattern that wasted capacity
    // whenever durations were uneven. The fix awaits Promise.race so one
    // finishing session immediately frees one slot. We pin this in by holding
    // sB open while sA finishes, and asserting sC gets claimed before sB does.
    it('claims a new session as soon as one slot frees (steady-state, not wave)', async () => {
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

        const ids = ['sA', 'sB', 'sC']
        // Per-session deferreds so each turn signals when it has STARTED
        // (so the test can observe inflight composition) and blocks until
        // the test RELEASES it.
        const started = new Map<string, { promise: Promise<void>; resolve: () => void }>()
        const release = new Map<string, () => void>()
        for (const id of ids) {
            let resolve!: () => void
            const promise = new Promise<void>((r) => {
                resolve = r
            })
            started.set(id, { promise, resolve })
        }

        for (const [i, id] of ids.entries()) {
            await queue.enqueue({
                id,
                application_id: app.id,
                revision_id: rev.id,
                team_id: 1,
                external_key: null,
                state: 'queued',
                // The session id is encoded into the seed user message so the
                // single scripted turn can route by session.
                conversation: [{ role: 'user', content: id, timestamp: Date.now() }],
                pending_inputs: [],
                principal: null,
                retry_count: 0,
                usage_total: { ...EMPTY_USAGE_TOTAL },
                created_at: `2026-05-27T00:00:0${i}Z`,
                updated_at: '2026-05-27',
            })
        }

        const gatedTurn: ScriptedTurn = async (ctx) => {
            const first = ctx.messages[0] as { role: string; content: unknown }
            const sessionId = typeof first.content === 'string' ? first.content : ''
            started.get(sessionId)!.resolve()
            await new Promise<void>((r) => {
                release.set(sessionId, r)
            })
            return endTurn(`done ${sessionId}`)
        }

        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            pi: new FauxPiClient([gatedTurn, gatedTurn, gatedTurn]),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
            maxConcurrency: 2,
        })

        const loopP = worker.loop({ iterations: 3, claimTimeoutMs: 5 })

        // Both initial slots fill.
        await started.get('sA')!.promise
        await started.get('sB')!.promise

        // Release sA. With the steady-state fix, sC must start while sB
        // is still in flight. Under the old wave behavior the loop would
        // block on `Promise.allSettled` for both sA AND sB before
        // claiming sC — this await would hang and the test would time out.
        release.get('sA')!()
        await started.get('sC')!.promise

        // sB is still held; release.set('sB') was registered but never
        // called. So sB is the proof that we didn't drain to zero.
        const sB = await queue.get('sB')
        expect(sB!.state).toBe('running')

        // Drain.
        release.get('sB')!()
        release.get('sC')!()
        await loopP

        for (const id of ids) {
            const after = await queue.get(id)
            expect(after!.state).toBe('completed')
        }
    }, 5_000)

    // Race semantics under failure — Promise.race is only safe because each
    // inflight promise has `.catch()` chained, so it resolves even when
    // runOne rejects. If a refactor ever removes that chain, race would
    // propagate the rejection and break the loop. Here we force runOne to
    // reject by making `broker.release` throw for sA (it's called in
    // runOne's `finally`, AFTER the try-block has already marked sA
    // completed — so the rejection comes out of runOne itself, not from
    // session-state handling).
    it('survives a slot whose runOne promise rejects (race semantics hold under failure)', async () => {
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

        const ids = ['sA', 'sB', 'sC']
        const started = new Map<string, { promise: Promise<void>; resolve: () => void }>()
        const release = new Map<string, () => void>()
        for (const id of ids) {
            let resolve!: () => void
            const promise = new Promise<void>((r) => {
                resolve = r
            })
            started.set(id, { promise, resolve })
        }
        for (const [i, id] of ids.entries()) {
            await queue.enqueue({
                id,
                application_id: app.id,
                revision_id: rev.id,
                team_id: 1,
                external_key: null,
                state: 'queued',
                conversation: [{ role: 'user', content: id, timestamp: Date.now() }],
                pending_inputs: [],
                principal: null,
                retry_count: 0,
                usage_total: { ...EMPTY_USAGE_TOTAL },
                created_at: `2026-05-27T00:00:0${i}Z`,
                updated_at: '2026-05-27',
            })
        }

        // sA: runs through without a gate (completes the try-block).
        // sB, sC: gated so the test can observe inflight composition.
        const routedTurn: ScriptedTurn = async (ctx) => {
            const first = ctx.messages[0] as { role: string; content: unknown }
            const sessionId = typeof first.content === 'string' ? first.content : ''
            started.get(sessionId)!.resolve()
            if (sessionId !== 'sA') {
                await new Promise<void>((r) => {
                    release.set(sessionId, r)
                })
            }
            return endTurn(`done ${sessionId}`)
        }

        const broker = new SecretBroker()
        const realRelease = broker.release.bind(broker)
        broker.release = (sessionId: string): void => {
            if (sessionId === 'sA') {
                throw new Error('simulated broker release failure')
            }
            realRelease(sessionId)
        }

        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            pi: new FauxPiClient([routedTurn, routedTurn, routedTurn]),
            broker,
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
            maxConcurrency: 2,
        })

        const loopP = worker.loop({ iterations: 3, claimTimeoutMs: 5 })

        // sB starts and is held; sA also reaches its turn but doesn't gate.
        await started.get('sB')!.promise
        // sA's turn ran, marked the session completed, then broker.release
        // threw in `finally` → runOne rejected → the outer `.catch` chain
        // swallowed it → its slot freed. sC must then be claimed despite
        // sA's rejection — that's the property under test.
        await started.get('sC')!.promise

        // sA finished (state was set before the finally-throw).
        const sA = await queue.get('sA')
        expect(sA!.state).toBe('completed')
        // sB is still in flight, proving the race wasn't a wave drain.
        const sB = await queue.get('sB')
        expect(sB!.state).toBe('running')

        release.get('sB')!()
        release.get('sC')!()
        await loopP

        expect((await queue.get('sB'))!.state).toBe('completed')
        expect((await queue.get('sC'))!.state).toBe('completed')
    }, 5_000)

    // Shutdown while parked on Promise.race. With both slots in flight on a
    // gated turn, stop() aborts the controller. The gated turn rejects with
    // AbortError, runSession returns suspended, runOne marks the session
    // queued, and the race resolves. The loop sees the abort and exits.
    it('cleanly drains when stop() fires while the loop is parked at capacity', async () => {
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

        const ids = ['sA', 'sB']
        const started = new Map<string, { promise: Promise<void>; resolve: () => void }>()
        for (const id of ids) {
            let resolve!: () => void
            const promise = new Promise<void>((r) => {
                resolve = r
            })
            started.set(id, { promise, resolve })
        }
        for (const [i, id] of ids.entries()) {
            await queue.enqueue({
                id,
                application_id: app.id,
                revision_id: rev.id,
                team_id: 1,
                external_key: null,
                state: 'queued',
                conversation: [{ role: 'user', content: id, timestamp: Date.now() }],
                pending_inputs: [],
                principal: null,
                retry_count: 0,
                usage_total: { ...EMPTY_USAGE_TOTAL },
                created_at: `2026-05-27T00:00:0${i}Z`,
                updated_at: '2026-05-27',
            })
        }

        // Gated turn that respects the abort signal — when shutdown
        // fires, the gate rejects with AbortError so runSession exits
        // via its abort path (returns state: 'suspended').
        const abortableGatedTurn: ScriptedTurn = async (ctx, opts) => {
            const first = ctx.messages[0] as { role: string; content: unknown }
            const sessionId = typeof first.content === 'string' ? first.content : ''
            started.get(sessionId)!.resolve()
            await new Promise<void>((resolve, reject) => {
                const fail = (): void => {
                    const e = new Error('aborted') as Error & { name: string }
                    e.name = 'AbortError'
                    reject(e)
                }
                if (opts?.signal?.aborted) {
                    fail()
                    return
                }
                opts?.signal?.addEventListener('abort', fail, { once: true })
            })
            return endTurn('unreachable')
        }

        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            pi: new FauxPiClient([abortableGatedTurn, abortableGatedTurn]),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
            maxConcurrency: 2,
        })

        const loopP = worker.loop({ iterations: 2, claimTimeoutMs: 5 })

        // Both at the gate; loop parked on Promise.race.
        await started.get('sA')!.promise
        await started.get('sB')!.promise

        await worker.stop()
        await loopP

        // Both sessions handed back to the queue for a sibling worker.
        expect((await queue.get('sA'))!.state).toBe('queued')
        expect((await queue.get('sB'))!.state).toBe('queued')
    }, 5_000)

    // Degenerate concurrency case. maxConcurrency=1 must serialise — the
    // second session may not start until the first has fully completed.
    it('with maxConcurrency=1 runs sessions strictly serially', async () => {
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

        const ids = ['sA', 'sB']
        const startedSet = new Set<string>()
        const started = new Map<string, { promise: Promise<void>; resolve: () => void }>()
        const release = new Map<string, () => void>()
        for (const id of ids) {
            let resolve!: () => void
            const promise = new Promise<void>((r) => {
                resolve = r
            })
            started.set(id, { promise, resolve })
        }
        for (const [i, id] of ids.entries()) {
            await queue.enqueue({
                id,
                application_id: app.id,
                revision_id: rev.id,
                team_id: 1,
                external_key: null,
                state: 'queued',
                conversation: [{ role: 'user', content: id, timestamp: Date.now() }],
                pending_inputs: [],
                principal: null,
                retry_count: 0,
                usage_total: { ...EMPTY_USAGE_TOTAL },
                created_at: `2026-05-27T00:00:0${i}Z`,
                updated_at: '2026-05-27',
            })
        }

        const gatedTurn: ScriptedTurn = async (ctx) => {
            const first = ctx.messages[0] as { role: string; content: unknown }
            const sessionId = typeof first.content === 'string' ? first.content : ''
            startedSet.add(sessionId)
            started.get(sessionId)!.resolve()
            await new Promise<void>((r) => {
                release.set(sessionId, r)
            })
            return endTurn(`done ${sessionId}`)
        }

        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            pi: new FauxPiClient([gatedTurn, gatedTurn]),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
            maxConcurrency: 1,
        })

        const loopP = worker.loop({ iterations: 2, claimTimeoutMs: 5 })

        await started.get('sA')!.promise
        // Critical assertion: sB has NOT started while sA is running.
        expect(startedSet.has('sB')).toBe(false)

        release.get('sA')!()
        await started.get('sB')!.promise
        expect(startedSet.has('sA')).toBe(true)
        expect((await queue.get('sA'))!.state).toBe('completed')

        release.get('sB')!()
        await loopP
        expect((await queue.get('sB'))!.state).toBe('completed')
    }, 5_000)

    // Throughput guarantee: with the at-capacity wait correct, exactly the
    // requested number of successful claims happen — neither more (bug: loop
    // bursts past the iterations bound) nor stuck below (bug: loop wedges).
    it('makes exactly `iterations` successful claims', async () => {
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

        const N = 5
        for (let i = 0; i < N; i++) {
            await queue.enqueue({
                id: `s${i}`,
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
                created_at: `2026-05-27T00:00:0${i}Z`,
                updated_at: '2026-05-27',
            })
        }

        let successfulClaims = 0
        const realClaim = queue.claim.bind(queue)
        queue.claim = async (timeoutMs: number) => {
            const result = await realClaim(timeoutMs)
            if (result) {
                successfulClaims++
            }
            return result
        }

        // Enough scripted turns for every session; FauxPiClient consumes
        // them in arrival order, which is fine because every turn is the
        // same (endTurn).
        const turns = Array.from({ length: N }, () => endTurn('done'))
        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            pi: new FauxPiClient(turns),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
            maxConcurrency: 3,
        })

        await worker.loop({ iterations: N, claimTimeoutMs: 5 })
        expect(successfulClaims).toBe(N)
        for (let i = 0; i < N; i++) {
            expect((await queue.get(`s${i}`))!.state).toBe('completed')
        }
    })

    // Empty-inflight guard. The inner at-capacity wait only enters when
    // inflight.size >= maxConcurrency. With maxConcurrency=10 and 1 session,
    // the loop never enters that wait — so Promise.race is never called on
    // an empty iterable (which would hang forever). If a refactor ever drops
    // the size guard, this test catches the regression by timing out.
    it('never parks on Promise.race when inflight is below capacity', async () => {
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
        await queue.enqueue({
            id: 'sOnly',
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
        })

        const worker = new Worker({
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            pi: new FauxPiClient([endTurn('done')]),
            broker: new SecretBroker(),
            resolveIntegrations: async () => ({}),
            resolveSecrets: async () => ({}),
            maxConcurrency: 10,
        })

        await worker.loop({ iterations: 1, claimTimeoutMs: 5 })
        expect((await queue.get('sOnly'))!.state).toBe('completed')
    }, 5_000)
})
