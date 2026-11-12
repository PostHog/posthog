// The `/v1/integrations/*` routes against a real Postgres in a container, with the local KMS.

import { PostgreSqlContainer, type StartedPostgreSqlContainer } from '@testcontainers/postgresql'
import type { Hono } from 'hono'
import { SignJWT } from 'jose'
import { type KeyObject, generateKeyPairSync, randomBytes } from 'node:crypto'
import { Pool } from 'pg'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { IntegrationKeyLoader } from '@/auth/integration-keys'
import { IntegrationVerifier, MAX_TOKEN_LIFETIME_SECONDS } from '@/auth/integrations'
import { JwtVerifier } from '@/auth/jwt'
import type { IntegrationOp } from '@/auth/policy'
import type { SigningKeyLoader } from '@/auth/registry'
import type { ReplayStore } from '@/auth/replay'
import { PostgresReplayStore } from '@/auth/replay-postgres'
import { INTEGRATIONS_AUDIENCE, type SigningKeys } from '@/auth/types'
import { Envelope } from '@/crypto/envelope'
import { LocalKms } from '@/crypto/local-kms'
import { type EncryptionContext, type Kms, KmsError } from '@/crypto/types'
import { deleteExpiredIdempotencyKeys } from '@/db/idempotency'
import { listIntegrations } from '@/db/integration-queries'
import { insertIntegration } from '@/db/integrations'
import { runMigrations } from '@/db/migrate'
import { createApp } from '@/http/app'
import { AuditQueue, insertAuditRows } from '@/integrations/audit'
import { IntegrationsService } from '@/integrations/service'
import { logger } from '@/lib/logging'
import { register } from '@/metrics'

const WEB = 'posthog-web-django'
const WORKER = 'temporal-worker-data-warehouse'
const CDP = 'cdp-api'
const REVERSE_SYNC = 'posthog-integrations-reverse-sync'
const BATCH_EXPORTS = 'temporal-worker-batch-exports'
const TASKS_AGENT = 'temporal-worker-tasks-agent'
const DEPLOYMENTS = [WEB, WORKER, CDP, REVERSE_SYNC, BATCH_EXPORTS, TASKS_AGENT]
const PAIRS: Record<string, { privateKey: KeyObject; publicKey: KeyObject }> = Object.fromEntries(
    DEPLOYMENTS.map((deployment) => [deployment, generateKeyPairSync('ed25519')])
)
const integrationLoader = new IntegrationKeyLoader('test')
integrationLoader.loadFrom(
    Object.fromEntries(
        DEPLOYMENTS.map((deployment) => [
            `${deployment}.pub`,
            PAIRS[deployment]!.publicKey.export({ type: 'spki', format: 'pem' }).toString(),
        ])
    )
)
const PLATFORM_KEYS: SigningKeys = { [WEB]: ['web-signing-key-fake'] }
const platformLoader = {
    entries: () => Object.entries(PLATFORM_KEYS),
    allowedSecrets: () => null,
} as unknown as SigningKeyLoader

const TEAM_A = 101
const TEAM_B = 202
const TEAM_C = 303
const REF_PATTERN = /^(0|[1-9][0-9]{0,18}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/

// Obviously fake values. The tests search every response and log line for them.
const ACCESS_TOKEN = 'fake-access-token-a1b2c3'
const REFRESH_TOKEN = 'fake-refresh-token-d4e5f6'
const CLIENT_SECRET = 'fake-client-secret-g7h8i9'
// Only resolve may return the access token. Nothing may ever return the other two.
const NEVER_RETURNED = [REFRESH_TOKEN, CLIENT_SECRET]

let container: StartedPostgreSqlContainer
let pool: Pool
let audit: AuditQueue
let app: Hono
let kms: Kms
const logLines: string[] = []
let jti = 0

interface TokenOptions {
    deployment?: string | undefined
    team?: number | null | undefined
    ops?: IntegrationOp[] | undefined
    kinds?: string[] | undefined
    refs?: string[] | undefined
    userId?: number | undefined
}

async function token(opts: TokenOptions = {}): Promise<string> {
    jti += 1
    const deployment = opts.deployment ?? WEB
    const claims: Record<string, unknown> = {
        jti: `e2e-token-${String(jti).padStart(10, '0')}`,
        ops: opts.ops ?? ['read'],
        caller: 'integrations-e2e',
    }
    if (opts.team !== null) {
        claims['owner'] = { type: 'team', id: opts.team ?? TEAM_A }
    }
    if (opts.kinds) {
        claims['kinds'] = opts.kinds
    }
    if (opts.refs) {
        claims['refs'] = opts.refs
    }
    if (opts.userId) {
        claims['user_id'] = opts.userId
    }
    const now = Math.floor(Date.now() / 1000)
    return new SignJWT(claims)
        .setProtectedHeader({ alg: 'EdDSA' })
        .setAudience(INTEGRATIONS_AUDIENCE)
        .setIssuedAt(now)
        .setExpirationTime(now + MAX_TOKEN_LIFETIME_SECONDS)
        .sign(PAIRS[deployment]!.privateKey)
}

interface CallOptions extends TokenOptions {
    body?: unknown
    headers?: Record<string, string>
    noToken?: boolean
    target?: Hono
}

interface CallResult {
    status: number
    json: any
    text: string
    headers: Headers
}

const responses: { path: string; text: string }[] = []

async function call(method: string, path: string, opts: CallOptions = {}): Promise<CallResult> {
    const headers: Record<string, string> = { ...opts.headers }
    if (!opts.noToken) {
        const route = path.split(/[/?]/)[1]
        const bodyRefs =
            typeof opts.body === 'object' && opts.body !== null && 'refs' in opts.body ? opts.body.refs : undefined
        const requestedRefs =
            route === 'batch-get' || route === 'resolve'
                ? bodyRefs
                : route && !['upsert', 'list-across-teams'].includes(route)
                  ? [route]
                  : undefined
        const refs =
            Array.isArray(requestedRefs) &&
            requestedRefs.length > 0 &&
            requestedRefs.length <= 200 &&
            requestedRefs.every((ref) => typeof ref === 'string' && REF_PATTERN.test(ref))
                ? (requestedRefs as string[])
                : route === 'batch-get' || route === 'resolve'
                  ? ['1']
                  : undefined
        const op: IntegrationOp =
            route === 'list-across-teams'
                ? 'list_across_teams'
                : route === 'batch-get'
                  ? 'read'
                  : route === 'resolve'
                    ? 'resolve'
                    : method === 'DELETE'
                      ? 'delete'
                      : method === 'GET'
                        ? 'read'
                        : 'write'
        headers['Authorization'] = `Bearer ${await token({ ...opts, ops: opts.ops ?? [op], refs: opts.refs ?? refs })}`
    }
    const init: RequestInit = { method, headers }
    if (opts.body !== undefined) {
        headers['Content-Type'] = 'application/json'
        init.body = typeof opts.body === 'string' ? opts.body : JSON.stringify(opts.body)
    }
    // The collection route is `/v1/integrations`, with no trailing slash.
    const route = path === '/' || path.startsWith('/?') ? path.slice(1) : path
    const res = await (opts.target ?? app).request(`/v1/integrations${route}`, init)
    const text = await res.text()
    responses.push({ path, text })
    let json: any = null
    try {
        json = text ? JSON.parse(text) : null
    } catch {
        json = { notJson: text }
    }
    return { status: res.status, json, text, headers: res.headers }
}

function newIntegration(overrides: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        kind: 'hubspot',
        integration_id: 'portal-1',
        auth_type: 'oauth',
        config: { region: 'us', refreshed_at: 1_800_000_000, expires_in: 3600, display_name: 'Portal one' },
        sensitive_config: { access_token: ACCESS_TOKEN, refresh_token: REFRESH_TOKEN, client_secret: CLIENT_SECRET },
        ...overrides,
    }
}

async function create(overrides: Record<string, unknown> = {}, opts: CallOptions = {}): Promise<any> {
    const res = await call('POST', '/', { body: newIntegration(overrides), ...opts })
    expect(res.status).toBe(201)
    return res.json
}

function buildApp(kms: Kms, replay?: ReplayStore, changesSettleSeconds = 0): Hono {
    const verifier = replay
        ? new IntegrationVerifier(integrationLoader, { replay })
        : new IntegrationVerifier(integrationLoader)
    return createApp({
        verifier: new JwtVerifier(platformLoader),
        lifecycle: { ready: true, shuttingDown: false },
        secrets: () => null,
        integrations: {
            verifier,
            service: new IntegrationsService({ pool, envelope: new Envelope(kms), audit, changesSettleSeconds }),
        },
    })
}

async function auditRows(): Promise<{ operation: string; outcome: string; owner_id: string; fields: string[] }[]> {
    await audit.flush()
    const result = await pool.query(
        'SELECT operation, outcome, owner_id, fields, details FROM audit_log ORDER BY occurred_at'
    )
    return result.rows
}

