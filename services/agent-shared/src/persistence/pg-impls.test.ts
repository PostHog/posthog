/**
 * Real Postgres tests against agent_runtime_queue_test. Schema is recreated
 * per test via @posthog/agent-migrations `reset()` — single source of
 * truth for the v2 platform schema.
 *
 * The test database is provided by the local hogli dev stack
 * (see services/agent-tests/.. for setup). We probe and skip the suite if
 * the database isn't reachable.
 */

import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'

import { reset } from '@posthog/agent-migrations'

import { EncryptedFields } from '../runtime/encryption'
import { PgSandboxInstanceStore } from '../sandbox/sandbox-instance-store'
import { AgentSpecSchema, AssistantMessageRecord, EMPTY_USAGE_TOTAL } from '../spec/spec'
import { hashCanonicalArgs } from './approval-store'
import { PgIntegrationStore } from './integration-store'
import { PgApprovalStore } from './pg-approval-store'
import { PgSessionQueue } from './pg-queue'
import { PgRevisionStore } from './pg-revision-store'

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
        await reset({ databaseUrl: TEST_DB_URL })
    })

    afterAll(async () => {
        if (pool) {
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
            created_by_id: null,
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
            created_by_id: null,
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
            created_by_id: null,
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
                usage_total: { ...EMPTY_USAGE_TOTAL },
                acl: [],
                pending_elevation_requests: [],
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
            created_by_id: null,
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
            usage_total: { ...EMPTY_USAGE_TOTAL },
            acl: [],
            pending_elevation_requests: [],
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
            created_by_id: null,
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
            usage_total: { ...EMPTY_USAGE_TOTAL },
            acl: [],
            pending_elevation_requests: [],
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
            created_by_id: null,
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
            usage_total: { ...EMPTY_USAGE_TOTAL },
            acl: [],
            pending_elevation_requests: [],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
        })
        // Move into running with a backdated claimed_at so the reaper sees it.
        await pool.query(`UPDATE agent_session SET state='running', claimed_at=NOW() - interval '1 hour' WHERE id=$1`, [
            id,
        ])

        // First reap: re-queue, retry_count → 1.
        let r = await queue.reapStuckRunning(60_000, 2)
        expect(r).toEqual({ requeued: 1, poisoned: 0 })
        expect((await queue.get(id))!.retry_count).toBe(1)

        // Move back into running with stale claimed_at and reap again → retry_count → 2.
        await pool.query(`UPDATE agent_session SET state='running', claimed_at=NOW() - interval '1 hour' WHERE id=$1`, [
            id,
        ])
        r = await queue.reapStuckRunning(60_000, 2)
        expect(r).toEqual({ requeued: 1, poisoned: 0 })
        expect((await queue.get(id))!.retry_count).toBe(2)

        // Once retry_count >= maxRetries the next stuck-running reap fails it.
        await pool.query(`UPDATE agent_session SET state='running', claimed_at=NOW() - interval '1 hour' WHERE id=$1`, [
            id,
        ])
        r = await queue.reapStuckRunning(60_000, 2)
        expect(r).toEqual({ requeued: 0, poisoned: 1 })
        expect((await queue.get(id))!.state).toBe('failed')
    })

    it('PgSandboxInstanceStore round-trips create → markReady → markTerminated, and findStale picks up old rows', async () => {
        if (!reachable) {
            return
        }
        const store = new PgSandboxInstanceStore(pool)
        const row = await store.create({
            team_id: 1,
            application_id: '44444444-4444-4444-4444-444444444444',
            revision_id: '55555555-5555-5555-5555-555555555555',
            session_id: '66666666-6666-6666-6666-666666666666',
            provider_kind: 'docker',
        })
        expect(row.state).toBe('provisioning')

        await store.markReady(row.id, 'container-xyz')
        let after = await store.get(row.id)
        expect(after!.state).toBe('ready')
        expect(after!.provider_sandbox_id).toBe('container-xyz')

        // Force last_used_at into the past so findStale picks it up.
        await pool.query(`UPDATE agent_sandbox_instance SET last_used_at = NOW() - interval '1 hour' WHERE id = $1`, [
            row.id,
        ])
        const stales = await store.findStale(60_000)
        expect(stales).toHaveLength(1)
        expect(stales[0].id).toBe(row.id)
        expect(stales[0].provider_sandbox_id).toBe('container-xyz')

        await store.markTerminated(row.id)
        after = await store.get(row.id)
        expect(after!.state).toBe('terminated')
        expect(after!.terminated_at).not.toBeNull()
        // findStale now ignores it — terminated is out of the alive set.
        expect(await store.findStale(60_000)).toHaveLength(0)
    })

    it('PgApprovalStore: dedupes queued rows by canonical args hash; new row after rejection', async () => {
        if (!reachable) {
            return
        }
        // Need a real session (FK target). Mint application + revision + session.
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        const app = await revisions.createApplication({ team_id: 1, slug: 'ap', name: 'Ap', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'x' }),
        })
        const sessionId = randomUUID()
        await queue.enqueue({
            id: sessionId,
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            state: 'running',
            conversation: [],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            usage_total: { ...EMPTY_USAGE_TOTAL },
            acl: [],
            pending_elevation_requests: [],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
        })

        const store = new PgApprovalStore(pool)
        const asstMsg: AssistantMessageRecord = {
            role: 'assistant',
            content: [{ type: 'text', text: 'about to delete' }],
            timestamp: Date.now(),
        }
        const baseInput = {
            session_id: sessionId,
            application_id: app.id,
            team_id: 1,
            revision_id: rev.id,
            turn: 1,
            tool_call_id: 'tc_1',
            tool_name: '@posthog/team-delete',
            proposed_args: { team_id: 42, dry_run: false },
            assistant_message: asstMsg,
            approver_scope: { approvers: ['team_admins'], allow_edit: false, allow_agent_approver: false },
            expires_at: new Date(Date.now() + 60_000).toISOString(),
        }

        const first = await store.upsertQueued({ id: randomUUID(), ...baseInput })
        expect(first.deduped).toBe(false)

        // Reordered args → same hash → deduped to the same row.
        const second = await store.upsertQueued({
            id: randomUUID(),
            ...baseInput,
            proposed_args: { dry_run: false, team_id: 42 },
        })
        expect(second.deduped).toBe(true)
        expect(second.request.id).toBe(first.request.id)

        // Reject the first, then re-issue → fresh row.
        await store.markRejected(first.request.id, {
            decided_by: randomUUID(),
            decided_at: new Date().toISOString(),
            reason: 'too risky',
        })
        const third = await store.upsertQueued({ id: randomUUID(), ...baseInput })
        expect(third.deduped).toBe(false)
        expect(third.request.id).not.toBe(first.request.id)

        // Lookup by canonical hash returns the most recent.
        const latest = await store.findLatestByArgs(
            sessionId,
            '@posthog/team-delete',
            hashCanonicalArgs(baseInput.proposed_args)
        )
        expect(latest!.id).toBe(third.request.id)
    })

    it('PgApprovalStore: decision lifecycle + expireQueued sweep', async () => {
        if (!reachable) {
            return
        }
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        const app = await revisions.createApplication({ team_id: 1, slug: 'lc', name: 'Lc', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'x' }),
        })
        const sessionId = randomUUID()
        await queue.enqueue({
            id: sessionId,
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            state: 'running',
            conversation: [],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            usage_total: { ...EMPTY_USAGE_TOTAL },
            acl: [],
            pending_elevation_requests: [],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
        })

        const store = new PgApprovalStore(pool)
        const asstMsg: AssistantMessageRecord = {
            role: 'assistant',
            content: [{ type: 'text', text: 'deciding' }],
            timestamp: Date.now(),
        }
        const baseInput = {
            session_id: sessionId,
            application_id: app.id,
            team_id: 1,
            revision_id: rev.id,
            turn: 1,
            tool_call_id: 'tc_x',
            tool_name: 'tool.dispatch',
            assistant_message: asstMsg,
            approver_scope: { approvers: ['team_admins'], allow_edit: false, allow_agent_approver: false },
            expires_at: new Date(Date.now() + 60_000).toISOString(),
        }

        // Approve → dispatch success path.
        const okReq = await store.upsertQueued({ id: randomUUID(), ...baseInput, proposed_args: { v: 1 } })
        const approving = await store.markApproving(okReq.request.id, {
            decided_by: randomUUID(),
            decided_at: new Date().toISOString(),
        })
        expect(approving!.state).toBe('approving')
        const dispatched = await store.markDispatched(okReq.request.id, { result: { ok: true } })
        expect(dispatched!.state).toBe('dispatched')
        expect(dispatched!.dispatch_outcome).toEqual({ result: { ok: true } })

        // Approve → dispatch failure path.
        const failReq = await store.upsertQueued({ id: randomUUID(), ...baseInput, proposed_args: { v: 2 } })
        await store.markApproving(failReq.request.id, {
            decided_by: randomUUID(),
            decided_at: new Date().toISOString(),
        })
        const failed = await store.markDispatched(failReq.request.id, { error: 'boom' })
        expect(failed!.state).toBe('dispatched_failed')

        // expireQueued only flips queued rows past expires_at.
        const ttlReq = await store.upsertQueued({
            id: randomUUID(),
            ...baseInput,
            proposed_args: { v: 3 },
            expires_at: new Date(Date.now() - 1000).toISOString(),
        })
        const expired = await store.expireQueued(new Date().toISOString())
        expect(expired.map((r) => r.id)).toContain(ttlReq.request.id)
        expect((await store.get(ttlReq.request.id))!.state).toBe('expired')

        // Listing by session returns all rows, newest first.
        const all = await store.listBySession(sessionId)
        expect(all.length).toBeGreaterThanOrEqual(3)
    })

    it('PgIntegrationStore reads + decrypts posthog_integration rows', async () => {
        if (!reachable) {
            return
        }
        // The test DB is the runtime queue DB which @posthog/agent-migrations
        // owns. posthog_integration lives in the main posthog DB in prod;
        // we recreate a minimal slice here so the store has something to
        // read from. Mirrors the existing harness pattern for agent_revision.
        await pool.query(`
            CREATE TABLE IF NOT EXISTS posthog_integration (
                id BIGSERIAL PRIMARY KEY,
                team_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                integration_id TEXT NOT NULL,
                sensitive_config TEXT,
                config JSONB DEFAULT '{}'::jsonb
            )
        `)
        await pool.query('TRUNCATE posthog_integration')

        const encryption = new EncryptedFields('test-salt-key-only-for-test')
        const slackBlob = encryption.encrypt(
            JSON.stringify({ access_token: 'xoxb-acme', refresh_token: 'r1', scopes: ['chat:write'] })
        )
        const githubBlob = encryption.encrypt(JSON.stringify({ access_token: 'gh_acme' }))
        await pool.query(
            `INSERT INTO posthog_integration (team_id, kind, integration_id, sensitive_config)
             VALUES (7, 'slack', 'T01ACME', $1),
                    (7, 'github', 'acme-org', $2)`,
            [slackBlob, githubBlob]
        )

        const store = new PgIntegrationStore(pool, encryption)

        // Direct lookup by natural key returns decrypted credentials.
        const slack = await store.get(7, 'slack', 'T01ACME')
        expect(slack?.access_token).toBe('xoxb-acme')
        expect(slack?.refresh_token).toBe('r1')
        expect(slack?.metadata).toEqual({ scopes: ['chat:write'] })

        // Missing rows return null.
        expect(await store.get(7, 'slack', 'NOT_THERE')).toBeNull()
        expect(await store.get(99, 'slack', 'T01ACME')).toBeNull()

        // resolveForSpec returns a `<kind>:<integration_id>`-keyed map.
        const map = await store.resolveForSpec(7, ['slack', 'github', 'linear'])
        expect(Object.keys(map).sort()).toEqual(['github:acme-org', 'slack:T01ACME'])
        expect(map['github:acme-org'].access_token).toBe('gh_acme')

        // Rows with undecodable sensitive_config (corrupted ciphertext, key
        // rotated past it) are silently omitted, mirroring Django's
        // ignore_decrypt_errors behaviour. The store doesn't crash the
        // resolver path.
        await pool.query(
            `INSERT INTO posthog_integration (team_id, kind, integration_id, sensitive_config)
             VALUES (7, 'slack', 'T02BAD', $1)`,
            ['gAAAAA-not-a-real-token']
        )
        const slacks = await store.list(7, 'slack')
        expect(slacks.map((r) => r.integration_id).sort()).toEqual(['T01ACME'])
    })
})
