import type { Principal, ServicePrincipal } from '@repo/ass-server/types'
/**
 * Stage D end-to-end harness for the auth + identity refactor described in
 * agent-stack/docs/auth-and-identity.md. Boots agent-ingress in-process via
 * supertest, hits a real PostHog Postgres + queue Postgres (the local DBs
 * `hogli start` provides), and validates every auth policy + identity flow.
 *
 * Skipped automatically when the DBs aren't reachable, so this is safe to run
 * in environments without hogli.
 *
 * Fixtures live under team_id = 1 (the default project), addressed by
 * `e2e-auth-*` slug prefixes so cleanup is precise. All test-created rows
 * are deleted in afterAll regardless of success/failure.
 */
import { createHmac } from 'node:crypto'
import { Pool } from 'pg'
import supertest from 'supertest'
import type { Express } from 'ultimate-express'

import {
    ApplicationsRepository,
    EncryptedFields,
    IdentitiesRepository,
    InMemorySessionBus,
    PosthogDbClient,
    SessionQueueManager,
} from '@posthog/agent-core'

import { RevisionResolver } from './resolver'
import { ServerDeps, buildServer } from './server'

const POSTHOG_DB_URL = process.env.POSTHOG_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/posthog'
const QUEUE_DB_URL =
    process.env.AGENT_RUNTIME_QUEUE_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue'
const ENCRYPTION_SALT = '00beef0000beef0000beef0000beef00'

const TEAM_ID = 1
const TEAM_SECRET = 'e2e-team-secret-deadbeef'
const INTERNAL_HEADER = 'x-posthog-internal'
const INTERNAL_SECRET = 'e2e-internal-secret'
const SHARED_SECRET_ENV = 'E2E_SHARED_SECRET'
const SHARED_SECRET_VALUE = 'e2e-shared-secret-cafebabe'
const SLACK_SIGNING_SECRET = 'e2e-slack-signing'
const SLACK_TRUSTED_WORKSPACE = 'T_E2E_TRUSTED'
const SLACK_UNTRUSTED_WORKSPACE = 'T_E2E_UNTRUSTED'
const IDENTITY_SPACE_NAME = 'e2e-slack'

const SLUG_PREFIX = 'e2e-auth-'

/* ===== Skip guard ===== */
// Probe both DBs synchronously at module load. If either is unreachable, mark
// the suite as `describe.skip` so the file is no-op without hogli. We do this
// in `beforeAll` rather than top-level so jest doesn't bail on import.

let dbReachable = false
let teamSecretWasSetByUs = false
let identitySpaceId: string | null = null
const createdRevisionIds: string[] = []
const createdApplicationIds: string[] = []
const createdSessionIds: string[] = []
const createdAgentUserIds: string[] = []

const posthogPool = new Pool({ connectionString: POSTHOG_DB_URL })
const queuePool = new Pool({ connectionString: QUEUE_DB_URL })