beforeAll(async () => {
    container = await new PostgreSqlContainer('postgres:17-alpine').start()
    await runMigrations({ databaseUrl: container.getConnectionUri(), direction: 'up' })
    pool = new Pool({ connectionString: container.getConnectionUri(), max: 5 })
    audit = new AuditQueue(pool, { flushIntervalMs: 60_000 })
    kms = new LocalKms([randomBytes(32)])
    app = buildApp(kms)
    for (const level of ['debug', 'info', 'warn', 'error', 'audit'] as const) {
        vi.spyOn(logger, level).mockImplementation((event: string, fields?: Record<string, unknown>) => {
            logLines.push(JSON.stringify({ event, fields }))
        })
    }
}, 120_000)

beforeEach(async () => {
    await audit.flush()
    await pool.query('TRUNCATE integrations, integration_secrets, audit_log, idempotency_keys CASCADE')
})

afterEach(() => {
    const seen = responses.splice(0)
    const logged = logLines.splice(0)
    // Every response and every log line of every test, not only the read routes.
    for (const { path, text } of seen) {
        // Resolve returns the access token. The change feed returns every secret, and no other route does.
        const forbidden = path.startsWith('/changes')
            ? []
            : path === '/resolve'
              ? NEVER_RETURNED
              : [ACCESS_TOKEN, ...NEVER_RETURNED]
        for (const secret of forbidden) {
            expect(text, `${path} returned a secret`).not.toContain(secret)
        }
    }
    for (const line of logged) {
        for (const secret of [ACCESS_TOKEN, ...NEVER_RETURNED]) {
            expect(line).not.toContain(secret)
        }
    }
})

afterAll(async () => {
    vi.restoreAllMocks()
    await pool?.end()
    await container?.stop()
})

describe('CRUD', () => {
    it('creates, reads, lists, patches and deletes a row', async () => {
        const created = await create({}, { userId: 7 })
        expect(created).toMatchObject({
            legacy_id: null,
            reference: created.id,
            team_id: TEAM_A,
            kind: 'hubspot',
            integration_id: 'portal-1',
            auth_type: 'oauth',
            display_name: 'Portal one',
            errors: '',
            is_source_row: false,
            version: 1,
        })
        expect(created).not.toHaveProperty('sensitive_config')

        const read = await call('GET', `/${created.id}`)
        expect(read.status).toBe(200)
        expect(read.json).toEqual(created)
        expect(read.headers.get('ETag')).toBe('"1"')

        const listed = await call('GET', '/?kind=hubspot&where.region=%22us%22')
        expect(listed.json.results.map((r: any) => r.id)).toEqual([created.id])

        const patched = await call('PATCH', `/${created.id}`, {
            headers: { 'If-Match': '"1"' },
            body: {
                config_patch: { refreshed_at: 1_800_000_100 },
                config_remove: ['display_name'],
                sensitive_config_patch: { access_token: 'fake-rotated-token' },
                errors: 'TOKEN_REFRESH_FAILED',
            },
        })
        expect(patched.status).toBe(200)
        expect(patched.json).toMatchObject({ version: 2, errors: 'TOKEN_REFRESH_FAILED', display_name: 'portal-1' })
        expect(patched.json.config).toEqual({ region: 'us', refreshed_at: 1_800_000_100, expires_in: 3600 })

        const resolved = await call('POST', '/resolve', { body: { refs: [created.id] } })
        expect(resolved.json.records[created.id].credentials).toEqual({ access_token: 'fake-rotated-token' })
        expect(resolved.headers.get('Cache-Control')).toBe('no-store')

        expect((await call('DELETE', `/${created.id}`, { headers: { 'If-Match': '2' } })).status).toBe(204)
        expect((await call('GET', `/${created.id}`)).status).toBe(404)
        expect((await call('GET', '/')).json.results).toEqual([])
        expect((await call('POST', '/resolve', { body: { refs: [created.id] } })).json.missing).toEqual([created.id])

        const stored = await pool.query('SELECT count(*)::int AS n FROM integration_secrets')
        expect(stored.rows[0].n).toBe(0)
    })

    it('stores secrets only as ciphertext', async () => {
        const created = await create()
        const rows = await pool.query(
            `SELECT i.config::text AS config, s.ciphertext, s.wrapped_dek, s.key_id
             FROM integrations i JOIN integration_secrets s ON s.integration_id = i.id WHERE i.id = $1`,
            [created.id]
        )
        const row = rows.rows[0]
        for (const secret of [ACCESS_TOKEN, ...NEVER_RETURNED]) {
            expect(row.config).not.toContain(secret)
            expect(Buffer.from(row.ciphertext).includes(Buffer.from(secret))).toBe(false)
        }
        expect(row.key_id).toMatch(/^local:/)
    })

    it('does not write or bump the version for a patch that changes nothing', async () => {
        const created = await create()
        const res = await call('PATCH', `/${created.id}`, {
            body: { config_patch: { region: 'us' }, sensitive_config_patch: { access_token: ACCESS_TOKEN } },
        })
        expect(res.json.version).toBe(1)
        expect((await auditRows()).filter((row) => row.operation === 'update')).toEqual([])
    })

    it('makes a patched key readable again on a row with unreadable legacy keys', async () => {
        const created = await create({ sensitive_config: { refresh_token: REFRESH_TOKEN } })
        await pool.query(`UPDATE integration_secrets SET legacy_unreadable_keys = '{access_token}'`)
        const resolve = async (): Promise<any> =>
            (await call('POST', '/resolve', { body: { refs: [created.id] } })).json
        expect((await resolve()).errors[created.id].code).toBe('unreadable_secret')

        await call('PATCH', `/${created.id}`, { body: { sensitive_config_patch: { access_token: 'fake-restored' } } })

        expect((await resolve()).records[created.id].credentials).toEqual({ access_token: 'fake-restored' })
        const stored = await pool.query('SELECT legacy_unreadable_keys FROM integration_secrets')
        expect(stored.rows[0].legacy_unreadable_keys).toEqual([])
    })

    it.each([
        ['an unknown kind format', { kind: 'Not A Kind' }, 400, 'validation'],
        ['an owner in the body', { owner: { type: 'team', id: TEAM_B } }, 400, 'validation'],
        ['a team id in the body', { team_id: TEAM_B }, 400, 'validation'],
        ['an unknown auth type', { auth_type: 'magic' }, 422, 'unsupported_auth_type'],
        ['a config that is not an object', { config: [1, 2] }, 400, 'validation'],
    ])('rejects a create with %s', async (_label, overrides, status, code) => {
        const res = await call('POST', '/', { body: newIntegration(overrides) })
        expect(res.status).toBe(status)
        expect(res.json.error.code).toBe(code)
        expect((await pool.query('SELECT count(*)::int AS n FROM integrations')).rows[0].n).toBe(0)
    })

    it('rejects a body that is not JSON with a 400, after the auth check', async () => {
        expect((await call('POST', '/', { body: '{not json' })).status).toBe(400)
        expect((await call('POST', '/', { body: '{not json', noToken: true })).status).toBe(401)
    })

    it('answers a duplicate external id with a conflict', async () => {
        await create()
        const res = await call('POST', '/', { body: newIntegration() })
        expect(res.status).toBe(409)
        expect(res.json.error.code).toBe('conflict')
    })

    it('reads a migrated row by its legacy id', async () => {
        const inserted = await insertIntegration(pool, {
            owner: { type: 'team', id: TEAM_A },
            kind: 'slack',
            externalId: 'T123',
            authType: 'oauth',
            legacyId: 4242,
        })
        expect(inserted.status).toBe('ok')
        const res = await call('GET', '/4242')
        expect(res.json).toMatchObject({ reference: '4242', legacy_id: 4242, kind: 'slack' })
    })

    it('pages the list with a cursor, oldest first or newest first', async () => {
        const ids: string[] = []
        for (let i = 0; i < 5; i++) {
            ids.push((await create({ integration_id: `portal-${i}`, sensitive_config: {} })).id)
        }
        for (const [newestFirst, expected] of [
            [false, ids],
            [true, [...ids].reverse()],
        ] as const) {
            const seen: string[] = []
            let next: string | null = null
            do {
                const query: string = `?limit=2&newest_first=${newestFirst}${next ? `&after=${next}` : ''}`
                const page = await call('GET', `/${query}`)
                expect(page.status).toBe(200)
                seen.push(...page.json.results.map((r: any) => r.id))
                next = page.json.next
            } while (next)
            expect(seen).toEqual(expected)
        }
    })

    it.each([
        ['an unknown filter', '?team_id=1'],
        ['a reserved config key', '?where.auth_type=%22oauth%22'],
        ['a where value that is not JSON', '?where.region=us'],
        ['a limit past the maximum', '?limit=5000'],
        ['a forged cursor', '?after=bm90LWEtY3Vyc29y'],
    ])('rejects a list with %s', async (_label, query) => {
        const res = await call('GET', `/${query}`)
        expect(res.status).toBe(400)
        expect(res.json.error.code).toBe('validation')
    })

    it('lists source rows only when asked', async () => {
        await create({ integration_id: 'plain', sensitive_config: {} })
        await create({ integration_id: 'source', is_source_row: true, sensitive_config: {} })
        const ids = async (query: string): Promise<string[]> =>
            (await call('GET', `/${query}`)).json.results.map((r: any) => r.integration_id)
        expect(await ids('')).toEqual(['plain'])
        expect(await ids('?source_rows=only')).toEqual(['source'])
        expect(await ids('?source_rows=include')).toEqual(['plain', 'source'])
    })
})

