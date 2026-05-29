/**
 * Real-Postgres tests for the agent-memory slice, against
 * agent_runtime_queue_test. Skips if the DB is unreachable (mirrors
 * pg-impls.test.ts).
 *
 * NOTE (slice): schema is applied inline from ./schema rather than via
 * @posthog/agent-migrations reset(). The production graduation moves the
 * agent_memory_* tables into a migration there (see the plan doc).
 */

import { Pool } from 'pg'

import { Memory, type Scope } from './memory'
import { FullTextRecaller } from './recaller'
import { applySchema, dropSchema } from './schema'

const TEST_DB_URL =
    process.env.AGENT_MEMORY_DB_URL ??
    process.env.AGENT_TEST_DB_URL ??
    'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

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

const triager: Scope = { teamId: 42, applicationId: 'triager' }
const resolver: Scope = { teamId: 42, applicationId: 'resolver' }
const otherTeam: Scope = { teamId: 99, applicationId: 'triager' }

async function seedIncidents(mem: Memory): Promise<number> {
    await mem.createPattern(triager, {
        name: 'incidents',
        doctrine: 'Production incidents with root cause.',
        facets: [
            { name: 'title', type: 'text' },
            { name: 'detail', type: 'text' },
            { name: 'root_cause', type: 'text' },
        ],
    })
    const e = await mem.create(triager, 'incidents', {
        title: 'Database connection pool exhausted',
        detail: 'API latency spiked; Postgres rejected new connections under load.',
        root_cause: 'pgbouncer pool size too low for the worker count',
    })
    await mem.create(triager, 'incidents', {
        title: 'Slack notifications delayed',
        detail: 'Alert messages arrived an hour late.',
        root_cause: 'rate limit on the Slack channel search endpoint',
    })
    return (e.data as { id: number }).id
}

const maybeDescribe = process.env.SKIP_PG_TESTS === '1' ? describe.skip : describe