beforeAll(async () => {
    try {
        await posthogPool.query('SELECT 1')
        await queuePool.query('SELECT 1')
        dbReachable = true
    } catch {
        // eslint-disable-next-line no-console
        console.warn('[auth.e2e] DBs unreachable, skipping suite')
        return
    }

    // 1. Set the team's secret_api_token so verifyTokenIdentity recognises us.
    const { rows: priorSecret } = await posthogPool.query<{ secret_api_token: string | null }>(
        `SELECT secret_api_token FROM posthog_team WHERE id = $1`,
        [TEAM_ID]
    )
    if (priorSecret[0]?.secret_api_token !== TEAM_SECRET) {
        await posthogPool.query(`UPDATE posthog_team SET secret_api_token = $1 WHERE id = $2`, [TEAM_SECRET, TEAM_ID])
        teamSecretWasSetByUs = true
    }

    // 2. Create one IdentitySpace for the Slack agents. Soft-delete idempotent.
    await posthogPool.query(`DELETE FROM agent_stack_identityspace WHERE team_id = $1 AND name = $2`, [
        TEAM_ID,
        IDENTITY_SPACE_NAME,
    ])
    const { rows: spaceRows } = await posthogPool.query<{ id: string }>(
        `INSERT INTO agent_stack_identityspace (id, team_id, name, deleted, created_at, updated_at)
         VALUES (gen_random_uuid(), $1, $2, FALSE, NOW(), NOW())
         RETURNING id::text AS id`,
        [TEAM_ID, IDENTITY_SPACE_NAME]
    )
    identitySpaceId = spaceRows[0].id

    // 3. Create test apps. One per auth policy + the Slack identity ones.
    await createApp('public', { auth: { mode: 'public' } })
    await createApp(
        'pat',
        {
            auth: {
                mode: 'public',
            } /* top_level_config.auth is parsed by ResolvedRevision; agent.ts auth lives in topLevelConfig.auth */,
        },
        agentYaml({ type: 'pat' })
    )
    await createApp('internal', { auth: { mode: 'public' } }, agentYaml({ type: 'posthog_internal' }))
    await createApp(
        'shared',
        { auth: { mode: 'public' } },
        agentYaml({ type: 'shared_secret', secret_name: SHARED_SECRET_ENV, header: 'x-shared-secret' })
    )
    await createApp(
        'slack-trusted',
        { auth: { mode: 'webhook_signature', provider: 'slack', secret: SLACK_SIGNING_SECRET } },
        slackAgentYaml({ trusted_workspaces: [SLACK_TRUSTED_WORKSPACE] })
    )
    await createApp(
        'slack-b2c',
        { auth: { mode: 'webhook_signature', provider: 'slack', secret: SLACK_SIGNING_SECRET } },
        slackAgentYaml({ trusted_workspaces: '*' })
    )
}, 30_000)

afterAll(async () => {
    if (!dbReachable) {
        await posthogPool.end()
        await queuePool.end()
        return
    }
    // Order matters: identities → users → space → sessions → revisions → apps → restore team secret.
    if (createdSessionIds.length > 0) {
        await queuePool.query(`DELETE FROM agent_sessions WHERE id = ANY($1::uuid[])`, [createdSessionIds])
    }
    if (identitySpaceId) {
        await posthogPool.query(`DELETE FROM agent_stack_useridentity WHERE space_id = $1`, [identitySpaceId])
        await posthogPool.query(`DELETE FROM agent_stack_agentuser WHERE space_id = $1`, [identitySpaceId])
        await posthogPool.query(`DELETE FROM agent_stack_identityspace WHERE id = $1`, [identitySpaceId])
    }
    if (createdRevisionIds.length > 0) {
        await posthogPool.query(`DELETE FROM agent_stack_agentapplicationrevision WHERE id = ANY($1::uuid[])`, [
            createdRevisionIds,
        ])
    }
    if (createdApplicationIds.length > 0) {
        await posthogPool.query(`DELETE FROM agent_stack_agentapplication WHERE id = ANY($1::uuid[])`, [
            createdApplicationIds,
        ])
    }
    if (teamSecretWasSetByUs) {
        await posthogPool.query(`UPDATE posthog_team SET secret_api_token = NULL WHERE id = $1`, [TEAM_ID])
    }
    await posthogPool.end()
    await queuePool.end()
}, 30_000)

/* ===== Fixture builders ===== */

function agentYaml(auth: Record<string, unknown>): Record<string, unknown> {
    // Mirrors what `agentDefinitionToAssYaml` emits. The runtime path only
    // reads `auth` (consumed by ass-server's checkAuth) and `identity`, plus
    // `triggers` for routing — keep this minimal.
    return {
        name: 'e2e',
        slug: 'placeholder',
        prompt: 'you are an e2e bot',
        visibility: 'private',
        auth,
        triggers: [{ id: 'http', type: 'http_invoke' }],
        tools: [],
        skills: [],
        required_secrets: [],
    }
}