describe('audit write safety', () => {
    it.each([
        ['a NUL', 'caller\u0000x', 'callerx'],
        ['a lone surrogate', 'caller\uD800x', 'caller\uFFFDx'],
    ])('stores a batch whose caller holds %s', async (_label, caller, stored) => {
        const entry = {
            actor: { deployment: WEB, caller, userId: null, jti: 'j', requestId: 'r' },
            operation: 'read',
            outcome: 'ok',
            ownerType: 'team',
            ownerId: TEAM_A,
            integrationId: null,
            kind: 'hubspot',
        }

        await insertAuditRows(pool, [entry, { ...entry, actor: { ...entry.actor, caller: 'plain' } }])

        const rows = (await pool.query('SELECT caller FROM audit_log')).rows.map((row) => row.caller)
        expect(rows.sort()).toEqual([stored, 'plain'].sort())
    })
})

describe('patch audit', () => {
    it('audits a patch that changes nothing as a read', async () => {
        const created = await create()

        const res = await call('PATCH', `/${created.id}`, { ops: ['write'], body: {} })

        expect(res.status).toBe(200)
        expect((await auditRows()).map((row) => row.operation)).toEqual(['create', 'read'])
    })
})

describe('idempotency key cleanup', () => {
    it('deletes expired keys and keeps live ones', async () => {
        await pool.query(
            `INSERT INTO idempotency_keys (deployment, owner_type, owner_id, operation, key, request_hash, expires_at)
             VALUES ($1, 'team', 1, 'create', 'old', '\\x00', now() - interval '1 hour'),
                    ($1, 'team', 1, 'create', 'new', '\\x00', now() + interval '1 hour')`,
            [WEB]
        )

        expect(await deleteExpiredIdempotencyKeys(pool)).toBe(1)

        const left = await pool.query('SELECT key FROM idempotency_keys')
        expect(left.rows.map((row) => row.key)).toEqual(['new'])
    })
})

describe('source row grants', () => {
    // temporal-worker-batch-exports may read postgresql rows but has no source-row grant.
    async function setup(): Promise<{ plain: any; source: any }> {
        const plain = await create({ kind: 'postgresql', integration_id: 'plain', sensitive_config: {} })
        const source = await create({
            kind: 'postgresql',
            integration_id: 'source',
            is_source_row: true,
            sensitive_config: {},
        })
        return { plain, source }
    }

    it('refuses a deployment with no grant on every route that reads a source row', async () => {
        const { plain, source } = await setup()
        const as = { deployment: BATCH_EXPORTS, ops: undefined }

        expect((await call('GET', `/${plain.id}`, as)).status).toBe(200)
        for (const res of [
            await call('GET', `/${source.id}`, as),
            await call('POST', '/batch-get', { ...as, body: { refs: [plain.id, source.id] } }),
            await call('POST', '/resolve', { ...as, body: { refs: [source.id] } }),
            await call('GET', '/?source_rows=only', as),
            await call('GET', '/?source_rows=include', as),
        ]) {
            expect(res.status).toBe(403)
            expect(res.json.error.code).toBe('forbidden_kind')
        }
    })

    it('lists the ordinary rows of a deployment with no grant', async () => {
        const { plain } = await setup()

        const res = await call('GET', '/', { deployment: BATCH_EXPORTS })

        expect(res.json.results.map((row: any) => row.id)).toEqual([plain.id])
    })

    it('lets a deployment with the grant list and read source rows', async () => {
        const { source } = await setup()

        const res = await call('GET', '/?source_rows=only', { deployment: WORKER })

        expect(res.json.results.map((row: any) => row.id)).toEqual([source.id])
    })
})

describe('upsert', () => {
    it('creates a row, then replaces its config and whole secret blob', async () => {
        const first = await call('PUT', '/upsert', { body: newIntegration() })
        expect(first.status).toBe(201)
        expect(first.json.created).toBe(true)

        const second = await call('PUT', '/upsert', {
            body: newIntegration({ config: { region: 'us' }, sensitive_config: { access_token: 'fake-new-token' } }),
        })
        expect(second.status).toBe(200)
        expect(second.json).toMatchObject({ created: false, record: { id: first.json.record.id, version: 2 } })
        expect(second.json.record.config).toEqual({ region: 'us' })

        const resolved = await call('POST', '/resolve', { body: { refs: [first.json.record.id] } })
        expect(resolved.json.records[first.json.record.id].credentials).toEqual({ access_token: 'fake-new-token' })
    })

    it.each([
        ['changes the region', { region: 'eu' }, 'region'],
        ['drops the region', { display_name: 'x' }, 'region'],
        ['adds an instance url', { region: 'us', instance_url: 'https://example.com' }, 'instance_url'],
    ])('refuses an upsert of an existing row that %s', async (_label, config, key) => {
        await call('PUT', '/upsert', { body: newIntegration() })
        const res = await call('PUT', '/upsert', { body: newIntegration({ config }) })
        expect(res.status).toBe(400)
        expect(res.json.error).toMatchObject({ code: 'validation', details: { keys: [key] } })
    })

    it('answers a row with another auth type with a conflict', async () => {
        await create()
        const res = await call('PUT', '/upsert', { body: newIntegration({ auth_type: 'token' }) })
        expect(res.status).toBe(409)
    })

    it('makes concurrent upserts of a null external id create one row', async () => {
        const body = newIntegration({ integration_id: null, sensitive_config: {} })
        const results = await Promise.all([1, 2, 3, 4].map(() => call('PUT', '/upsert', { body })))
        expect(results.filter((res) => res.json.created)).toHaveLength(1)
        expect((await pool.query('SELECT count(*)::int AS n FROM integrations')).rows[0].n).toBe(1)
    })
})

describe('identity fields', () => {
    it.each([
        ['changes the region', { config_patch: { region: 'eu' } }, 'region'],
        ['removes the region', { config_remove: ['region'] }, 'region'],
        ['sets an installation id', { config_patch: { installation_id: 7 } }, 'installation_id'],
        ['sets an instance url', { config_patch: { instance_url: 'https://example.com' } }, 'instance_url'],
    ])('refuses a patch that %s', async (_label, body, key) => {
        const created = await create()
        const res = await call('PATCH', `/${created.id}`, { body })
        expect(res.status).toBe(400)
        expect(res.json.error).toMatchObject({ code: 'validation', details: { keys: [key] } })
        expect(res.json.error.message).toContain(key)
        expect((await call('GET', `/${created.id}`)).json.config.region).toBe('us')
    })

    it('refuses to change the external id through a patch', async () => {
        const created = await create()
        const res = await call('PATCH', `/${created.id}`, { body: { integration_id: 'portal-2' } })
        expect(res.status).toBe(400)
        expect(res.json.error.code).toBe('validation')
    })

    it('allows a patch that sets an identity key to its current value', async () => {
        const created = await create()
        const res = await call('PATCH', `/${created.id}`, { body: { config_patch: { region: 'us' } } })
        expect(res.status).toBe(200)
    })
})

describe('team isolation', () => {
    it.each([
        ['GET', (ref: string) => `/${ref}`, undefined],
        ['PATCH', (ref: string) => `/${ref}`, { config_patch: { region: 'eu' } }],
        ['DELETE', (ref: string) => `/${ref}`, undefined],
    ])('answers %s of another team row with 404', async (method, path, body) => {
        const created = await create()
        const res = await call(method, path(created.id), { team: TEAM_B, body })
        expect(res.status).toBe(404)
        expect(res.json.error.code).toBe('not_found')

        const unchanged = await call('GET', `/${created.id}`)
        expect(unchanged.json.version).toBe(1)
    })

    it('reports another team row as missing in batch-get and resolve, and never lists it', async () => {
        const created = await create()
        for (const path of ['/batch-get', '/resolve']) {
            const res = await call('POST', path, { team: TEAM_B, body: { refs: [created.id] } })
            expect(res.json).toMatchObject({ records: {}, missing: [created.id] })
        }
        expect((await call('GET', '/', { team: TEAM_B })).json.results).toEqual([])
    })

    it('lets two teams use the same external id', async () => {
        await create()
        await create({}, { team: TEAM_B })
        expect((await pool.query('SELECT count(*)::int AS n FROM integrations')).rows[0].n).toBe(2)
    })
})