maybeDescribe('agent memory (real PG)', () => {
    let pool: Pool
    let reachable = false
    let mem: Memory

    beforeAll(async () => {
        reachable = await isReachable()
        if (!reachable) {
            console.warn(`[memory.test] ${TEST_DB_URL} unreachable — skipping`)
            return
        }
        pool = new Pool({ connectionString: TEST_DB_URL, max: 4 })
    })

    beforeEach(async () => {
        if (!reachable) {
            return
        }
        await dropSchema(pool)
        await applySchema(pool)
        mem = new Memory(pool, new FullTextRecaller())
    })

    afterAll(async () => {
        if (pool) {
            await pool.end()
        }
    })

    it('creates a pattern with a creator-only write grant; rejects duplicates', async () => {
        if (!reachable) {
            return
        }
        const r = await mem.createPattern(triager, { name: 'notes', facets: [{ name: 'body', type: 'text' }] })
        expect(r.ok).toBe(true)
        const dup = await mem.createPattern(triager, { name: 'notes', facets: [{ name: 'body', type: 'text' }] })
        expect(dup.ok).toBe(false)
        expect(dup.error).toMatch(/already exists/)
    })

    it('rejects invalid pattern/facet names', async () => {
        if (!reachable) {
            return
        }
        expect((await mem.createPattern(triager, { name: 'Bad Name', facets: [{ name: 'b', type: 'text' }] })).ok).toBe(
            false
        )
        expect((await mem.createPattern(triager, { name: 'ok', facets: [{ name: 'Bad', type: 'text' }] })).ok).toBe(
            false
        )
    })

    it('write + query round-trips, and filters on facets', async () => {
        if (!reachable) {
            return
        }
        await seedIncidents(mem)
        const all = await mem.query(triager, 'incidents')
        expect((all.data as { count: number }).count).toBe(2)
        const filtered = await mem.query(triager, 'incidents', [{ field: 'title', op: '~', value: 'Slack' }])
        expect((filtered.data as { count: number }).count).toBe(1)
    })

    it('enforces the per-pattern allowlist: a non-granted agent gets no access', async () => {
        if (!reachable) {
            return
        }
        await seedIncidents(mem)
        const q = await mem.query(resolver, 'incidents')
        expect(q.ok).toBe(false)
        expect(q.error).toMatch(/no read access/)
        const p = await mem.prime(resolver, 'connection pool exhausted')
        expect((p.data as { count: number }).count).toBe(0)
    })

    it("cross-agent share: after a grant, the second agent can prime the first agent's memory", async () => {
        if (!reachable) {
            return
        }
        await seedIncidents(mem)
        const before = await mem.prime(resolver, 'postgres ran out of connections')
        expect((before.data as { count: number }).count).toBe(0)

        const g = await mem.grant(triager, { pattern: 'incidents', applicationId: 'resolver', access: 'read' })
        expect(g.ok).toBe(true)
        expect((g.data as { requires_approval_in_prod: boolean }).requires_approval_in_prod).toBe(true)

        const after = await mem.prime(resolver, 'postgres ran out of connections')
        const hits = (after.data as { results: { pattern: string }[] }).results
        expect(hits.length).toBeGreaterThan(0)
        expect(hits[0].pattern).toBe('incidents')
    })

    it('a read grant does not confer write', async () => {
        if (!reachable) {
            return
        }
        await seedIncidents(mem)
        await mem.grant(triager, { pattern: 'incidents', applicationId: 'resolver', access: 'read' })
        const w = await mem.create(resolver, 'incidents', { title: 'x', detail: 'y', root_cause: 'z' })
        expect(w.ok).toBe(false)
        expect(w.error).toMatch(/no write access/)
    })

    it('prime ranks a relevant cue above the noise and reports the ranker kind', async () => {
        if (!reachable) {
            return
        }
        const dbId = await seedIncidents(mem)
        const r = await mem.prime(triager, 'database ran out of connections under load')
        const data = r.data as { ranker: string; results: { id: number }[] }
        expect(data.ranker).toBe('fts-v0')
        expect(data.results[0].id).toBe(dbId)
    })

    it('expands one hop along links in prime (bidirectional)', async () => {
        if (!reachable) {
            return
        }
        const dbId = await seedIncidents(mem)
        await mem.createPattern(triager, {
            name: 'fixes',
            facets: [
                { name: 'title', type: 'text' },
                { name: 'change', type: 'text' },
            ],
        })
        const f = await mem.create(triager, 'fixes', {
            title: 'Raised pgbouncer pool size',
            change: 'default_pool_size 20 -> 80',
        })
        await mem.link(
            triager,
            { pattern: 'incidents', id: dbId },
            { pattern: 'fixes', id: (f.data as { id: number }).id },
            'resolved-by'
        )

        const r = await mem.prime(triager, 'connection pool problem')
        const top = (r.data as { results: { id: number; linked?: { pattern: string }[] }[] }).results.find(
            (x) => x.id === dbId
        )
        expect(top?.linked?.some((l) => l.pattern === 'fixes')).toBe(true)
    })

    it('optimistic locking rejects a stale update', async () => {
        if (!reachable) {
            return
        }
        const dbId = await seedIncidents(mem)
        const ok = await mem.update(triager, 'incidents', dbId, { title: 'updated' }, 0)
        expect(ok.ok).toBe(true)
        const stale = await mem.update(triager, 'incidents', dbId, { title: 'again' }, 0)
        expect(stale.ok).toBe(false)
        expect(stale.error).toMatch(/version conflict/)
    })

    it('archive removes an entry from query and prime', async () => {
        if (!reachable) {
            return
        }
        const dbId = await seedIncidents(mem)
        await mem.archive(triager, 'incidents', dbId)
        const q = await mem.query(triager, 'incidents')
        expect((q.data as { count: number }).count).toBe(1)
        const p = await mem.prime(triager, 'database connection pool exhausted')
        expect((p.data as { results: { id: number }[] }).results.find((x) => x.id === dbId)).toBeUndefined()
    })

    it('enforces cross-team isolation', async () => {
        if (!reachable) {
            return
        }
        await seedIncidents(mem)
        // team 99 has no patterns at all → no reach, even with the same app id.
        const q = await mem.query(otherTeam, 'incidents')
        expect(q.ok).toBe(false)
        const p = await mem.prime(otherTeam, 'connection pool exhausted')
        expect((p.data as { count: number }).count).toBe(0)
    })
})