function slackAgentYaml(source: { trusted_workspaces: '*' | string[] }): Record<string, unknown> {
    return {
        name: 'e2e-slack',
        slug: 'placeholder',
        prompt: 'you are a slack bot',
        visibility: 'private',
        auth: { type: 'webhook_signature', provider: 'slack' },
        identity: { space: IDENTITY_SPACE_NAME, source: { provider: 'slack', ...source } },
        triggers: [
            {
                id: 'slack',
                type: 'slack_event',
                events: ['app_mention'],
                signing_secret_name: 'SLACK_SIGNING_SECRET',
            },
        ],
        tools: [],
        skills: [],
        required_secrets: [],
    }
}

async function createApp(
    policySuffix: string,
    topLevelAuth: Record<string, unknown>,
    parsedManifest: Record<string, unknown> | null = null
): Promise<{ applicationId: string; slug: string }> {
    const slug = `${SLUG_PREFIX}${policySuffix}`
    // Idempotent — drop any prior fixture with this slug.
    await posthogPool.query(
        `DELETE FROM agent_stack_agentapplicationrevision WHERE application_id IN (SELECT id FROM agent_stack_agentapplication WHERE slug = $1)`,
        [slug]
    )
    await posthogPool.query(`DELETE FROM agent_stack_agentapplication WHERE slug = $1`, [slug])

    const { rows: appRows } = await posthogPool.query<{ id: string }>(
        `INSERT INTO agent_stack_agentapplication (id, team_id, name, slug, description, deleted, created_at, updated_at)
         VALUES (gen_random_uuid(), $1, $2, $3, '', FALSE, NOW(), NOW())
         RETURNING id::text AS id`,
        [TEAM_ID, `e2e-${policySuffix}`, slug]
    )
    const applicationId = appRows[0].id
    createdApplicationIds.push(applicationId)

    const { rows: revRows } = await posthogPool.query<{ id: string }>(
        `INSERT INTO agent_stack_agentapplicationrevision
            (id, team_id, application_id, state, deployment_status, bundle_s3_key, bundle_size, bundle_sha256,
             top_level_config, parsed_manifest, created_at, updated_at)
         VALUES (gen_random_uuid(), $1, $2, 'ready', 'live', 's3://e2e', 0, '',
                 $3::jsonb, $4::jsonb, NOW(), NOW())
         RETURNING id::text AS id`,
        [TEAM_ID, applicationId, JSON.stringify({ auth: topLevelAuth.auth, ...parsedManifest }), null]
    )
    createdRevisionIds.push(revRows[0].id)
    return { applicationId, slug }
}

/* ===== Server builder ===== */

interface Harness {
    app: Express
    queue: SessionQueueManager
    bus: InMemorySessionBus
    posthogDb: PosthogDbClient
}

async function buildHarness(): Promise<Harness> {
    const posthogDb = new PosthogDbClient({ dbUrl: POSTHOG_DB_URL })
    const encryption = new EncryptedFields(ENCRYPTION_SALT)
    const repository = new ApplicationsRepository({ db: posthogDb, encryption })
    const identities = new IdentitiesRepository({ db: posthogDb })
    const resolver = new RevisionResolver({
        repository,
        ttlMs: 0, // disable cache for tests
        domainSuffix: '.e2e.test',
    })
    const queue = new SessionQueueManager({ pool: { dbUrl: QUEUE_DB_URL } })
    await queue.connect()
    const bus = new InMemorySessionBus()
    const deps: ServerDeps = {
        queue,
        bus,
        resolver,
        repository,
        identities,
        domainSuffix: '.e2e.test',
        routingMode: 'domain',
        // posthog_internal verifier: accept requests carrying the test header.
        verifyPostHogInternal: async (req): Promise<ServicePrincipal | null> => {
            return req.headers[INTERNAL_HEADER] === INTERNAL_SECRET
                ? { kind: 'service', orgId: String(TEAM_ID), caller: 'posthog-internal' }
                : null
        },
        // shared_secret callback: serve the configured value when asked for the env name.
        loadSecret: async (name) => {
            if (name === SHARED_SECRET_ENV) {
                return SHARED_SECRET_VALUE
            }
            if (name === 'SLACK_SIGNING_SECRET') {
                return SLACK_SIGNING_SECRET
            }
            return null
        },
    }
    const app = buildServer(deps)
    // ultimate-express needs to be listening before supertest can hit it.
    await new Promise<void>((resolve, reject) => {
        try {
            app.listen(0, () => resolve())
        } catch (err) {
            reject(err)
        }
    })
    return { app, queue, bus, posthogDb }
}