describe('authorization', () => {
    it('rejects token replay in one app and across apps that share Postgres', async () => {
        const kms = new LocalKms([randomBytes(32)])
        const first = buildApp(kms, new PostgresReplayStore(pool))
        const second = buildApp(kms, new PostgresReplayStore(pool))
        const sameAppToken = await token({ ops: ['read'] })
        const crossAppToken = await token({ ops: ['read'] })
        const request = (target: Hono, bearer: string): Response | Promise<Response> =>
            target.request('/v1/integrations', { headers: { Authorization: `Bearer ${bearer}` } })

        expect((await request(first, sameAppToken)).status).toBe(200)
        expect((await request(first, sameAppToken)).status).toBe(401)
        expect((await request(first, crossAppToken)).status).toBe(200)
        expect((await request(second, crossAppToken)).status).toBe(401)
    })

    it.each([
        ['POST', '/', newIntegration()],
        ['PUT', '/upsert', newIntegration()],
        ['PATCH', '/REF', { config_patch: { region: 'eu' } }],
        ['DELETE', '/REF', undefined],
        ['GET', '/REF', undefined],
        ['GET', '/', undefined],
        ['POST', '/batch-get', { refs: ['REF'] }],
    ])('refuses %s %s for a cdp token', async (method, path, body) => {
        const created = await create({ integration_id: 'existing' })
        const withRef = (value: string): string => value.replace('REF', created.id)
        const res = await call(method, withRef(path), {
            deployment: CDP,
            ops: [method === 'DELETE' ? 'delete' : method === 'GET' || path === '/batch-get' ? 'read' : 'write'],
            body: body === undefined ? undefined : JSON.parse(withRef(JSON.stringify(body))),
        })
        expect(res.status).toBe(403)
        expect(res.json.error.code).toBe('forbidden_op')
        expect((await call('GET', `/${created.id}`)).json.version).toBe(1)
    })

    it('lets a cdp token resolve', async () => {
        const created = await create()
        const res = await call('POST', '/resolve', { deployment: CDP, ops: ['resolve'], body: { refs: [created.id] } })
        expect(res.status).toBe(200)
        expect(res.json.records[created.id].credentials).toEqual({ access_token: ACCESS_TOKEN })
    })

    it('refuses a write when the token does not hold the write op', async () => {
        const res = await call('POST', '/', { ops: ['read'], body: newIntegration() })
        expect(res.status).toBe(403)
    })

    it('refuses a delete for a worker token', async () => {
        const created = await create()
        const res = await call('DELETE', `/${created.id}`, { deployment: WORKER, ops: ['delete'] })
        expect(res.status).toBe(403)
        expect(res.json.error.code).toBe('forbidden_op')
    })

    it('limits a kind-narrowed token to its kinds', async () => {
        const hubspot = await create()
        await create({ kind: 'slack', integration_id: 'T1', sensitive_config: {} })

        expect((await call('GET', `/${hubspot.id}`, { kinds: ['slack'] })).json.error.code).toBe('forbidden_kind')
        expect((await call('POST', '/', { kinds: ['slack'], body: newIntegration() })).status).toBe(403)
        expect(
            (await call('POST', '/resolve', { kinds: ['slack'], body: { refs: [hubspot.id] } })).json.error.code
        ).toBe('forbidden_kind')
        const listed = await call('GET', '/', { kinds: ['slack'] })
        expect(listed.json.results.map((r: any) => r.kind)).toEqual(['slack'])
    })

    it('limits a ref-narrowed token to its refs, and refuses lists', async () => {
        const one = await create({ integration_id: 'one', sensitive_config: {} })
        const two = await create({ integration_id: 'two', sensitive_config: {} })

        expect((await call('GET', `/${one.id}`, { refs: [one.id] })).status).toBe(200)
        expect((await call('GET', `/${two.id}`, { refs: [one.id] })).status).toBe(403)
        expect((await call('POST', '/batch-get', { refs: [one.id], body: { refs: [one.id, two.id] } })).status).toBe(
            403
        )
        expect((await call('GET', '/', { refs: [one.id] })).status).toBe(403)
    })

    it('answers a request with no token with 401', async () => {
        const res = await call('POST', '/resolve', { noToken: true, body: { refs: ['1'] } })
        expect(res.status).toBe(401)
        expect(res.json.error.code).toBe('unauthorized')
    })
})

describe('optimistic concurrency', () => {
    it.each([
        ['PATCH', { config_patch: { region: 'eu' } }],
        ['DELETE', undefined],
    ])('answers %s with a stale If-Match with version_mismatch', async (method, body) => {
        const created = await create()
        await call('PATCH', `/${created.id}`, { body: { errors: 'something' } })

        const res = await call(method, `/${created.id}`, { headers: { 'If-Match': '"1"' }, body })
        expect(res.status).toBe(412)
        expect(res.json.error).toMatchObject({ code: 'version_mismatch', details: { current_version: 2 } })
        expect((await call('GET', `/${created.id}`)).json.version).toBe(2)
    })

    it('rejects an If-Match that is not a version', async () => {
        const created = await create()
        const res = await call('PATCH', `/${created.id}`, { headers: { 'If-Match': 'W/"abc"' }, body: {} })
        expect(res.status).toBe(400)
    })
})

describe('idempotent create', () => {
    it('returns the first result for a replay with the same key and body', async () => {
        const headers = { 'Idempotency-Key': 'create-once-123' }
        const first = await call('POST', '/', { headers, body: newIntegration() })
        const second = await call('POST', '/', { headers, body: newIntegration() })

        expect(first.status).toBe(201)
        expect(second.status).toBe(201)
        expect(second.json.id).toBe(first.json.id)
        expect(second.headers.get('Idempotent-Replayed')).toBe('true')
        expect((await pool.query('SELECT count(*)::int AS n FROM integrations')).rows[0].n).toBe(1)
    })

    it('answers a reused key with another body with a conflict', async () => {
        const headers = { 'Idempotency-Key': 'create-once-456' }
        await call('POST', '/', { headers, body: newIntegration() })
        const res = await call('POST', '/', { headers, body: newIntegration({ integration_id: 'portal-2' }) })
        expect(res.status).toBe(409)
        expect((await pool.query('SELECT count(*)::int AS n FROM integrations')).rows[0].n).toBe(1)
    })

    it('keeps keys of different deployments apart', async () => {
        const headers = { 'Idempotency-Key': 'create-once-shared' }
        const a = await call('POST', '/', { headers, body: newIntegration() })
        const b = await call('POST', '/', {
            headers,
            deployment: WORKER,
            body: newIntegration({ integration_id: 'portal-2' }),
        })
        expect(b.status).toBe(201)
        expect(b.json.id).not.toBe(a.json.id)
        expect(b.headers.get('Idempotent-Replayed')).toBeNull()
    })

    it('keeps keys of different teams apart', async () => {
        const headers = { 'Idempotency-Key': 'create-once-789' }
        const a = await call('POST', '/', { headers, body: newIntegration() })
        const b = await call('POST', '/', { headers, team: TEAM_B, body: newIntegration() })
        expect(b.json.id).not.toBe(a.json.id)
        expect(b.headers.get('Idempotent-Replayed')).toBeNull()
    })
})

describe('resolve', () => {
    it('returns credentials without refresh tokens or client secrets, and the token expiry', async () => {
        const created = await create()
        const res = await call('POST', '/resolve', { body: { refs: [created.id, '999999'] } })
        expect(res.status).toBe(200)
        expect(res.json).toEqual({
            records: {
                [created.id]: {
                    record: created,
                    credentials: { access_token: ACCESS_TOKEN },
                    expires_at: new Date((1_800_000_000 + 3600) * 1000).toISOString(),
                },
            },
            missing: ['999999'],
            errors: {},
        })
    })

    it('answers a row with unreadable legacy keys with unreadable_secret for that ref only', async () => {
        const good = await create({ integration_id: 'good' })
        const bad = await create({ integration_id: 'bad' })
        await pool.query(
            `UPDATE integration_secrets SET legacy_unreadable_keys = '{refresh_token}' WHERE integration_id = $1`,
            [bad.id]
        )

        const res = await call('POST', '/resolve', { body: { refs: [good.id, bad.id] } })
        expect(Object.keys(res.json.records)).toEqual([good.id])
        expect(res.json.errors[bad.id]).toMatchObject({
            code: 'unreadable_secret',
            details: { keys: ['refresh_token'] },
        })
    })

    it('answers a ciphertext copied from another row with unreadable_secret', async () => {
        const source = await create({ integration_id: 'source' })
        const target = await create({ integration_id: 'target', sensitive_config: { access_token: 'fake-other' } })
        await pool.query(
            `UPDATE integration_secrets t SET key_id = s.key_id, wrapped_dek = s.wrapped_dek, ciphertext = s.ciphertext, nonce = s.nonce
             FROM integration_secrets s WHERE s.integration_id = $1 AND t.integration_id = $2`,
            [source.id, target.id]
        )
        const res = await call('POST', '/resolve', { body: { refs: [target.id] } })
        expect(res.json.errors[target.id].code).toBe('unreadable_secret')
    })

    it('returns empty credentials for a row with no secret', async () => {
        const created = await create({ sensitive_config: {} })
        const res = await call('POST', '/resolve', { body: { refs: [created.id] } })
        expect(res.json.records[created.id]).toMatchObject({ credentials: {} })
    })

    it('answers both refs of a migrated row', async () => {
        const inserted = await insertIntegration(pool, {
            owner: { type: 'team', id: TEAM_A },
            kind: 'slack',
            externalId: 'T9',
            authType: 'oauth',
            legacyId: 77,
        })
        if (inserted.status !== 'ok') {
            throw new Error('insert failed')
        }
        const res = await call('POST', '/resolve', { body: { refs: ['77', inserted.row.id] } })
        expect(Object.keys(res.json.records).sort()).toEqual(['77', inserted.row.id].sort())
    })
})

