import request from 'supertest'

import {
    AgentSession,
    AgentSpecSchema,
    EMPTY_USAGE_TOTAL,
    MemoryBundleStore,
    MemoryRevisionStore,
    MemorySessionQueue,
} from '@posthog/agent-shared'

import { buildJanitorApp } from './server'

function session(id: string): AgentSession {
    return {
        id,
        application_id: 'app',
        revision_id: 'rev',
        team_id: 1,
        external_key: null,
        idempotency_key: null,
        trigger_metadata: null,
        state: 'running',
        conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
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

describe('janitor HTTP', () => {
    function mk(): { queue: MemorySessionQueue; app: ReturnType<typeof buildJanitorApp> } {
        const queue = new MemorySessionQueue()
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
        })
        return { queue, app }
    }

    it('GET /healthz returns ok', async () => {
        const { app } = mk()
        const res = await request(app).get('/healthz')
        expect(res.status).toBe(200)
    })

    it('GET /sessions?application_id= returns summaries, newest first', async () => {
        const { queue, app } = mk()
        const a = { ...session('s-a'), application_id: 'app-1', created_at: '2026-05-01T00:00:00Z' }
        const b = { ...session('s-b'), application_id: 'app-1', created_at: '2026-05-02T00:00:00Z' }
        const c = { ...session('s-c'), application_id: 'other', created_at: '2026-05-03T00:00:00Z' }
        await queue.enqueue(a)
        await queue.enqueue(b)
        await queue.enqueue(c)
        const res = await request(app).get('/sessions').query({ application_id: 'app-1' })
        expect(res.status).toBe(200)
        const ids = (res.body.results as Array<{ id: string }>).map((s) => s.id)
        expect(ids).toEqual(['s-b', 's-a'])
        expect(res.body.count).toBe(2)
        // Summaries strip the heavy conversation body.
        expect(Object.keys(res.body.results[0])).not.toContain('conversation')
        expect(res.body.results[0]).toMatchObject({ turns: 1, state: 'running' })
    })

    it('GET /sessions without application_id returns a structured 400', async () => {
        const { app } = mk()
        const res = await request(app).get('/sessions')
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_request')
        // The zod issues array points at the offending field so callers can
        // surface useful messages instead of a generic "bad request".
        const issues = res.body.issues as Array<{ path: string[]; message: string }>
        expect(issues.some((i) => i.path[0] === 'application_id')).toBe(true)
    })

    it('GET /sessions with garbage state value returns 400 instead of crashing', async () => {
        // Pre-zod, an unknown state silently passed through to the queue layer
        // and could cause weird filter behavior. The schema rejects it now.
        const { app } = mk()
        const res = await request(app).get('/sessions').query({ application_id: 'app-1', state: 'banana' })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_request')
    })

    it('PUT /revisions/:id/bundle with null files returns 400 instead of crashing', async () => {
        // Regression: pre-zod, `typeof null === 'object'` slipped through the
        // shape check and the route would attempt `Object.entries(null)` and
        // throw an unhandled rejection. The schema now rejects null up front.
        const { app, revisionId } = await mkRevisionApp()
        const res = await request(app).put(`/revisions/${revisionId}/bundle`).send({ files: null })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_request')
    })

    it('PUT /revisions/:id/bundle with non-string file content returns 400', async () => {
        // Pre-zod, `{ files: { a: 42 } }` passed the loose `typeof object`
        // check and reached `bundles.write(..., 42)`, which then threw.
        const { app, revisionId } = await mkRevisionApp()
        const res = await request(app)
            .put(`/revisions/${revisionId}/bundle`)
            .send({ files: { 'agent.md': 42 } })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_request')
    })

    it('PUT /revisions/:id/file rejects content over the per-file size cap', async () => {
        // Pre-cap, a single 7MB file would slip through the express.json 8MB
        // limit and land on disk.
        const { app, revisionId } = await mkRevisionApp()
        const tooLarge = 'a'.repeat(1_000_001)
        const res = await request(app).put(`/revisions/${revisionId}/file?path=big.md`).send({ content: tooLarge })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_request')
        expect((res.body.issues as Array<{ message: string }>)[0].message).toMatch(/exceeds.*1000000/)
    })

    it('PUT /revisions/:id/bundle rejects a single file over the per-file cap', async () => {
        const { app, revisionId } = await mkRevisionApp()
        const res = await request(app)
            .put(`/revisions/${revisionId}/bundle`)
            .send({ files: { 'big.md': 'a'.repeat(1_000_001) } })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_request')
        // Issue path points at the offending file so the caller knows which one.
        const issues = res.body.issues as Array<{ path: (string | number)[]; message: string }>
        expect(issues.some((i) => i.path.includes('big.md'))).toBe(true)
    })

    it('PUT /revisions/:id/bundle rejects many under-limit files that sum past the bundle cap', async () => {
        const { app, revisionId } = await mkRevisionApp()
        // Five 900KB files = 4.5MB total. Each one fits under the 1MB
        // per-file cap; the bundle exceeds the 4MB total cap.
        const half = 'a'.repeat(900_000)
        const files: Record<string, string> = {}
        for (let i = 0; i < 5; i++) {
            files[`f${i}.md`] = half
        }
        const res = await request(app).put(`/revisions/${revisionId}/bundle`).send({ files })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_request')
    })

    it('GET /sessions supports state / revision_id / created_after filters', async () => {
        const { queue, app } = mk()
        await queue.enqueue({
            ...session('done-r1'),
            application_id: 'app-1',
            revision_id: 'rev-1',
            state: 'completed',
            created_at: '2026-05-02T00:00:00Z',
        })
        await queue.enqueue({
            ...session('fail-r1'),
            application_id: 'app-1',
            revision_id: 'rev-1',
            state: 'failed',
            created_at: '2026-05-03T00:00:00Z',
        })
        await queue.enqueue({
            ...session('done-r2'),
            application_id: 'app-1',
            revision_id: 'rev-2',
            state: 'completed',
            created_at: '2026-04-25T00:00:00Z',
        })
        // state=completed,failed → both completed and failed across revs
        const both = await request(app).get('/sessions').query({ application_id: 'app-1', state: 'completed,failed' })
        expect((both.body.results as Array<{ id: string }>).map((s) => s.id).sort()).toEqual([
            'done-r1',
            'done-r2',
            'fail-r1',
        ])
        // revision_id filter scopes to one revision
        const r1 = await request(app).get('/sessions').query({ application_id: 'app-1', revision_id: 'rev-1' })
        expect((r1.body.results as Array<{ id: string }>).map((s) => s.id).sort()).toEqual(['done-r1', 'fail-r1'])
        // created_after excludes older sessions
        const recent = await request(app)
            .get('/sessions')
            .query({ application_id: 'app-1', created_after: '2026-05-01T00:00:00Z' })
        expect((recent.body.results as Array<{ id: string }>).map((s) => s.id).sort()).toEqual(['done-r1', 'fail-r1'])
    })

    it('GET /sessions summaries include preview + usage_total off the persisted column', async () => {
        const { queue, app } = mk()
        await queue.enqueue({
            ...session('s-rich'),
            application_id: 'app-1',
            // The runner accumulates this; we set it explicitly so the summary
            // matches what a live row would carry.
            usage_total: {
                ...EMPTY_USAGE_TOTAL,
                tokens_in: 50,
                tokens_out: 10,
                cost_input: 0.0005,
                cost_output: 0.0002,
                cost_total: 0.0007,
            },
            conversation: [
                { role: 'user', content: 'hi', timestamp: 1 },
                {
                    role: 'assistant',
                    content: [{ type: 'text', text: 'hello back!' }],
                    api: 'anthropic-messages',
                    provider: 'anthropic',
                    model: 'claude-haiku-4-5',
                    usage: { input: 50, output: 10, cost: { input: 0.0005, output: 0.0002, total: 0.0007 } },
                    timestamp: 2,
                },
            ],
        })
        const res = await request(app).get('/sessions').query({ application_id: 'app-1' })
        expect(res.body.results[0].preview).toBe('hello back!')
        expect(res.body.results[0].usage_total).toMatchObject({
            tokens_in: 50,
            tokens_out: 10,
            cost_total: 0.0007,
        })
    })

    it('GET /sessions/:id returns session, 404 if missing', async () => {
        const { queue, app } = mk()
        await queue.enqueue(session('s1'))
        const ok = await request(app).get('/sessions/s1')
        expect(ok.status).toBe(200)
        expect(ok.body.id).toBe('s1')
        expect(ok.body.conversation_trimmed).toBe(false)
        expect(ok.body.usage_total).not.toBeUndefined()
        const miss = await request(app).get('/sessions/nope')
        expect(miss.status).toBe(404)
    })

    it('GET /sessions/:id?last_n trims the transcript but keeps usage_total accurate', async () => {
        const { queue, app } = mk()
        await queue.enqueue({
            ...session('s-long'),
            // Mirror what the runner would have accumulated by turn 2.
            usage_total: {
                ...EMPTY_USAGE_TOTAL,
                tokens_in: 30,
                tokens_out: 15,
                cost_input: 0.0003,
                cost_output: 0.00015,
                cost_total: 0.00045,
            },
            conversation: [
                { role: 'user', content: 'turn1', timestamp: 1 },
                {
                    role: 'assistant',
                    content: [{ type: 'text', text: 'reply1' }],
                    api: 'a',
                    provider: 'a',
                    model: 'm',
                    usage: { input: 10, output: 5, cost: { input: 0.0001, output: 0.00005, total: 0.00015 } },
                    timestamp: 2,
                },
                { role: 'user', content: 'turn2', timestamp: 3 },
                {
                    role: 'assistant',
                    content: [{ type: 'text', text: 'reply2' }],
                    api: 'a',
                    provider: 'a',
                    model: 'm',
                    usage: { input: 20, output: 10, cost: { input: 0.0002, output: 0.0001, total: 0.0003 } },
                    timestamp: 4,
                },
            ],
        })
        const res = await request(app).get('/sessions/s-long').query({ last_n: 2 })
        expect(res.body.conversation_trimmed).toBe(true)
        expect(res.body.conversation_total_turns).toBe(4)
        expect(res.body.conversation).toHaveLength(2)
        // Last two messages are turn2 + reply2.
        expect(res.body.conversation[0].content).toBe('turn2')
        // usage_total comes off the persisted column — not derived from the trim.
        expect(res.body.usage_total.tokens_in).toBe(30)
    })

    it('POST /sessions/backfill_usage rewrites usage_total from conversation', async () => {
        const { queue, app } = mk()
        await queue.enqueue({
            ...session('s-backfill'),
            application_id: 'app-x',
            conversation: [
                { role: 'user', content: 'q', timestamp: 1 },
                {
                    role: 'assistant',
                    content: [{ type: 'text', text: 'a' }],
                    api: 'a',
                    provider: 'a',
                    model: 'm',
                    usage: { input: 7, output: 3, cost: { input: 0.01, output: 0.005, total: 0.015 } },
                    timestamp: 2,
                },
            ],
        })
        // Dry-run reports the would-be change but doesn't persist.
        const dry = await request(app).post('/sessions/backfill_usage').send({ application_id: 'app-x', dry_run: true })
        expect(dry.status).toBe(200)
        expect(dry.body).toMatchObject({ scanned: 1, updated: 1, dry_run: true })
        expect((await queue.get('s-backfill'))!.usage_total.tokens_in).toBe(0)

        // Real run writes the recomputed totals.
        const real = await request(app)
            .post('/sessions/backfill_usage')
            .send({ application_id: 'app-x', dry_run: false })
        expect(real.body).toMatchObject({ scanned: 1, updated: 1, dry_run: false })
        const after = (await queue.get('s-backfill'))!
        expect(after.usage_total.tokens_in).toBe(7)
        expect(after.usage_total.cost_total).toBeCloseTo(0.015, 10)

        // Second run finds nothing to update.
        const repeat = await request(app)
            .post('/sessions/backfill_usage')
            .send({ application_id: 'app-x', dry_run: false })
        expect(repeat.body).toMatchObject({ scanned: 1, updated: 0 })
    })

    it('POST /sessions/:id/cancel marks cancelled', async () => {
        const { queue, app } = mk()
        await queue.enqueue(session('s2'))
        const res = await request(app).post('/sessions/s2/cancel')
        expect(res.status).toBe(200)
        expect(res.body).toMatchObject({ ok: true, state: 'cancelled' })
        expect((await queue.get('s2'))!.state).toBe('cancelled')
    })

    it('POST /sessions/:id/cancel is idempotent on terminal state', async () => {
        const { queue, app } = mk()
        await queue.enqueue(session('s2b'))
        await request(app).post('/sessions/s2b/cancel')
        const second = await request(app).post('/sessions/s2b/cancel')
        expect(second.status).toBe(200)
        expect(second.body).toMatchObject({ ok: true, idempotent: true, state: 'cancelled' })
    })

    /* ────────────────────────── fleet stats ────────────────────────── */

    it('GET /sessions/stats rolls up per-application counts + spend', async () => {
        const { queue, app } = mk()
        const now = Date.now()
        const iso = (d: number): string => new Date(d).toISOString()
        const recent = iso(now - 60_000)
        const old = iso(now - 7 * 24 * 60 * 60 * 1000)
        await queue.enqueue({
            ...session('live-1'),
            application_id: 'app-x',
            state: 'running',
            created_at: recent,
            updated_at: recent,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 0.5 },
        })
        await queue.enqueue({
            ...session('done-1'),
            application_id: 'app-x',
            state: 'completed',
            created_at: recent,
            updated_at: recent,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 1.25 },
        })
        await queue.enqueue({
            ...session('failed-1'),
            application_id: 'app-x',
            state: 'failed',
            created_at: recent,
            updated_at: recent,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 0.1 },
        })
        await queue.enqueue({
            ...session('old-1'),
            application_id: 'app-x',
            state: 'completed',
            created_at: old,
            updated_at: old,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 99 },
        })
        await queue.enqueue({
            ...session('other-app'),
            application_id: 'app-y',
            state: 'running',
            created_at: recent,
            updated_at: recent,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 99 },
        })
        const res = await request(app).get('/sessions/stats').query({ application_id: 'app-x' })
        expect(res.status).toBe(200)
        expect(res.body).toMatchObject({
            liveCount: 1,
            sessionsInWindowCount: 3,
            spendInWindowUsd: 0.5 + 1.25 + 0.1,
            failedInWindowCount: 1,
        })
        expect(res.body.lastActivityAt).toBe(recent)
    })

    it('GET /fleet/stats rolls up per-team counts + spend', async () => {
        const { queue, app } = mk()
        const now = Date.now()
        const recent = new Date(now - 60_000).toISOString()
        await queue.enqueue({
            ...session('t1-live'),
            team_id: 7,
            state: 'running',
            created_at: recent,
            updated_at: recent,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 2 },
        })
        await queue.enqueue({
            ...session('t1-done'),
            team_id: 7,
            state: 'completed',
            created_at: recent,
            updated_at: recent,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 1 },
        })
        await queue.enqueue({
            ...session('t2-other'),
            team_id: 99,
            state: 'running',
            created_at: recent,
            updated_at: recent,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 50 },
        })
        const res = await request(app).get('/fleet/stats').query({ team_id: 7 })
        expect(res.status).toBe(200)
        expect(res.body).toMatchObject({ liveCount: 1, sessionsInWindowCount: 2, spendInWindowUsd: 3 })
    })

    it('GET /sessions/live returns live sessions for a team', async () => {
        const { queue, app } = mk()
        const now = Date.now()
        const recent = new Date(now - 60_000).toISOString()
        const newer = new Date(now - 30_000).toISOString()
        await queue.enqueue({
            ...session('live-old'),
            team_id: 7,
            state: 'queued',
            created_at: recent,
            updated_at: recent,
        })
        await queue.enqueue({
            ...session('live-new'),
            team_id: 7,
            state: 'running',
            created_at: newer,
            updated_at: newer,
        })
        await queue.enqueue({
            ...session('done'),
            team_id: 7,
            state: 'completed',
            created_at: newer,
            updated_at: newer,
        })
        await queue.enqueue({
            ...session('other-team'),
            team_id: 99,
            state: 'running',
            created_at: newer,
            updated_at: newer,
        })
        const res = await request(app).get('/sessions/live').query({ team_id: 7 })
        expect(res.status).toBe(200)
        const ids = (res.body.results as Array<{ id: string }>).map((s) => s.id)
        expect(ids).toEqual(['live-new', 'live-old'])
        expect(Object.keys(res.body.results[0])).not.toContain('conversation')
    })

    it('GET /sessions/stats without application_id returns 400', async () => {
        const { app } = mk()
        const res = await request(app).get('/sessions/stats')
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_request')
    })

    it('GET /fleet/stats without team_id returns 400', async () => {
        const { app } = mk()
        const res = await request(app).get('/fleet/stats')
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_request')
    })

    it('POST /sweep returns counts', async () => {
        const { app } = mk()
        const res = await request(app).post('/sweep')
        expect(res.status).toBe(200)
        expect(res.body).toEqual({
            requeued: 0,
            poisoned: 0,
            closed: 0,
            expired_approvals: 0,
            cleared_idempotency_keys: 0,
            reaped_sandboxes: 0,
            sandbox_reap_failures: 0,
        })
    })

    it('enforces internal secret when configured', async () => {
        const queue = new MemorySessionQueue()
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
            internalSecret: 'topsecret',
        })
        const noAuth = await request(app).get('/sessions/x')
        expect(noAuth.status).toBe(401)
        const withAuth = await request(app).get('/sessions/x').set('x-internal-secret', 'topsecret')
        expect(withAuth.status).toBe(404) // session not found, but auth passed
    })

    /* ────────────────────────── catalog ────────────────────────── */

    it('GET /native_tools returns the registry catalog', async () => {
        const { app } = mk()
        const res = await request(app).get('/native_tools')
        expect(res.status).toBe(200)
        const ids = (res.body.tools as Array<{ id: string }>).map((t) => t.id)
        // Spot-check a couple of stable tools from different families. Meta
        // tools (`@posthog/meta-*`) are auto-included by the runner outside
        // ALL_TOOLS and are deliberately NOT in this list.
        expect(ids).toEqual(expect.arrayContaining(['@posthog/query', '@posthog/memory-list']))
    })

    /* ────────────────────────── revisions ────────────────────────── */

    async function mkRevisionApp(): Promise<{
        revisions: MemoryRevisionStore
        bundles: MemoryBundleStore
        app: ReturnType<typeof buildJanitorApp>
        revisionId: string
    }> {
        const revisions = new MemoryRevisionStore()
        const bundles = new MemoryBundleStore()
        const queue = new MemorySessionQueue()
        const apprec = await revisions.createApplication({ team_id: 1, slug: 'a', name: 'A', description: '' })
        const rev = await revisions.createRevision({
            application_id: apprec.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 'mem://b',
            spec: AgentSpecSchema.parse({
                model: 'x',
                triggers: [{ type: 'chat', config: { require_auth: false } }],
            }),
        })
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
            revisions,
            bundles,
        })
        return { revisions, bundles, app, revisionId: rev.id }
    }

    it('GET /revisions/:id/system-prompt returns the assembled prompt + framework version', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'agent.md', '## Author content\n\nThis is the author-side prompt.')
        const res = await request(app).get(`/revisions/${revisionId}/system-prompt`)
        expect(res.status).toBe(200)
        expect(res.body.revision_id).toBe(revisionId)
        expect(res.body.framework_prompt_version).toBeGreaterThanOrEqual(1)
        const prompt = res.body.system_prompt as string
        // Framework preamble landed first…
        expect(prompt).toContain('Platform guidance')
        expect(prompt).toContain('@posthog/meta-end-turn')
        // …then the author content.
        expect(prompt).toContain('This is the author-side prompt.')
        expect(prompt.indexOf('Platform guidance')).toBeLessThan(prompt.indexOf('This is the author-side prompt.'))
    })

    it('GET /revisions/:id/system-prompt 404s for an unknown revision', async () => {
        const { app } = await mkRevisionApp()
        const res = await request(app).get('/revisions/00000000-0000-0000-0000-000000000000/system-prompt')
        expect(res.status).toBe(404)
    })

    it('POST /revisions/:id/cron/fire enqueues a session for the named cron', async () => {
        const revisions = new MemoryRevisionStore()
        const bundles = new MemoryBundleStore()
        const queue = new MemorySessionQueue()
        const apprec = await revisions.createApplication({ team_id: 1, slug: 'a', name: 'A', description: '' })
        const rev = await revisions.createRevision({
            application_id: apprec.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 'mem://b',
            spec: AgentSpecSchema.parse({
                model: 'x',
                triggers: [
                    {
                        type: 'cron',
                        config: { name: 'digest', schedule: '0 9 * * MON', prompt: 'Run the digest.' },
                    },
                ],
            }),
        })
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
            revisions,
            bundles,
        })
        const res = await request(app)
            .post(`/revisions/${rev.id}/cron/fire`)
            .send({ cron_name: 'digest', request_id: 'click-1' })
        expect(res.status).toBe(200)
        expect(res.body.ok).toBe(true)
        expect(res.body.session_id).toBeTruthy()
        expect(res.body.idempotency_key).toBe(`cron-manual:${rev.id}:digest:click-1`)
        const session = await queue.get(res.body.session_id)
        expect((session!.conversation[0] as { content: string }).content).toBe('Run the digest.')
    })

    it('POST /revisions/:id/cron/fire dedupes repeat clicks with the same request_id', async () => {
        const revisions = new MemoryRevisionStore()
        const bundles = new MemoryBundleStore()
        const queue = new MemorySessionQueue()
        const apprec = await revisions.createApplication({ team_id: 1, slug: 'a', name: 'A', description: '' })
        const rev = await revisions.createRevision({
            application_id: apprec.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 'mem://b',
            spec: AgentSpecSchema.parse({
                model: 'x',
                triggers: [
                    {
                        type: 'cron',
                        config: { name: 'digest', schedule: '0 9 * * MON', prompt: 'p' },
                    },
                ],
            }),
        })
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
            revisions,
            bundles,
        })
        const a = await request(app)
            .post(`/revisions/${rev.id}/cron/fire`)
            .send({ cron_name: 'digest', request_id: 'click-1' })
        const b = await request(app)
            .post(`/revisions/${rev.id}/cron/fire`)
            .send({ cron_name: 'digest', request_id: 'click-1' })
        expect(a.body.session_id).toBe(b.body.session_id)
    })

    it('POST /revisions/:id/cron/fire 404s when the cron name is not declared', async () => {
        const { app, revisionId } = await mkRevisionApp()
        const res = await request(app)
            .post(`/revisions/${revisionId}/cron/fire`)
            .send({ cron_name: 'ghost', request_id: 'r' })
        expect(res.status).toBe(404)
        expect(res.body.error).toBe('unknown_cron')
    })

    it('GET /revisions/:id/manifest returns the file list + state', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'agent.md', 'hello')
        await bundles.write(revisionId, 'skills/research.md', 'be thorough')
        const res = await request(app).get(`/revisions/${revisionId}/manifest`)
        expect(res.status).toBe(200)
        expect(res.body.state).toBe('draft')
        const paths = (res.body.files as Array<{ path: string }>).map((f) => f.path).sort()
        expect(paths).toEqual(['agent.md', 'skills/research.md'])
    })

    it('PUT /revisions/:id/file writes and GET reads back', async () => {
        const { app, revisionId } = await mkRevisionApp()
        const put = await request(app)
            .put(`/revisions/${revisionId}/file?path=tools/wc/source.ts`)
            .send({ content: 'export default 1' })
        expect(put.status).toBe(200)
        const get = await request(app).get(`/revisions/${revisionId}/file?path=tools/wc/source.ts`)
        expect(get.status).toBe(200)
        expect(get.body.content).toBe('export default 1')
    })

    it('DELETE /revisions/:id/file removes the file', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'doomed.md', 'bye')
        const del = await request(app).delete(`/revisions/${revisionId}/file?path=doomed.md`)
        expect(del.status).toBe(200)
        expect(await bundles.exists(revisionId, 'doomed.md')).toBe(false)
    })

    it('GET /revisions/:id/bundle bulk-pulls every file', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'agent.md', 'a')
        await bundles.write(revisionId, 'skills/x.md', 'b')
        const res = await request(app).get(`/revisions/${revisionId}/bundle`)
        expect(res.status).toBe(200)
        expect(res.body.files).toEqual({ 'agent.md': 'a', 'skills/x.md': 'b' })
    })

    it('PUT /revisions/:id/bundle with mode=replace wipes and writes', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'old.md', 'gone')
        const res = await request(app)
            .put(`/revisions/${revisionId}/bundle`)
            .send({ files: { 'new.md': 'fresh', 'agent.md': 'top' }, mode: 'replace' })
        expect(res.status).toBe(200)
        const paths = (res.body.files as Array<{ path: string }>).map((f) => f.path).sort()
        expect(paths).toEqual(['agent.md', 'new.md'])
        expect(await bundles.exists(revisionId, 'old.md')).toBe(false)
    })

    it('PUT /revisions/:id/bundle with mode=merge upserts without wiping', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'keep.md', 'still here')
        const res = await request(app)
            .put(`/revisions/${revisionId}/bundle`)
            .send({ files: { 'added.md': 'new' }, mode: 'merge' })
        expect(res.status).toBe(200)
        const paths = (res.body.files as Array<{ path: string }>).map((f) => f.path).sort()
        expect(paths).toEqual(['added.md', 'keep.md'])
    })

    it('POST /revisions/:id/freeze returns the sha + state hint, writes the S3 frozen marker, and does NOT mutate agent_revision', async () => {
        const { app, bundles, revisions, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'agent.md', 'final')
        const res = await request(app).post(`/revisions/${revisionId}/freeze`)
        expect(res.status).toBe(200)
        expect(res.body.state).toBe('ready')
        expect(res.body.bundle_sha256).toMatch(/^[0-9a-f]{64}$/)
        // Janitor is no longer a writer to `agent_revision.state` /
        // `bundle_sha256` — Django stamps those inside its own freeze
        // transaction using the returned sha. The bundle store's .frozen
        // marker is still written here; subsequent writes refuse.
        const after = await revisions.getRevision(revisionId)
        expect(after!.state).toBe('draft')
        expect(after!.bundle_sha256).toBeNull()
    })

    it('refuses writes once the revision is frozen', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'agent.md', 'final')
        await request(app).post(`/revisions/${revisionId}/freeze`)
        const put = await request(app).put(`/revisions/${revisionId}/file?path=agent.md`).send({ content: 'x' })
        expect(put.status).toBe(409)
        expect(put.body.error).toBe('revision_not_editable')
    })

    it('POST /revisions/:id/clone_from copies every file from the source', async () => {
        const { app, bundles, revisions, revisionId } = await mkRevisionApp()
        // Make the existing revision the source — seed it with files, freeze it.
        await bundles.write(revisionId, 'agent.md', 'parent')
        await bundles.write(revisionId, 'skills/x.md', 'parent skill')
        await request(app).post(`/revisions/${revisionId}/freeze`)
        // Create a fresh draft to clone into.
        const apps = await revisions.listApplications(1)
        const draft = await revisions.createRevision({
            application_id: apps[0].id,
            parent_revision_id: revisionId,
            created_by_id: null,
            bundle_uri: 'mem://b2',
            spec: { model: 'x' } as never,
        })
        const res = await request(app)
            .post(`/revisions/${draft.id}/clone_from`)
            .send({ source_revision_id: revisionId })
        expect(res.status).toBe(200)
        const paths = (res.body.files as Array<{ path: string }>).map((f) => f.path).sort()
        expect(paths).toEqual(['agent.md', 'skills/x.md'])
    })

    it('returns 503 when the revision/bundle stores are not configured', async () => {
        const { app } = mk() // no revisions/bundles
        const res = await request(app).get('/revisions/00000000-0000-0000-0000-000000000000/manifest')
        expect(res.status).toBe(503)
    })
})
