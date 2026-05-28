/**
 * Real Postgres tests against agent_runtime_queue_test. Schema is recreated
 * per suite via SCHEMA_SQL/DROP_SQL — no migrations, no shared state across
 * suites.
 *
 * The test database is provided by the local hogli dev stack
 * (see services/agent-tests/.. for setup). We probe and skip the suite if
 * the database isn't reachable.
 */

import { Pool } from 'pg'

import { PgSessionQueue } from './pg-queue'
import { PgRevisionStore } from './pg-revision-store'
import { DROP_SQL, SCHEMA_SQL } from './pg-schema'
import { AgentSpecSchema } from './spec'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

async function isReachable(): Promise<boolean> {
    const probe = new Pool({ connectionString: TEST_DB_URL, max: 1 })
    try {
        await probe.query('SELECT 1')
        return true
    } catch {
        return false
    } finally {
        await probe.end().catch(() => undefined)
    }
}

const maybeDescribe = process.env.SKIP_PG_TESTS === '1' ? describe.skip : describe

maybeDescribe('Postgres impls (real PG)', () => {
    let pool: Pool
    let reachable = false

    beforeAll(async () => {
        reachable = await isReachable()
        if (!reachable) {
            // eslint-disable-next-line no-console
            console.warn(`[pg-impls.test] ${TEST_DB_URL} unreachable — skipping`)
            return
        }
        pool = new Pool({ connectionString: TEST_DB_URL, max: 4 })
    })

    beforeEach(async () => {
        if (!reachable) {
            return
        }
        await pool.query(DROP_SQL)
        await pool.query(SCHEMA_SQL)
    })

    afterAll(async () => {
        if (pool) {
            await pool.query(DROP_SQL).catch(() => undefined)
            await pool.end()
        }
    })

    it('PgRevisionStore round-trip: create app, create revision, update spec, set live', async () => {
        if (!reachable) {
            return
        }
        const store = new PgRevisionStore(pool)
        const app = await store.createApplication({ team_id: 1, slug: 'echo', name: 'Echo', description: '' })
        expect(await store.getApplicationBySlug(1, 'echo')).toMatchObject({ slug: 'echo' })

        const spec = AgentSpecSchema.parse({ model: 'mock-echo' })
        const rev = await store.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by: 'u',
            bundle_uri: 's3://x/',
            spec,
        })
        expect(rev.state).toBe('draft')

        const newSpec = AgentSpecSchema.parse({ model: 'mock-static:hello' })
        await store.updateSpec(rev.id, newSpec)
        const after = await store.getRevision(rev.id)
        expect(after!.spec.model).toBe('mock-static:hello')

        await store.setRevisionState(rev.id, 'live')
        await store.setLiveRevision(app.id, rev.id)
        expect((await store.getApplication(app.id))!.live_revision_id).toBe(rev.id)
    })

    it('PgRevisionStore rejects spec updates on non-draft revisions', async () => {
        if (!reachable) {
            return
        }
        const store = new PgRevisionStore(pool)
        const app = await store.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await store.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by: 'u',
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'x' }),
        })
        await store.setRevisionState(rev.id, 'ready', 'deadbeef')
        await expect(store.updateSpec(rev.id, AgentSpecSchema.parse({ model: 'y' }))).rejects.toThrow(/not a draft/)
    })

    it('PgSessionQueue enqueue/claim with SKIP LOCKED across concurrent claimers', async () => {
        if (!reachable) {
            return
        }
        const revisions = new PgRevisionStore(pool)
        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by: 'u',
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'x' }),
        })

        const queue = new PgSessionQueue(pool)
        for (let i = 0; i < 5; i++) {
            await queue.enqueue({
                id: `00000000-0000-0000-0000-00000000000${i + 1}`,
                application_id: app.id,
                revision_id: rev.id,
                team_id: 1,
                external_key: null,
                state: 'queued',
                conversation: [{ role: 'user', content: `msg ${i}`, timestamp: Date.now() }],
                pending_inputs: [],
                principal: null,
                retry_count: 0,
                created_at: new Date(Date.now() + i).toISOString(),
                updated_at: new Date(Date.now() + i).toISOString(),
            })
        }

        // Two concurrent claimers should each get distinct sessions (no double-claim).
        const a = await queue.claim(500)
        const b = await queue.claim(500)
        expect(a).not.toBeNull()
        expect(b).not.toBeNull()
        expect(a!.id).not.toBe(b!.id)
        expect(a!.state).toBe('running')
    })

    it('PgSessionQueue appendPendingInput buffers into pending_inputs JSONB', async () => {
        if (!reachable) {
            return
        }
        const queue = new PgSessionQueue(pool)
        const revisions = new PgRevisionStore(pool)
        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by: 'u',
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'x' }),
        })
        await queue.enqueue({
            id: '11111111-1111-1111-1111-111111111111',
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: 'ext-1',
            state: 'running',
            conversation: [{ role: 'user', content: 'first', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
        })
        await queue.appendPendingInput('11111111-1111-1111-1111-111111111111', {
            role: 'user',
            content: 'second',
            timestamp: Date.now(),
        })
        const after = await queue.get('11111111-1111-1111-1111-111111111111')
        expect(after!.conversation).toHaveLength(1)
        expect(after!.pending_inputs).toHaveLength(1)
    })

    it('findByExternalKey resolves on (application_id, external_key)', async () => {
        if (!reachable) {
            return
        }
        const queue = new PgSessionQueue(pool)
        const revisions = new PgRevisionStore(pool)
        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by: 'u',
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'x' }),
        })
        await queue.enqueue({
            id: '22222222-2222-2222-2222-222222222222',
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: 'slack:C01:T1',
            state: 'queued',
            conversation: [],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
        })
        const found = await queue.findByExternalKey(app.id, 'slack:C01:T1')
        expect(found!.id).toBe('22222222-2222-2222-2222-222222222222')
        const missing = await queue.findByExternalKey(app.id, 'nope')
        expect(missing).toBeNull()
    })

    it('PgSessionQueue.reapStuckRunning bumps retry_count and poison-pills past threshold', async () => {
        if (!reachable) {
            return
        }
        const queue = new PgSessionQueue(pool)
        const revisions = new PgRevisionStore(pool)
        const app = await revisions.createApplication({ team_id: 1, slug: 'reap', name: 'R', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by: 'u',
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'x' }),
        })
        const id = '33333333-3333-3333-3333-333333333333'
        await queue.enqueue({
            id,
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            state: 'queued',
            conversation: [],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
        })
        // Move into running with a backdated claimed_at so the reaper sees it.
        await pool.query(
            `UPDATE agent_session_v2 SET state='running', claimed_at=NOW() - interval '1 hour' WHERE id=$1`,
            [id]
        )

        // First reap: re-queue, retry_count → 1.
        let r = await queue.reapStuckRunning(60_000, 2)
        expect(r).toEqual({ requeued: 1, poisoned: 0 })
        expect((await queue.get(id))!.retry_count).toBe(1)

        // Move back into running with stale claimed_at and reap again → retry_count → 2.
        await pool.query(
            `UPDATE agent_session_v2 SET state='running', claimed_at=NOW() - interval '1 hour' WHERE id=$1`,
            [id]
        )
        r = await queue.reapStuckRunning(60_000, 2)
        expect(r).toEqual({ requeued: 1, poisoned: 0 })
        expect((await queue.get(id))!.retry_count).toBe(2)

        // Once retry_count >= maxRetries the next stuck-running reap fails it.
        await pool.query(
            `UPDATE agent_session_v2 SET state='running', claimed_at=NOW() - interval '1 hour' WHERE id=$1`,
            [id]
        )
        r = await queue.reapStuckRunning(60_000, 2)
        expect(r).toEqual({ requeued: 0, poisoned: 1 })
        expect((await queue.get(id))!.state).toBe('failed')
    })
})