describe('batch limits', () => {
    const uuid = (i: number): string => `00000000-0000-4000-8000-${String(i).padStart(12, '0')}`

    it.each([
        ['no refs', { refs: [] }, 403, 'forbidden_ref'],
        ['201 refs', { refs: Array.from({ length: 201 }, (_, i) => uuid(i)) }, 403, 'forbidden_ref'],
        ['a ref that is not a legacy id or a UUID', { refs: ['01'] }, 403, 'forbidden_ref'],
        ['an upper-case UUID', { refs: ['0B8A3A8E-4E0A-4F5E-9D7A-1C2B3D4E5F60'] }, 403, 'forbidden_ref'],
        ['an extra field', { refs: ['1'], team_id: TEAM_B }, 400, 'validation'],
    ])('rejects %s', async (_label, body, status, code) => {
        for (const path of ['/batch-get', '/resolve']) {
            const res = await call('POST', path, { body })
            expect(res.status).toBe(status)
            expect(res.json.error.code).toBe(code)
        }
    })

    it('accepts 200 refs', async () => {
        const created = await create({ sensitive_config: {} })
        const refs = [created.id, ...Array.from({ length: 199 }, (_, i) => uuid(i))]
        const res = await call('POST', '/batch-get', { body: { refs } })
        expect(res.status).toBe(200)
        expect(Object.keys(res.json.records)).toEqual([created.id])
        expect(res.json.missing).toHaveLength(199)
    })
})

describe('list across teams', () => {
    async function seed(): Promise<void> {
        await create({ integration_id: 'a1', config: { region: 'us' }, sensitive_config: {} }, { userId: 1 })
        await create({ integration_id: 'a2', config: { region: 'eu' }, sensitive_config: {} }, { userId: 1 })
        await create({ integration_id: 'b1', config: { region: 'us' } }, { team: TEAM_B })
        await create({ kind: 'slack', integration_id: 's1', sensitive_config: {} }, { team: TEAM_B })
    }

    it.each([
        ['every row of the kind', {}, ['a1', 'a2', 'b1']],
        ['a config value', { where: { region: 'us' } }, ['a1', 'b1']],
        ['a config value list', { where_in: { region: ['eu', 'apac'] } }, ['a2']],
        ['a case-insensitive config value', { where_iexact: { region: 'US' } }, ['a1', 'b1']],
        ['team ids', { team_ids: [TEAM_B] }, ['b1']],
        ['excluded team ids', { exclude_team_ids: [TEAM_A] }, ['b1']],
        ['an empty team list', { team_ids: [] }, []],
        ['an external id', { external_id: 'a2' }, ['a2']],
        ['a config key', { has_config_key: 'region' }, ['a1', 'a2', 'b1']],
        ['newest first', { newest_first: true }, ['b1', 'a2', 'a1']],
    ])('selects by %s', async (_label, filter, expected) => {
        await seed()
        const res = await call('POST', '/list-across-teams', {
            team: null,
            ops: ['list_across_teams'],
            body: { kinds: ['hubspot'], ...filter },
        })
        expect(res.status).toBe(200)
        expect(res.json.results.map((r: any) => r.integration_id)).toEqual(expected)
    })

    it('pages with a cursor', async () => {
        await seed()
        const first = await call('POST', '/list-across-teams', {
            team: null,
            ops: ['list_across_teams'],
            body: { kinds: ['hubspot'], limit: 2 },
        })
        const second = await call('POST', '/list-across-teams', {
            team: null,
            ops: ['list_across_teams'],
            body: { kinds: ['hubspot'], limit: 2, after: first.json.next },
        })
        expect([...first.json.results, ...second.json.results].map((r: any) => r.integration_id)).toEqual([
            'a1',
            'a2',
            'b1',
        ])
        expect(second.json.next).toBeNull()
    })

    it.each([
        [WEB, 200],
        [WORKER, 200],
        [CDP, 403],
    ])('answers a %s token with %i', async (deployment, status) => {
        const res = await call('POST', '/list-across-teams', {
            deployment,
            team: null,
            ops: ['list_across_teams'],
            body: { kinds: ['hubspot'] },
        })
        expect(res.status).toBe(status)
    })

    it.each([
        ['no kinds', {}],
        ['a nested path in where', { kinds: ['hubspot'], where: { 'a.b': 1 } }],
        ['a three-level iexact path', { kinds: ['hubspot'], where_iexact: { 'a.b.c': 'x' } }],
        ['a null in where_in', { kinds: ['hubspot'], where_in: { region: [null] } }],
        ['an object in where', { kinds: ['hubspot'], where: { region: { $ne: 1 } } }],
    ])('rejects a filter with %s', async (_label, body) => {
        const res = await call('POST', '/list-across-teams', { team: null, ops: ['list_across_teams'], body })
        expect(res.status).toBe(400)
    })
})

describe('audit', () => {
    it('writes one row per changed record in the write transaction, and queues read rows', async () => {
        const created = await create()
        await call('PATCH', `/${created.id}`, { body: { sensitive_config_patch: { access_token: 'fake-rotated' } } })
        await call('GET', `/${created.id}`)
        await call('POST', '/resolve', { body: { refs: [created.id] } })
        await call('DELETE', `/${created.id}`)

        const rows = await auditRows()
        expect(rows.map((row) => row.operation).sort()).toEqual(['create', 'delete', 'read', 'resolve', 'update'])
        expect(rows.every((row) => row.owner_id === String(TEAM_A))).toBe(true)
        expect(rows.find((row) => row.operation === 'resolve')?.fields).toEqual(['access_token'])
        expect(rows.find((row) => row.operation === 'create')?.fields).toEqual([
            'access_token',
            'client_secret',
            'refresh_token',
        ])
        expect(JSON.stringify(rows)).not.toContain('fake-rotated')
    })

    it('writes one row per record a cross-team list returns, with each row team', async () => {
        await create({ sensitive_config: {} })
        await create({ sensitive_config: {} }, { team: TEAM_B })
        await call('POST', '/list-across-teams', {
            team: null,
            ops: ['list_across_teams'],
            body: { kinds: ['hubspot'] },
        })

        const rows = (await auditRows()).filter((row) => row.operation === 'list_across_teams')
        expect(rows.map((row) => row.owner_id).sort()).toEqual([String(TEAM_A), String(TEAM_B)])
    })

    it('writes one stdout line per audit row, with field names and no values', async () => {
        const created = await create()
        await call('PATCH', `/${created.id}`, { body: { sensitive_config_patch: { access_token: 'fake-rotated' } } })
        await call('GET', `/${created.id}`)

        const lines = logLines.map((line) => JSON.parse(line)).filter((line) => line.event === 'integrations:audited')
        expect(lines.map((line) => line.fields.operation).sort()).toEqual(['create', 'read', 'update'])
        expect(lines.find((line) => line.fields.operation === 'create').fields).toMatchObject({
            deployment: WEB,
            owner_id: TEAM_A,
            integration_id: created.id,
            kind: 'hubspot',
            outcome: 'ok',
            fields: ['access_token', 'client_secret', 'refresh_token'],
        })
        expect(JSON.stringify(lines)).not.toContain('fake-rotated')
    })

    it('writes the stdout line for a read row that the full queue drops', async () => {
        const small = new AuditQueue(pool, { maxPending: 0, batchSize: 100, flushIntervalMs: 60_000 })
        small.enqueue([
            {
                actor: { deployment: WEB, caller: 'test', userId: null, jti: 'jti', requestId: 'req' },
                operation: 'read',
                outcome: 'ok',
                ownerType: 'team',
                ownerId: TEAM_A,
                integrationId: null,
                kind: 'hubspot',
            },
        ])
        expect(small.size).toBe(0)
        expect(logLines.filter((line) => line.includes('integrations:audited'))).toHaveLength(1)
    })

    it('drops and counts read rows when the queue is full', async () => {
        const small = new AuditQueue(pool, { maxPending: 2, batchSize: 100, flushIntervalMs: 60_000 })
        const before = await droppedTotal()
        const entry = {
            actor: { deployment: WEB, caller: 'test', userId: null, jti: 'jti', requestId: 'req' },
            operation: 'read',
            outcome: 'ok',
            ownerType: 'team',
            ownerId: TEAM_A,
            integrationId: null,
            kind: 'hubspot',
        }
        small.enqueue([entry, entry, entry])
        expect(small.size).toBe(2)
        expect((await droppedTotal()) - before).toBe(1)
        await small.stop()
        expect((await pool.query('SELECT count(*)::int AS n FROM audit_log')).rows[0].n).toBe(2)
    })
})