function host(suffix: string): string {
    return `${SLUG_PREFIX}${suffix}.e2e.test`
}

function signSlack(body: string, timestamp: string): string {
    return 'v0=' + createHmac('sha256', SLACK_SIGNING_SECRET).update(`v0:${timestamp}:${body}`).digest('hex')
}

function postSlack(harness: Harness, suffix: string, payload: Record<string, unknown>): supertest.Test {
    const body = JSON.stringify(payload)
    const ts = String(Math.floor(Date.now() / 1000))
    return supertest(harness.app)
        .post('/webhooks/slack')
        .set('x-original-host', host(suffix))
        .set('x-slack-signature', signSlack(body, ts))
        .set('x-slack-request-timestamp', ts)
        .set('content-type', 'application/json')
        .send(body)
}

async function getStampedPrincipal(harness: Harness, sessionId: string): Promise<Principal | null> {
    createdSessionIds.push(sessionId)
    return (await harness.queue.getPrincipal(sessionId)) as Principal | null
}

/* ===== Tests ===== */

const describeIfDb = process.env.AGENT_E2E_SKIP === '1' ? describe.skip : describe

describeIfDb('agent-ingress auth + identity (e2e against real DBs)', () => {
    let harness: Harness

    beforeAll(async () => {
        if (!dbReachable) {
            return
        }
        harness = await buildHarness()
    }, 30_000)

    afterAll(async () => {
        if (!dbReachable || !harness) {
            return
        }
        await harness.queue.disconnect()
        await harness.bus.disconnect()
        await harness.posthogDb.disconnect()
    }, 30_000)

    /* --- public agent: baseline that all the plumbing works --- */

    it('public agent enqueues without auth and stamps no principal', async () => {
        if (!dbReachable) {
            return
        }
        const res = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', host('public'))
            .set('content-type', 'application/json')
            .send({})
        expect(res.status).toBe(202)
        const principal = await getStampedPrincipal(harness, res.body.sessionId)
        expect(principal).toBeNull()
    })

    /* --- pat --- */

    it('pat: correct token → 202 + service principal stamped', async () => {
        if (!dbReachable) {
            return
        }
        const res = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', host('pat'))
            .set('authorization', `Bearer ${TEAM_SECRET}`)
            .send({})
        expect(res.status).toBe(202)
        const principal = await getStampedPrincipal(harness, res.body.sessionId)
        expect(principal).toEqual({ kind: 'service', orgId: String(TEAM_ID), caller: 'team-secret' })
    })

    it('pat: wrong token → 401', async () => {
        if (!dbReachable) {
            return
        }
        const res = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', host('pat'))
            .set('authorization', 'Bearer wrong-token')
            .send({})
        expect(res.status).toBe(401)
    })

    it('pat: missing token → 401', async () => {
        if (!dbReachable) {
            return
        }
        const res = await supertest(harness.app).post('/run').set('x-original-host', host('pat')).send({})
        expect(res.status).toBe(401)
    })

    /* --- posthog_internal --- */

    it('posthog_internal: correct header → 202 + posthog-internal principal', async () => {
        if (!dbReachable) {
            return
        }
        const res = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', host('internal'))
            .set(INTERNAL_HEADER, INTERNAL_SECRET)
            .send({})
        expect(res.status).toBe(202)
        const principal = await getStampedPrincipal(harness, res.body.sessionId)
        expect(principal).toEqual({ kind: 'service', orgId: String(TEAM_ID), caller: 'posthog-internal' })
    })

    it('posthog_internal: missing header → 403', async () => {
        if (!dbReachable) {
            return
        }
        const res = await supertest(harness.app).post('/run').set('x-original-host', host('internal')).send({})
        expect(res.status).toBe(403)
    })

    /* --- shared_secret --- */

    it('shared_secret: correct header → 202 + synthesised principal', async () => {
        if (!dbReachable) {
            return
        }
        const res = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', host('shared'))
            .set('x-shared-secret', SHARED_SECRET_VALUE)
            .send({})
        expect(res.status).toBe(202)
        const principal = await getStampedPrincipal(harness, res.body.sessionId)
        expect(principal).toEqual({
            kind: 'service',
            orgId: 'shared-secret',
            caller: `shared_secret:${SHARED_SECRET_ENV}`,
        })
    })

    it('shared_secret: wrong value → 401', async () => {
        if (!dbReachable) {
            return
        }
        const res = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', host('shared'))
            .set('x-shared-secret', 'nope')
            .send({})
        expect(res.status).toBe(401)
    })

    it('shared_secret: missing header → 401', async () => {
        if (!dbReachable) {
            return
        }
        const res = await supertest(harness.app).post('/run').set('x-original-host', host('shared')).send({})
        expect(res.status).toBe(401)
    })

    /* --- slack identity --- */

    it('slack (trusted workspace): resolves identity, stamps UserPrincipal, persists AgentUser row', async () => {
        if (!dbReachable) {
            return
        }
        const payload = {
            type: 'event_callback',
            team_id: SLACK_TRUSTED_WORKSPACE,
            event: { type: 'app_mention', channel: 'C1', user: 'U_SLACK_A', text: '<@bot> hi' },
        }
        const res = await postSlack(harness, 'slack-trusted', payload)
        expect(res.status).toBe(202)
        const principal = await getStampedPrincipal(harness, res.body.sessionId)
        expect(principal).toMatchObject({
            kind: 'user',
            spaceId: identitySpaceId,
            provider: 'slack',
            providerAccountId: SLACK_TRUSTED_WORKSPACE,
            providerSubject: 'U_SLACK_A',
        })
        // Persistence side-effect: the AgentUser row exists in Django DB.
        const { rows } = await posthogPool.query<{ id: string }>(
            `SELECT au.id::text AS id
             FROM agent_stack_useridentity ui
             JOIN agent_stack_agentuser au ON au.id = ui.user_id
             WHERE ui.space_id = $1 AND ui.provider = 'slack'
               AND ui.provider_account_id = $2 AND ui.provider_subject = 'U_SLACK_A'`,
            [identitySpaceId, SLACK_TRUSTED_WORKSPACE]
        )
        expect(rows).toHaveLength(1)
        createdAgentUserIds.push(rows[0].id)
        expect((principal as { userId: string }).userId).toBe(rows[0].id)
    })

    it('slack (untrusted workspace) on trusted-list agent → 403', async () => {
        if (!dbReachable) {
            return
        }
        const payload = {
            type: 'event_callback',
            team_id: SLACK_UNTRUSTED_WORKSPACE,
            event: { type: 'app_mention', channel: 'C1', user: 'U_SLACK_X', text: 'hi' },
        }
        const res = await postSlack(harness, 'slack-trusted', payload)
        expect(res.status).toBe(403)
    })

    it('slack b2c (`*` allowlist) accepts any workspace, gives distinct users their own AgentUser', async () => {
        if (!dbReachable) {
            return
        }
        const a = await postSlack(harness, 'slack-b2c', {
            type: 'event_callback',
            team_id: 'T_B2C_X',
            event: { type: 'app_mention', user: 'U_X', channel: 'C', text: 'hi' },
        })
        const b = await postSlack(harness, 'slack-b2c', {
            type: 'event_callback',
            team_id: 'T_B2C_Y',
            event: { type: 'app_mention', user: 'U_Y', channel: 'C', text: 'hi' },
        })
        expect(a.status).toBe(202)
        expect(b.status).toBe(202)
        const pa = (await getStampedPrincipal(harness, a.body.sessionId)) as { userId: string }
        const pb = (await getStampedPrincipal(harness, b.body.sessionId)) as { userId: string }
        expect(pa.userId).not.toBe(pb.userId)
    })

    it('slack identity: same (workspace, user) is the same AgentUser across sessions (stable id)', async () => {
        if (!dbReachable) {
            return
        }
        const event = {
            type: 'event_callback',
            team_id: SLACK_TRUSTED_WORKSPACE,
            event: { type: 'app_mention', user: 'U_STABLE', channel: 'C', text: 'hi' },
        }
        const first = await postSlack(harness, 'slack-trusted', event)
        const second = await postSlack(harness, 'slack-trusted', event)
        expect(first.status).toBe(202)
        expect(second.status).toBe(202)
        const p1 = (await getStampedPrincipal(harness, first.body.sessionId)) as { userId: string }
        const p2 = (await getStampedPrincipal(harness, second.body.sessionId)) as { userId: string }
        expect(p1.userId).toBe(p2.userId)
    })

    /* --- strict principal-match on session control --- */

    it('control: /send with same pat as session creator → 202 (strict-match passes)', async () => {
        if (!dbReachable) {
            return
        }
        const run = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', host('pat'))
            .set('authorization', `Bearer ${TEAM_SECRET}`)
            .send({})
        expect(run.status).toBe(202)
        createdSessionIds.push(run.body.sessionId)
        const send = await supertest(harness.app)
            .post(`/send/${run.body.sessionId}`)
            .set('x-original-host', host('pat'))
            .set('authorization', `Bearer ${TEAM_SECRET}`)
            .send({ content: 'follow-up' })
        expect(send.status).toBe(202)
    })

    it('control: /send with wrong pat → 401 (auth fails before strict-match)', async () => {
        if (!dbReachable) {
            return
        }
        const run = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', host('pat'))
            .set('authorization', `Bearer ${TEAM_SECRET}`)
            .send({})
        createdSessionIds.push(run.body.sessionId)
        const send = await supertest(harness.app)
            .post(`/send/${run.body.sessionId}`)
            .set('x-original-host', host('pat'))
            .set('authorization', 'Bearer wrong')
            .send({ content: 'x' })
        expect(send.status).toBe(401)
    })

    it('control: /send on a slack-started session with pat falls back to control auth but mismatches → 403', async () => {
        if (!dbReachable) {
            return
        }
        // The session is started by a Slack webhook (user principal). The
        // control endpoint for a `webhook_signature` agent falls back to
        // `pat` (you can't sign a /send), so presenting the correct team PAT
        // authenticates. But strict-match then rejects because the
        // service-principal caller doesn't equal the session's user-principal.
        const run = await postSlack(harness, 'slack-trusted', {
            type: 'event_callback',
            team_id: SLACK_TRUSTED_WORKSPACE,
            event: { type: 'app_mention', user: 'U_OWNER', channel: 'C', text: 'hi' },
        })
        expect(run.status).toBe(202)
        createdSessionIds.push(run.body.sessionId)
        const send = await supertest(harness.app)
            .post(`/send/${run.body.sessionId}`)
            .set('x-original-host', host('slack-trusted'))
            .set('authorization', `Bearer ${TEAM_SECRET}`)
            .send({ content: 'x' })
        expect(send.status).toBe(403)
    })
})