async function droppedTotal(): Promise<number> {
    const metric = await register.getSingleMetric('credentials_service_audit_dropped_total')?.get()
    return (metric?.values ?? [])
        .filter((value) => value.labels['reason'] === 'queue_full')
        .reduce((sum, value) => sum + value.value, 0)
}

describe('where filters', () => {
    it('binds an injection-shaped value as data', async () => {
        await create()
        const value = encodeURIComponent(JSON.stringify(`us' OR '1'='1`))
        const res = await call('GET', `/?kind=hubspot&where.region=${value}`)
        expect(res.status).toBe(200)
        expect(res.json.results).toEqual([])
        expect((await pool.query('SELECT count(*)::int AS n FROM integrations')).rows[0].n).toBe(1)
    })

    it.each(["region'; DROP TABLE integrations;--", 'region" OR 1=1', "a'b"])(
        'refuses the injection-shaped key %j',
        async (key) => {
            const res = await call('GET', `/?where.${encodeURIComponent(key)}=1`)
            expect(res.status).toBe(400)
            const body = await call('POST', '/list-across-teams', {
                team: null,
                ops: ['list_across_teams'],
                body: { kinds: ['hubspot'], where: { [key]: 1 } },
            })
            expect(body.status).toBe(400)
        }
    )

    // The routes validate keys, so this reaches the query layer directly to prove the SQL binds them too.
    it('binds an injection-shaped key in the query layer', async () => {
        await create()
        const page = await listIntegrations(
            pool,
            { type: 'team', id: TEAM_A },
            {
                kinds: null,
                authTypes: null,
                externalId: null,
                sourceRows: 'include',
                where: { "region' OR '1'='1": 'us' },
                whereIn: { "x'); DROP TABLE integrations;--": ['a'] },
                whereIexact: { "a'b.c'd": 'x' },
                hasConfigKey: "x' OR '1'='1",
            },
            { limit: 10, newestFirst: false, after: null }
        )
        expect(page.rows).toEqual([])
        expect((await pool.query('SELECT count(*)::int AS n FROM integrations')).rows[0].n).toBe(1)
    })
})

describe('KMS outage', () => {
    class DownKms implements Kms {
        readonly provider = 'local'
        async generateDataKey(_context: EncryptionContext): Promise<never> {
            throw new KmsError('unavailable', 'KMS did not answer')
        }
        async decrypt(): Promise<never> {
            throw new KmsError('unavailable', 'KMS did not answer')
        }
        async rewrap(): Promise<never> {
            throw new KmsError('unavailable', 'KMS did not answer')
        }
    }

    it('answers a write with a secret, and a resolve that misses the key cache, with kms_unavailable', async () => {
        const created = await create()
        const down = buildApp(new DownKms())

        const write = await call('POST', '/', { target: down, body: newIntegration({ integration_id: 'other' }) })
        expect(write.status).toBe(503)
        expect(write.json.error.code).toBe('kms_unavailable')

        const resolve = await call('POST', '/resolve', { target: down, body: { refs: [created.id] } })
        expect(resolve.status).toBe(503)
        expect(resolve.json.error.code).toBe('kms_unavailable')

        // A write without secrets needs no KMS.
        const plain = await call('POST', '/', {
            target: down,
            body: newIntegration({ integration_id: 'plain', sensitive_config: {} }),
        })
        expect(plain.status).toBe(201)
    })
})

const BY_EXTERNAL_ID_OPS: IntegrationOp[] = ['read_by_external_id', 'write_by_external_id', 'delete_by_external_id']

function sharedPath(kind: string, externalId: string, query = ''): string {
    return `/by-external-id/${kind}/${encodeURIComponent(externalId)}${query}`
}

async function byExternalId(method: string, path: string, opts: CallOptions = {}): Promise<CallResult> {
    return call(method, path, { team: null, ops: BY_EXTERNAL_ID_OPS, ...opts })
}

async function rowCount(where: string, values: unknown[] = []): Promise<number> {
    const result = await pool.query(`SELECT count(*)::int AS n FROM integrations WHERE ${where}`, values)
    return result.rows[0].n
}

describe('by external id', () => {
    // Two teams share the installation, a third has it only as a source row. Other kinds and ids stay out.
    async function seed(): Promise<Record<string, any>> {
        return {
            a: await create({ integration_id: 'shared' }, { team: TEAM_A }),
            b: await create({ integration_id: 'shared' }, { team: TEAM_B }),
            c: await create({ integration_id: 'shared', is_source_row: true }, { team: TEAM_C }),
            otherId: await create({ integration_id: 'other' }, { team: TEAM_A }),
            otherKind: await create({ kind: 'slack', integration_id: 'shared' }, { team: TEAM_A }),
        }
    }

    it.each([
        ['the live rows of every team, without source rows', '', ['a', 'b']],
        ['source rows too, when asked', '?source_rows=include', ['a', 'b', 'c']],
        ['only the teams named', '?team_id=202', ['b']],
    ])('lists %s', async (_label, query, expected) => {
        const rows = await seed()
        const res = await byExternalId('GET', sharedPath('hubspot', 'shared', query))
        expect(res.status).toBe(200)
        expect(res.json.results.map((r: any) => r.id)).toEqual(expected.map((name) => rows[name].id))
        expect(res.json.results[0]).not.toHaveProperty('sensitive_config')
    })

    it.each([['?source_rows=only'], ['?source_rows=include']])(
        'refuses source rows to a deployment with no grant (%s)',
        async (query) => {
            await create({ kind: 'slack', integration_id: 'shared', is_source_row: true }, { team: TEAM_A })

            const res = await byExternalId('GET', sharedPath('slack', 'shared', query), { deployment: TASKS_AGENT })

            expect(res.status).toBe(403)
            expect(res.json.error.code).toBe('forbidden_kind')
        }
    )

    it('lists only the ordinary rows for a deployment with no source row grant', async () => {
        const plain = await create({ kind: 'slack', integration_id: 'shared' }, { team: TEAM_A })
        await create({ kind: 'slack', integration_id: 'shared', is_source_row: true }, { team: TEAM_B })

        const res = await byExternalId('GET', sharedPath('slack', 'shared'), { deployment: TASKS_AGENT })

        expect(res.json.results.map((r: any) => r.id)).toEqual([plain.id])
    })

    it('pages with a cursor', async () => {
        const rows = await seed()
        const first = await byExternalId('GET', sharedPath('hubspot', 'shared', '?limit=1'))
        const second = await byExternalId('GET', sharedPath('hubspot', 'shared', `?limit=1&after=${first.json.next}`))
        expect([...first.json.results, ...second.json.results].map((r: any) => r.id)).toEqual([rows.a.id, rows.b.id])
        expect(second.json.next).toBeNull()
    })

    it('refuses a token that also names an owner', async () => {
        await seed()
        const res = await call('GET', sharedPath('hubspot', 'shared'), { team: TEAM_A, ops: BY_EXTERNAL_ID_OPS })
        expect(res.status).toBe(401)
    })

    it.each([
        ['the web deployment', WEB, 200],
        ['a worker deployment', WORKER, 403],
        ['a cdp deployment', CDP, 403],
    ])('allows or refuses a read from %s', async (_label, deployment, status) => {
        const res = await byExternalId('GET', sharedPath('hubspot', 'shared'), { deployment })
        expect(res.status).toBe(status)
    })

    it.each([
        ['GET', 'read_by_external_id', undefined],
        ['PATCH', 'write_by_external_id', { config_patch: { region: 'eu' } }],
        ['DELETE', 'delete_by_external_id', undefined],
    ])('refuses a %s whose token lacks %s, or whose deployment is not web', async (method, op, body) => {
        await seed()
        const others = BY_EXTERNAL_ID_OPS.filter((candidate) => candidate !== op)
        const path = sharedPath('hubspot', 'shared')
        expect((await byExternalId(method, path, { ops: others, body })).status).toBe(403)
        for (const deployment of [WORKER, CDP]) {
            expect((await byExternalId(method, path, { deployment, body })).status).toBe(403)
        }
        expect(await rowCount('deleted_at IS NULL')).toBe(5)
    })

    it('refuses a kind that the token does not name', async () => {
        await seed()
        const res = await byExternalId('DELETE', sharedPath('hubspot', 'shared'), { kinds: ['slack'] })
        expect(res.status).toBe(403)
        expect(res.json.error.code).toBe('forbidden_kind')
        expect(await rowCount('deleted_at IS NULL')).toBe(5)
    })

    it('refuses a token that names refs, because no ref is known', async () => {
        const rows = await seed()
        const res = await byExternalId('GET', sharedPath('hubspot', 'shared'), { refs: [rows.a.id] })
        expect(res.status).toBe(403)
    })

    it('patches the rows of every team, secrets included, and writes nothing for an identical patch', async () => {
        const rows = await seed()
        const patch = {
            config_patch: { refreshed_at: 1_800_000_500 },
            sensitive_config_patch: { access_token: 'fake-rotated-token' },
            errors: 'TOKEN_REFRESH_FAILED',
        }
        const res = await byExternalId('PATCH', sharedPath('hubspot', 'shared'), { body: patch, userId: 9 })
        expect(res.status).toBe(200)
        expect(res.json).toEqual({ matched: 2, updated: 2 })

        for (const name of ['a', 'b']) {
            const row = await call('GET', `/${rows[name].id}`, { team: name === 'a' ? TEAM_A : TEAM_B })
            expect(row.json).toMatchObject({
                version: 2,
                errors: 'TOKEN_REFRESH_FAILED',
                config: { refreshed_at: 1_800_000_500 },
            })
            const resolved = await call('POST', '/resolve', {
                team: name === 'a' ? TEAM_A : TEAM_B,
                body: { refs: [rows[name].id] },
            })
            expect(resolved.json.records[rows[name].id].credentials).toEqual({ access_token: 'fake-rotated-token' })
        }
        // Other ids, kinds and source rows are untouched.
        for (const name of ['c', 'otherId', 'otherKind']) {
            expect(await rowCount('id = $1 AND version = 1', [rows[name].id])).toBe(1)
        }

        const again = await byExternalId('PATCH', sharedPath('hubspot', 'shared'), { body: patch })
        expect(again.json).toEqual({ matched: 2, updated: 0 })
        expect(await rowCount('version = 2')).toBe(2)

        const audited = (
            await pool.query(
                `SELECT outcome, owner_id, fields, user_id FROM audit_log
             WHERE operation = 'write_by_external_id' ORDER BY occurred_at, owner_id`
            )
        ).rows
        expect(audited.map((row) => [row.outcome, row.owner_id])).toEqual([
            ['ok', String(TEAM_A)],
            ['ok', String(TEAM_B)],
            ['unchanged', String(TEAM_A)],
            ['unchanged', String(TEAM_B)],
        ])
        expect(audited[0].fields).toEqual(['access_token'])
        expect(audited[0].user_id).toBe('9')
    })

    it.each([
        ['an unknown field', { owner: 5 }],
        ['a team id', { team_id: 5 }],
    ])('rejects a patch with %s', async (_label, body) => {
        await seed()
        const res = await byExternalId('PATCH', sharedPath('hubspot', 'shared'), { body })
        expect(res.status).toBe(400)
    })

    it('rejects a bad kind, a bad source_rows and an unknown parameter', async () => {
        for (const path of [
            sharedPath('Not A Kind', 'shared'),
            sharedPath('hubspot', 'shared', '?source_rows=all'),
            sharedPath('hubspot', 'shared', '?owner=1'),
        ]) {
            expect((await byExternalId('GET', path)).status).toBe(400)
        }
    })

    it('deletes the rows of every team and their secrets, once, and audits each row', async () => {
        const rows = await seed()
        const res = await byExternalId('DELETE', sharedPath('hubspot', 'shared'))
        expect(res.status).toBe(200)
        expect(res.json).toEqual({ deleted: 2 })

        expect(await rowCount('deleted_at IS NOT NULL')).toBe(2)
        expect(await rowCount('deleted_at IS NOT NULL AND id = ANY($1::uuid[])', [[rows.a.id, rows.b.id]])).toBe(2)
        const secrets = await pool.query('SELECT integration_id FROM integration_secrets')
        expect(secrets.rows.map((row) => row.integration_id).sort()).toEqual(
            [rows.c.id, rows.otherId.id, rows.otherKind.id].sort()
        )

        // A second call finds no live row.
        expect((await byExternalId('DELETE', sharedPath('hubspot', 'shared'))).json).toEqual({ deleted: 0 })

        const audited = (
            await pool.query(
                `SELECT owner_id, kind, integration_id FROM audit_log
             WHERE operation = 'delete_by_external_id' ORDER BY owner_id`
            )
        ).rows
        expect(audited.map((row) => [row.owner_id, row.kind, row.integration_id])).toEqual([
            [String(TEAM_A), 'hubspot', rows.a.id],
            [String(TEAM_B), 'hubspot', rows.b.id],
        ])

        // The unique key is free again.
        await create({ integration_id: 'shared' }, { team: TEAM_A })
    })

    it('deletes source rows only when asked', async () => {
        const rows = await seed()
        const res = await byExternalId('DELETE', sharedPath('hubspot', 'shared', '?source_rows=only'))
        expect(res.json).toEqual({ deleted: 1 })
        expect(await rowCount('id = $1 AND deleted_at IS NOT NULL', [rows.c.id])).toBe(1)
    })

    it('audits every row a list returns, with its own owner', async () => {
        await seed()
        await byExternalId('GET', sharedPath('hubspot', 'shared'))
        const rows = (await auditRows()).filter((row) => row.operation === 'read_by_external_id')
        expect(rows.map((row) => row.owner_id).sort()).toEqual([String(TEAM_A), String(TEAM_B)])
    })
})

describe('delete owner', () => {
    const ownerOps: IntegrationOp[] = ['delete_owner']

    it('deletes every row and secret of the owner and no other, then does nothing the second time', async () => {
        const a1 = await create({ integration_id: 'a1' }, { team: TEAM_A })
        const a2 = await create({ kind: 'slack', integration_id: 'a2', is_source_row: true }, { team: TEAM_A })
        const b1 = await create({ integration_id: 'a1' }, { team: TEAM_B })
        await call('POST', '/', {
            body: newIntegration({ integration_id: 'keyed' }),
            headers: { 'Idempotency-Key': 'owner-delete-key' },
        })

        const res = await call('DELETE', `/?owner=${TEAM_A}`, { ops: ownerOps })
        expect(res.status).toBe(200)
        expect(res.json).toEqual({ deleted: 3 })

        expect(await rowCount('owner_id = $1 AND deleted_at IS NULL', [TEAM_A])).toBe(0)
        expect(await rowCount('owner_id = $1 AND deleted_at IS NULL', [TEAM_B])).toBe(1)
        const secrets = await pool.query('SELECT integration_id FROM integration_secrets')
        expect(secrets.rows.map((row) => row.integration_id)).toEqual([b1.id])
        expect((await pool.query('SELECT 1 FROM idempotency_keys')).rowCount).toBe(0)
        expect((await call('GET', `/${a1.id}`)).status).toBe(404)
        expect((await call('GET', `/${a2.id}`)).status).toBe(404)

        expect((await call('DELETE', `/?owner=${TEAM_A}`, { ops: ownerOps })).json).toEqual({ deleted: 0 })

        const audited = (await auditRows()).filter((row) => row.operation === 'delete_owner')
        expect(audited).toHaveLength(3)
        expect(audited.every((row) => row.owner_id === String(TEAM_A))).toBe(true)
    })

    it('deletes more rows than one batch holds', async () => {
        await pool.query(
            `INSERT INTO integrations (owner_type, owner_id, kind, external_id, auth_type)
             SELECT 'team', $1, 'hubspot', 'bulk-' || n, 'oauth' FROM generate_series(1, 1100) AS n`,
            [TEAM_A]
        )
        const res = await call('DELETE', `/?owner=${TEAM_A}`, { ops: ownerOps })
        expect(res.json).toEqual({ deleted: 1100 })
        expect(await rowCount('deleted_at IS NULL')).toBe(0)
        expect((await auditRows()).filter((row) => row.operation === 'delete_owner')).toHaveLength(1100)
    })

    it.each([
        ['another owner than the token', `/?owner=${TEAM_B}`, {}, 403],
        ['no owner', '/', {}, 400],
        ['a bad owner', '/?owner=abc', {}, 400],
        ['an unknown parameter', `/?owner=${TEAM_A}&kind=hubspot`, {}, 400],
        ['a token that names kinds', `/?owner=${TEAM_A}`, { kinds: ['hubspot'] }, 403],
        ['a worker deployment', `/?owner=${TEAM_A}`, { deployment: WORKER }, 403],
        ['a cdp deployment', `/?owner=${TEAM_A}`, { deployment: CDP }, 403],
        ['a token without the op', `/?owner=${TEAM_A}`, { ops: ['write'] as IntegrationOp[] }, 403],
        ['a token without an owner', `/?owner=${TEAM_A}`, { team: null }, 401],
    ])('refuses %s and deletes nothing', async (_label, path, opts: CallOptions, status) => {
        await create({}, { team: TEAM_A })
        await create({}, { team: TEAM_B })
        const res = await call('DELETE', path, { ops: ownerOps, ...opts })
        expect(res.status).toBe(status)
        expect(await rowCount('deleted_at IS NULL')).toBe(2)
    })
})

describe('reverse_sync', () => {
    const changeOps: IntegrationOp[] = ['reverse_sync']

    async function changes(query = '', opts: CallOptions = {}): Promise<CallResult> {
        return call('GET', `/changes${query}`, { deployment: REVERSE_SYNC, team: null, ops: changeOps, ...opts })
    }

    it.each([
        ['the reverse-sync deployment', REVERSE_SYNC, 200],
        ['the web deployment', WEB, 403],
        ['a worker deployment', WORKER, 403],
        ['a cdp deployment', CDP, 403],
    ])('is allowed or refused for %s', async (_label, deployment, status) => {
        expect((await changes('', { deployment })).status).toBe(status)
    })

    it('refuses a token without the op, and a token that names refs', async () => {
        const created = await create()
        expect((await changes('', { ops: ['read'], team: TEAM_A })).status).toBe(403)
        expect((await changes('', { refs: [created.id] })).status).toBe(403)
    })

    it('returns the rows of every team in change order, with the whole secret blob, and audits each row', async () => {
        const a = await create({ integration_id: 'a' }, { team: TEAM_A })
        const b = await create({ integration_id: 'b' }, { team: TEAM_B })
        const bare = await create({ integration_id: 'bare', sensitive_config: {} }, { team: TEAM_A })

        const res = await changes()
        expect(res.status).toBe(200)
        expect(res.headers.get('Cache-Control')).toBe('no-store')
        expect(res.json.results.map((item: any) => item.record.id)).toEqual([a.id, b.id, bare.id])
        expect(res.json.results[0]).toMatchObject({
            deleted: false,
            secret: { access_token: ACCESS_TOKEN, refresh_token: REFRESH_TOKEN, client_secret: CLIENT_SECRET },
            secret_error: null,
        })
        expect(res.json.results[2].secret).toEqual({})
        expect(res.json.next).toEqual(expect.any(String))

        const audited = (await auditRows()).filter((row) => row.operation === 'reverse_sync')
        expect(audited.map((row) => [row.owner_id, row.fields])).toEqual([
            [String(TEAM_A), ['access_token', 'client_secret', 'refresh_token']],
            [String(TEAM_B), ['access_token', 'client_secret', 'refresh_token']],
            [String(TEAM_A), []],
        ])
    })

    it('returns the current secret on every live row, and tombstones for deletes', async () => {
        const a = await create({ integration_id: 'a' }, { team: TEAM_A })
        const b = await create({ integration_id: 'b' }, { team: TEAM_A })
        const c = await create({ integration_id: 'c' }, { team: TEAM_A })
        const first = await changes()
        expect(first.json.results).toHaveLength(3)

        await call('PATCH', `/${a.id}`, { body: { config_patch: { refreshed_at: 1_800_000_500 } } })
        await call('PATCH', `/${b.id}`, { body: { sensitive_config_patch: { access_token: 'fake-rotated-token' } } })
        await call('PATCH', `/${c.id}`, {
            body: { sensitive_config_remove: ['access_token', 'refresh_token', 'client_secret'] },
        })
        const deleted = await create({ integration_id: 'd' })
        await call('DELETE', `/${deleted.id}`)

        const second = await changes(`?since=${first.json.next}`)
        const byId = Object.fromEntries(second.json.results.map((item: any) => [item.record.id, item]))
        expect(Object.keys(byId).sort()).toEqual([a.id, b.id, c.id, deleted.id].sort())
        expect(byId[a.id]).toMatchObject({
            secret: { access_token: ACCESS_TOKEN, refresh_token: REFRESH_TOKEN, client_secret: CLIENT_SECRET },
            deleted: false,
        })
        expect(byId[a.id].record.config.refreshed_at).toBe(1_800_000_500)
        expect(byId[b.id].secret).toEqual({
            access_token: 'fake-rotated-token',
            refresh_token: REFRESH_TOKEN,
            client_secret: CLIENT_SECRET,
        })
        // A removed secret reads as an empty blob, so the reader can clear its copy.
        expect(byId[c.id].secret).toEqual({})
        expect(byId[deleted.id]).toMatchObject({ deleted: true, secret: {} })

        // With nothing new, the cursor stays.
        const third = await changes(`?since=${second.json.next}`)
        expect(third.json).toEqual({ results: [], next: second.json.next })
    })

    it('reports a deleted team as tombstones', async () => {
        await create({ integration_id: 'a' }, { team: TEAM_A })
        const first = await changes()
        await call('DELETE', `/?owner=${TEAM_A}`, { ops: ['delete_owner'] })
        const second = await changes(`?since=${first.json.next}`)
        expect(second.json.results.map((item: any) => item.deleted)).toEqual([true])
    })

    it('pages without gaps or repeats, also when many rows share one timestamp', async () => {
        await pool.query(
            `INSERT INTO integrations (owner_type, owner_id, kind, external_id, auth_type)
             SELECT 'team', $1, 'hubspot', 'same-' || n, 'oauth' FROM generate_series(1, 7) AS n`,
            [TEAM_A]
        )
        const seen: string[] = []
        let since = ''
        for (let page = 0; page < 10; page++) {
            const res = await changes(`?limit=3${since}`)
            const ids = res.json.results.map((item: any) => item.record.id)
            seen.push(...ids)
            since = `&since=${res.json.next}`
            if (ids.length < 3) {
                break
            }
        }
        const stored = await pool.query('SELECT id FROM integrations')
        expect(seen).toHaveLength(7)
        expect(new Set(seen)).toEqual(new Set(stored.rows.map((row) => row.id)))
    })

    it('does not pass a row that a slower transaction has not committed yet', async () => {
        const slow = await create({ integration_id: 'slow' })
        const fast = await create({ integration_id: 'fast' })
        const settling = buildApp(kms, undefined, 2)
        await new Promise((resolve) => setTimeout(resolve, 2100))
        const baseline = await changes('', { target: settling })
        expect(baseline.json.results).toHaveLength(2)

        // The transaction starts first, so its updated_at is the older one. It commits last.
        const client = await pool.connect()
        try {
            await client.query('BEGIN')
            await client.query('UPDATE integrations SET updated_at = now(), version = version + 1 WHERE id = $1', [
                slow.id,
            ])
            await call('PATCH', `/${fast.id}`, { body: { config_patch: { refreshed_at: 1_800_000_500 } } })

            // The fast row is newer than the open transaction. The feed must not return it yet.
            const during = await changes(`?since=${baseline.json.next}`, { target: settling })
            expect(during.json).toEqual({ results: [], next: baseline.json.next })
            await client.query('COMMIT')
        } finally {
            client.release()
        }

        await new Promise((resolve) => setTimeout(resolve, 2100))
        const after = await changes(`?since=${baseline.json.next}`, { target: settling })
        expect(after.json.results.map((item: any) => item.record.id)).toEqual([slow.id, fast.id])
    })

    it('limits a request to the kinds it names, and to the kinds of the token', async () => {
        const hubspot = await create({ integration_id: 'h' })
        const slack = await create({ kind: 'slack', integration_id: 's' })
        const ids = (res: CallResult): string[] => res.json.results.map((item: any) => item.record.id)

        expect(ids(await changes('?kind=slack'))).toEqual([slack.id])
        expect(ids(await changes('', { kinds: ['hubspot'] }))).toEqual([hubspot.id])
        expect((await changes('?kind=slack', { kinds: ['hubspot'] })).status).toBe(403)
    })

    it.each([
        ['a bad limit', '?limit=0'],
        ['a limit over the maximum', '?limit=501'],
        ['a bad cursor', '?since=not-a-cursor'],
        ['an unknown parameter', '?team_id=1'],
    ])('rejects %s', async (_label, query) => {
        expect((await changes(query)).status).toBe(400)
    })

    it('reports a secret that cannot be opened for its row and keeps the feed going', async () => {
        const broken = await create({ integration_id: 'broken' })
        const fine = await create({ integration_id: 'fine' })
        await pool.query(`UPDATE integration_secrets SET ciphertext = '\\x00'::bytea WHERE integration_id = $1`, [
            broken.id,
        ])
        const res = await changes()
        expect(res.status).toBe(200)
        expect(res.json.results[0]).toMatchObject({ secret: null, secret_error: 'unreadable_secret' })
        expect(res.json.results[1]).toMatchObject({ secret_error: null })
        expect(res.json.results[1].record.id).toBe(fine.id)
        const audited = (await auditRows()).filter((row) => row.operation === 'reverse_sync')
        expect(audited.map((row) => row.outcome)).toEqual(['unreadable_secret', 'ok'])
    })

    it('answers kms_unavailable when the key service is down, so the poller retries', async () => {
        await create()
        class DownKms implements Kms {
            readonly provider = 'local'
            async generateDataKey(): Promise<never> {
                throw new KmsError('unavailable', 'KMS did not answer')
            }
            async decrypt(): Promise<never> {
                throw new KmsError('unavailable', 'KMS did not answer')
            }
            async rewrap(): Promise<never> {
                throw new KmsError('unavailable', 'KMS did not answer')
            }
        }
        const res = await changes('', { target: buildApp(new DownKms()) })
        expect(res.status).toBe(503)
    })
})
