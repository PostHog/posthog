// Runs the migrations and the data-access queries against a real Postgres in a container, and
// boots a real server with and without a database.

import { serve } from '@hono/node-server'
import type { StartedPostgreSqlContainer } from '@testcontainers/postgresql'
import { SignJWT } from 'jose'
import { generateKeyPairSync, randomBytes } from 'node:crypto'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Pool } from 'pg'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { PostgresReplayStore } from '@/auth/replay-postgres'
import { AUDIENCE } from '@/auth/types'
import {
    getIntegration,
    insertIntegration,
    softDeleteIntegration,
    updateIntegration,
    type IntegrationOwner,
    type NewIntegration,
} from '@/db/integrations'
import { runMigrations } from '@/db/migrate'
import type { Config, DatabaseConfig, KmsConfig } from '@/lib/config'
import { CredentialsServer } from '@/server'

import { createAuditExtensions, startPostgresWithPartman } from './postgres'

const MIGRATIONS = [
    '1794323815130_initial-schema',
    '1794323815131_runtime-role-grants',
    '1794323815132_idempotency-deployment',
    '1794400000000_integrations-changes-index',
    '1794400000001_audit-exported-at',
    '1794400000002_audit-partman',
]
const TABLES = ['audit_log', 'audit_log_default', 'auth_jti', 'idempotency_keys', 'integration_secrets', 'integrations']
// pg_cron runs in this one database of the cluster, so every test that migrates with a runtime
// role, the way a deployed environment does, shares it.
const DEPLOYED_DATABASE = 'deployed'
const RUNTIME_ROLE = 'credentials_runtime_test'
const RUNTIME_PASSWORD = 'not-a-real-password'
const TEAM: IntegrationOwner = { type: 'team', id: 1 }
const OTHER_TEAM: IntegrationOwner = { type: 'team', id: 2 }

let container: StartedPostgreSqlContainer
let pool: Pool

function databaseUrl(database: string): string {
    const url = new URL(container.getConnectionUri())
    url.pathname = `/${database}`
    return url.toString()
}

async function createDatabase(name: string): Promise<string> {
    await pool.query(`CREATE DATABASE ${name}`)
    return databaseUrl(name)
}

let deployed: Promise<{ url: string; runtimeUrl: string }> | undefined

/**
 * Migrated with the runtime role. Rows written before the pg_partman migration, today and 10 days
 * ago, sit in the default partition until that migration runs.
 */
function deployedDatabase(): Promise<{ url: string; runtimeUrl: string }> {
    deployed ??= (async () => {
        const url = await createDatabase(DEPLOYED_DATABASE)
        await createAuditExtensions(url)
        await runMigrations({
            databaseUrl: url,
            direction: 'up',
            runtimeRole: RUNTIME_ROLE,
            count: MIGRATIONS.length - 1,
        })
        const db = new Pool({ connectionString: url })
        try {
            await db.query(
                `INSERT INTO audit_log (deployment, operation, outcome, occurred_at)
                 VALUES ('d', 'before-partman', 'ok', now()), ('d', 'before-partman', 'ok', now() - interval '10 days')`
            )
        } finally {
            await db.end()
        }
        await runMigrations({ databaseUrl: url, direction: 'up', runtimeRole: RUNTIME_ROLE })
        const runtimeUrl = new URL(url)
        runtimeUrl.username = RUNTIME_ROLE
        runtimeUrl.password = RUNTIME_PASSWORD
        return { url, runtimeUrl: runtimeUrl.toString() }
    })()
    return deployed
}

async function tables(url: string): Promise<string[]> {
    const client = new Pool({ connectionString: url })
    try {
        const result = await client.query<{ table_name: string }>(
            `SELECT table_name FROM information_schema.tables
             WHERE table_schema = 'public' AND table_name <> 'pgmigrations'
             ORDER BY table_name`
        )
        return result.rows.map((row) => row.table_name)
    } finally {
        await client.end()
    }
}

beforeAll(async () => {
    container = await startPostgresWithPartman(DEPLOYED_DATABASE)
    pool = new Pool({ connectionString: container.getConnectionUri() })
    await pool.query(`CREATE ROLE ${RUNTIME_ROLE} LOGIN PASSWORD '${RUNTIME_PASSWORD}'`)
}, 300_000)

afterAll(async () => {
    await pool?.end()
    await container?.stop()
})

describe('migrations', () => {
    it('apply cleanly, revert cleanly and apply again', async () => {
        const url = await createDatabase('migrations_round_trip')

        expect(await runMigrations({ databaseUrl: url, direction: 'up', partmanOptional: true })).toEqual(MIGRATIONS)
        expect(await tables(url)).toEqual(TABLES)
        expect(await runMigrations({ databaseUrl: url, direction: 'up' })).toEqual([])

        expect(await runMigrations({ databaseUrl: url, direction: 'down', count: MIGRATIONS.length })).toEqual(
            [...MIGRATIONS].reverse()
        )
        expect(await tables(url)).toEqual([])

        expect(await runMigrations({ databaseUrl: url, direction: 'up', partmanOptional: true })).toEqual(MIGRATIONS)
        expect(await tables(url)).toEqual(TABLES)
    })

    it('refuses to set up audit retention without pg_partman and pg_cron by default', async () => {
        const url = await createDatabase('no_audit_extensions')
        await expect(runMigrations({ databaseUrl: url, direction: 'up' })).rejects.toThrow(
            'missing: {pg_cron,pg_partman}'
        )
    })

    it('skips audit retention without the extensions when partman is optional', async () => {
        const url = await createDatabase('optional_audit_extensions')
        expect(
            await runMigrations({ databaseUrl: url, direction: 'up', runtimeRole: RUNTIME_ROLE, partmanOptional: true })
        ).toEqual(MIGRATIONS)
    })
})

describe('runtime role grants', () => {
    let runtime: Pool

    beforeAll(async () => {
        runtime = new Pool({ connectionString: (await deployedDatabase()).runtimeUrl })
    })

    afterAll(async () => {
        await runtime?.end()
    })

    it('lets the runtime role write the integration tables and the replay table', async () => {
        await runtime.query(
            `INSERT INTO integrations (owner_type, owner_id, kind, auth_type) VALUES ('team', 1, 'slack', 'oauth')`
        )
        await runtime.query(`UPDATE integrations SET errors = 'x'`)
        await runtime.query(`INSERT INTO auth_jti (deployment, jti, expires_at) VALUES ('d', 'j', now())`)
        await runtime.query(`DELETE FROM auth_jti WHERE expires_at <= now()`)
        await runtime.query(`DELETE FROM integrations`)
    })

    // Postgres checks DML through audit_log against audit_log only, so the daily partitions need no grant.
    it('lets the runtime role append to and read the audit log', async () => {
        const inserted = await runtime.query<{ partition: string }>(
            `INSERT INTO audit_log (deployment, operation, outcome) VALUES ('d', 'read', 'ok')
             RETURNING tableoid::regclass::text AS partition`
        )
        expect(inserted.rows[0]?.partition).toMatch(/^audit_log_p\d{8}$/)
        const result = await runtime.query(`SELECT count(*)::int AS n FROM audit_log`)
        expect(result.rows[0].n).toBeGreaterThan(0)
    })

    it.each([
        ['UPDATE', `UPDATE audit_log SET outcome = 'forged'`],
        ['DELETE', `DELETE FROM audit_log`],
        ['TRUNCATE', `TRUNCATE audit_log`],
        ['UPDATE on the default partition', `UPDATE audit_log_default SET outcome = 'forged'`],
        ['DELETE on the default partition', `DELETE FROM audit_log_default`],
    ])('refuses %s on the audit log for the runtime role', async (_label, sql) => {
        await expect(runtime.query(sql)).rejects.toThrow(/permission denied/)
    })

    it('skips the grants when no runtime role is given', async () => {
        const url = await createDatabase('runtime_role_unset')
        expect(await runMigrations({ databaseUrl: url, direction: 'up', partmanOptional: true })).toEqual(MIGRATIONS)
    })
})

describe('postgres replay store', () => {
    let db: Pool
    let store: PostgresReplayStore

    beforeAll(async () => {
        const url = await createDatabase('replay_store')
        await runMigrations({ databaseUrl: url, direction: 'up', partmanOptional: true })
        db = new Pool({ connectionString: url })
        store = new PostgresReplayStore(db)
    })

    afterAll(async () => {
        await db?.end()
    })

    it('accepts a token id once per deployment', async () => {
        const expires = Date.now() + 60_000
        expect(await store.claim('web', 'jti-1', expires)).toBe(true)
        expect(await store.claim('web', 'jti-1', expires)).toBe(false)
        expect(await store.claim('worker', 'jti-1', expires)).toBe(true)
    })

    it('accepts only one of many concurrent claims of the same id', async () => {
        const results = await Promise.all(
            Array.from({ length: 8 }, () => store.claim('web', 'jti-race', Date.now() + 60_000))
        )
        expect(results.filter(Boolean)).toHaveLength(1)
    })

    it('deletes expired rows and keeps live ones', async () => {
        await store.claim('web', 'jti-old', Date.now() - 1000)
        await store.claim('web', 'jti-live', Date.now() + 60_000)
        await store.deleteExpired()
        const rows = await db.query<{ jti: string }>(`SELECT jti FROM auth_jti WHERE jti IN ('jti-old', 'jti-live')`)
        expect(rows.rows.map((row) => row.jti)).toEqual(['jti-live'])
    })
})

describe('audit_log partitions', () => {
    let db: Pool

    beforeAll(async () => {
        db = new Pool({ connectionString: (await deployedDatabase()).url })
    })

    afterAll(async () => {
        await db?.end()
    })

    it('moves rows written before pg_partman out of the default partition', async () => {
        const result = await db.query<{ partition: string }>(
            `SELECT tableoid::regclass::text AS partition FROM audit_log WHERE operation = 'before-partman'`
        )
        expect(result.rows).toHaveLength(2)
        for (const row of result.rows) {
            expect(row.partition).toMatch(/^audit_log_p\d{8}$/)
        }
    })

    it('drops daily partitions past 30 days on the hourly job, and keeps newer ones', async () => {
        const job = await db.query(
            `SELECT schedule, command, username FROM cron.job WHERE jobname = 'credentials-service-audit-partman'`
        )
        expect(job.rows).toEqual([
            {
                schedule: '17 * * * *',
                command: 'CALL public.audit_log_maintenance()',
                username: container.getUsername(),
            },
        ])

        await db.query(
            `SELECT partman.create_partition_time('public.audit_log', ARRAY[now() - interval '31 days', now() - interval '29 days'])`
        )
        const inserted = await db.query<{ operation: string; partition: string }>(
            `INSERT INTO audit_log (deployment, operation, outcome, occurred_at)
             VALUES ('d', 'expired', 'ok', now() - interval '31 days'), ('d', 'kept', 'ok', now() - interval '29 days')
             RETURNING operation, tableoid::regclass::text AS partition`
        )
        const partitionOf = (operation: string): string =>
            inserted.rows.find((row) => row.operation === operation)!.partition

        await db.query(`SELECT partman.run_maintenance('public.audit_log')`)

        const left = await db.query<{ operation: string }>(
            `SELECT operation FROM audit_log WHERE operation IN ('expired', 'kept')`
        )
        expect(left.rows).toEqual([{ operation: 'kept' }])
        const tables = await db.query<{ expired: string | null; kept: string | null }>(
            'SELECT to_regclass($1)::text AS expired, to_regclass($2)::text AS kept',
            [partitionOf('expired'), partitionOf('kept')]
        )
        expect(tables.rows[0]).toEqual({ expired: null, kept: partitionOf('kept') })
    })

    it('moves default-partition rows into daily partitions during maintenance', async () => {
        const inserted = await db.query<{ partition: string }>(
            `INSERT INTO audit_log (deployment, operation, outcome, occurred_at)
             VALUES ('d', 'late-maintenance', 'ok', now() + interval '10 days')
             RETURNING tableoid::regclass::text AS partition`
        )
        expect(inserted.rows[0]?.partition).toBe('audit_log_default')

        await db.query('CALL public.audit_log_maintenance()')

        const moved = await db.query<{ partition: string }>(
            `SELECT tableoid::regclass::text AS partition FROM audit_log WHERE operation = 'late-maintenance'`
        )
        expect(moved.rows[0]?.partition).toMatch(/^audit_log_p\d{8}$/)
    })
})

describe('integrations queries', () => {
    let db: Pool

    it('serves the change feed page from the (updated_at, id) index', async () => {
        await db.query(
            `INSERT INTO integrations (owner_type, owner_id, kind, external_id, auth_type)
             SELECT 'team', n % 50, 'hubspot', 'feed-' || n, 'oauth' FROM generate_series(1, 2000) AS n`
        )
        await db.query('ANALYZE integrations')
        const plan = await db.query(
            `EXPLAIN SELECT id FROM integrations
             WHERE owner_type = 'team' AND updated_at <= statement_timestamp() - interval '30 seconds'
               AND (updated_at, id) > (now() - interval '1 hour', gen_random_uuid())
             ORDER BY updated_at, id LIMIT 100`
        )
        const text = plan.rows.map((row) => row['QUERY PLAN']).join('\n')
        expect(text).toContain('integrations_updated_at_id')
        expect(text).not.toContain('Sort')
    })

    beforeAll(async () => {
        const url = await createDatabase('integrations_queries')
        await runMigrations({ databaseUrl: url, direction: 'up', partmanOptional: true })
        db = new Pool({ connectionString: url })
    })

    afterAll(async () => {
        await db?.end()
    })

    beforeEach(async () => {
        await db.query('TRUNCATE integrations CASCADE')
    })

    function slack(overrides: Partial<NewIntegration> = {}): NewIntegration {
        return { owner: TEAM, kind: 'slack', externalId: 'T0001', authType: 'oauth', ...overrides }
    }

    async function insertOk(input: NewIntegration): Promise<string> {
        const result = await insertIntegration(db, input)
        if (result.status !== 'ok') {
            throw new Error(`insert returned ${result.status}`)
        }
        return result.row.id
    }

    it.each([
        ['the same owner, kind and external id', slack(), 'conflict'],
        ['another owner', slack({ owner: OTHER_TEAM }), 'ok'],
        ['another kind', slack({ kind: 'hubspot' }), 'ok'],
        ['another external id', slack({ externalId: 'T0002' }), 'ok'],
        ['the same legacy id as the first row', slack({ owner: OTHER_TEAM, legacyId: 7 }), 'conflict'],
    ] as const)('a second live row with %s returns %s', async (_label, second, expected) => {
        await insertOk(slack({ legacyId: 7 }))
        expect((await insertIntegration(db, second)).status).toBe(expected)
    })

    // The Django constraint treats NULL ids as distinct, and the backfill copies those rows as-is.
    it('allows several live rows with no external id', async () => {
        await insertOk(slack({ externalId: null }))
        expect((await insertIntegration(db, slack({ externalId: null }))).status).toBe('ok')
    })

    it('allows the same external id again once the first row is soft deleted', async () => {
        const first = await insertOk(slack())
        expect((await softDeleteIntegration(db, TEAM, { id: first })).status).toBe('ok')

        const second = await insertOk(slack())

        expect(await getIntegration(db, TEAM, { id: first })).toBeNull()
        expect((await getIntegration(db, TEAM, { id: second }))?.externalId).toBe('T0001')
    })

    it('reads a row by its UUID and by its legacy id, only for its own owner', async () => {
        const id = await insertOk(slack({ legacyId: 42, config: { team: { name: 'Example' } }, createdById: 7 }))

        const byId = await getIntegration(db, TEAM, { id })
        expect(byId).toMatchObject({
            id,
            legacyId: 42,
            ownerType: 'team',
            ownerId: 1,
            config: { team: { name: 'Example' } },
            createdById: 7,
            errors: '',
            version: 1,
            refreshState: 'idle',
        })
        expect(await getIntegration(db, TEAM, { legacyId: 42 })).toEqual(byId)

        expect(await getIntegration(db, OTHER_TEAM, { id })).toBeNull()
        expect(await getIntegration(db, OTHER_TEAM, { legacyId: 42 })).toBeNull()
    })

    it('updates only with the current version, and bumps it', async () => {
        const id = await insertOk(slack())

        const updated = await updateIntegration(db, TEAM, { id }, 1, { errors: 'token expired', config: { a: 1 } })
        expect(updated).toMatchObject({ status: 'ok', row: { version: 2, errors: 'token expired', config: { a: 1 } } })

        const stale = await updateIntegration(db, TEAM, { id }, 1, { errors: 'lost update' })
        expect(stale).toEqual({ status: 'version_mismatch', currentVersion: 2 })
        expect((await getIntegration(db, TEAM, { id }))?.errors).toBe('token expired')
    })

    it.each([
        ['another owner', OTHER_TEAM, false],
        ['a soft-deleted row', TEAM, true],
    ])('does not update %s', async (_label, owner, deleteFirst) => {
        const id = await insertOk(slack())
        if (deleteFirst) {
            await softDeleteIntegration(db, TEAM, { id })
        }

        expect(await updateIntegration(db, owner, { id }, deleteFirst ? 2 : 1, { errors: 'x' })).toEqual({
            status: 'not_found',
        })
    })

    it('returns conflict when an update moves a row onto another live external id', async () => {
        await insertOk(slack({ externalId: 'T0002' }))
        const id = await insertOk(slack())

        expect(await updateIntegration(db, TEAM, { id }, 1, { externalId: 'T0002' })).toEqual({ status: 'conflict' })
    })

    it('soft deletes only with the current version when one is given', async () => {
        const id = await insertOk(slack())
        await updateIntegration(db, TEAM, { id }, 1, { errors: 'x' })

        expect(await softDeleteIntegration(db, TEAM, { id }, { expectedVersion: 1 })).toEqual({
            status: 'version_mismatch',
            currentVersion: 2,
        })
        expect(await softDeleteIntegration(db, OTHER_TEAM, { id })).toEqual({ status: 'not_found' })

        const deleted = await softDeleteIntegration(db, TEAM, { id }, { expectedVersion: 2 })
        expect(deleted).toMatchObject({ status: 'ok', row: { version: 3 } })
        expect(deleted.status === 'ok' && deleted.row.deletedAt).toBeInstanceOf(Date)

        expect(await softDeleteIntegration(db, TEAM, { id })).toEqual({ status: 'not_found' })
    })

    it('stores audit rows in the default partition until daily partitions exist', async () => {
        await db.query(`INSERT INTO audit_log (deployment, operation, outcome) VALUES ('posthog-django', 'read', 'ok')`)

        const result = await db.query<{ partition: string }>(
            `SELECT tableoid::regclass::text AS partition FROM audit_log`
        )
        expect(result.rows).toEqual([{ partition: 'audit_log_default' }])
    })

    it('expires idempotency keys 24 hours after they are stored', async () => {
        const result = await db.query<{ seconds: string }>(
            `INSERT INTO idempotency_keys (deployment, owner_type, owner_id, operation, key, request_hash)
             VALUES ('posthog-django', 'team', 1, 'create', 'key-1', '\\x00')
             RETURNING extract(epoch FROM expires_at - created_at)::text AS seconds`
        )
        expect(Number(result.rows[0]?.seconds)).toBe(24 * 60 * 60)
    })
})

describe('server readiness with a database', () => {
    const SIGNING_KEY = 'database-e2e-signing-key'
    const KEY = 'HUBSPOT_APP_CLIENT_SECRET'
    const dirs: string[] = []
    const servers: CredentialsServer[] = []

    afterEach(async () => {
        await Promise.all(servers.splice(0).map((server) => server.stop('test')))
        await Promise.all(dirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })))
    })

    async function boot(
        database: DatabaseConfig | undefined,
        kms?: KmsConfig,
        withIntegrationKeys = false,
        env = 'test'
    ): Promise<number> {
        const mountDir = await mkdtemp(join(tmpdir(), 'credentials-db-e2e-'))
        dirs.push(mountDir)
        await writeFile(join(mountDir, KEY), 'not-a-real-secret')
        await writeFile(join(mountDir, '__CALLER_KEY_TEST_DEPLOYMENT'), SIGNING_KEY)

        const config: Config = {
            port: 0,
            host: '127.0.0.1',
            shutdownPrestopDelayMs: 0,
            env,
            mountDir,
            reloadSeconds: 3600,
            metricsPort: 0,
        }
        if (database) {
            config.database = database
        }
        if (kms) {
            config.kms = kms
        }
        if (withIntegrationKeys) {
            const integrationKeysDir = await mkdtemp(join(tmpdir(), 'credentials-integration-keys-e2e-'))
            dirs.push(integrationKeysDir)
            const { publicKey } = generateKeyPairSync('ed25519')
            await writeFile(
                join(integrationKeysDir, 'posthog-web-django.pub'),
                publicKey.export({ type: 'spki', format: 'pem' })
            )
            config.integrationCallerPublicKeysDir = integrationKeysDir
        }

        let announce!: (port: number) => void
        const listening = new Promise<number>((resolve) => {
            announce = resolve
        })
        const server = new CredentialsServer(config, {
            serve: (options, listener) =>
                serve(options, (info) => {
                    listener(info)
                    announce(info.port)
                }),
            exit: () => undefined,
        })
        servers.push(server)
        await server.start()
        return listening
    }

    function bootedServer(): CredentialsServer {
        return servers[servers.length - 1]!
    }

    async function resolveStatus(port: number): Promise<number> {
        const token = await new SignJWT({ caller: 'warehouse-sources', keys: [KEY] })
            .setProtectedHeader({ alg: 'HS256' })
            .setAudience(AUDIENCE)
            .setIssuedAt()
            .setExpirationTime('5m')
            .sign(new TextEncoder().encode(SIGNING_KEY))
        const res = await fetch(`http://127.0.0.1:${port}/v1/secrets/resolve`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${token}` },
        })
        return res.status
    }

    // An unreachable database keeps a new pod out of rotation, but the platform secrets route
    // never needs the database.
    it.each([
        ['no database configured', () => undefined, 200],
        ['a reachable database', () => ({ url: container.getConnectionUri(), poolSize: 2 }), 200],
        [
            'an unreachable database',
            () => ({ url: 'postgres://credentials:not-a-real-password@127.0.0.1:1/credentials', poolSize: 2 }),
            503,
        ],
    ])('with %s, readiness answers %i and platform secrets still resolve', async (_label, database, readiness) => {
        const port = await boot(database())

        expect((await fetch(`http://127.0.0.1:${port}/_readiness`)).status).toBe(readiness)
        expect(await resolveStatus(port)).toBe(200)
    })

    // Integration routes need a database, a KMS, and public keys.
    it.each([
        ['a database, a KMS, and public keys', true, true, 401],
        ['a database and a KMS without public keys', true, false, 404],
        ['a database and no KMS', false, true, 404],
    ])('with %s, the integration routes answer %i', async (_label, withKms, withKeys, status) => {
        const kms: KmsConfig | undefined = withKms ? { provider: 'local', keys: [randomBytes(32)] } : undefined
        const port = await boot({ url: container.getConnectionUri(), poolSize: 2 }, kms, withKeys)

        expect((await fetch(`http://127.0.0.1:${port}/v1/integrations`)).status).toBe(status)
        expect(await resolveStatus(port)).toBe(200)
    })

    // The audit log has daily partitions here, as in a deployed environment.
    describe('runtime role check', () => {
        let migratedUrl: string
        let runtimeUrl: string

        beforeAll(async () => {
            ;({ url: migratedUrl, runtimeUrl } = await deployedDatabase())
        })

        const ownerUser = (): string => new URL(migratedUrl).username

        // The owner of audit_log can rewrite it, so production refuses to serve integrations
        // with that role. Platform secrets keep serving and the pod stays ready.
        it.each([
            ['prod-us', 'the owner role', () => ({ url: migratedUrl, poolSize: 2 }), false],
            ['prod-eu', 'the owner role', () => ({ url: migratedUrl, poolSize: 2 }), false],
            ['production', 'the owner role', () => ({ url: migratedUrl, poolSize: 2 }), false],
            [
                'prod-us',
                'a limited role that shares the migrate user',
                () => ({ url: runtimeUrl, poolSize: 2, migrateUser: RUNTIME_ROLE }),
                false,
            ],
            ['dev', 'the owner role', () => ({ url: migratedUrl, poolSize: 2 }), true],
            ['test', 'the owner role', () => ({ url: migratedUrl, poolSize: 2 }), true],
            [
                'dev',
                'a limited role that shares the migrate user',
                () => ({ url: runtimeUrl, poolSize: 2, migrateUser: RUNTIME_ROLE }),
                true,
            ],
            ['prod-us', 'a separate limited role', () => ({ url: runtimeUrl, poolSize: 2 }), true],
            [
                'prod-eu',
                'a separate limited role with a different migrate user',
                () => ({ url: runtimeUrl, poolSize: 2, migrateUser: ownerUser() }),
                true,
            ],
        ] as [string, string, () => DatabaseConfig, boolean][])(
            'in %s with %s, integrations enabled is %s',
            async (env, _label, database, enabled) => {
                const port = await boot(database(), undefined, false, env)

                expect(bootedServer().integrationsPool() !== undefined).toBe(enabled)
                expect((await fetch(`http://127.0.0.1:${port}/_readiness`)).status).toBe(200)
                expect(await resolveStatus(port)).toBe(200)
            }
        )

        it.each([
            ['prod-us', () => ({ url: migratedUrl, poolSize: 2 }), 404],
            ['prod-us', () => ({ url: runtimeUrl, poolSize: 2 }), 401],
            ['dev', () => ({ url: migratedUrl, poolSize: 2 }), 401],
        ] as [string, () => DatabaseConfig, number][])(
            'in %s, the integration routes answer %i with the role as configured',
            async (env, database, status) => {
                const kms: KmsConfig = { provider: 'local', keys: [randomBytes(32)] }
                const port = await boot(database(), kms, true, env)

                expect((await fetch(`http://127.0.0.1:${port}/v1/integrations`)).status).toBe(status)
            }
        )

        it.each([
            ['DELETE on the default partition', (role: string) => `GRANT DELETE ON audit_log_default TO ${role}`],
            ['TRUNCATE on the default partition', (role: string) => `GRANT TRUNCATE ON audit_log_default TO ${role}`],
            ['column UPDATE on the audit log', (role: string) => `GRANT UPDATE (outcome) ON audit_log TO ${role}`],
            [
                'NOINHERIT membership in the audit log owner',
                (role: string) =>
                    `DO $$ BEGIN EXECUTE format('GRANT %I TO ${role} WITH INHERIT FALSE', ` +
                    `(SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'audit_log'::regclass)); END $$`,
            ],
        ])('refuses a runtime role with %s', async (_label, grant) => {
            const role = `credentials_guard_${Math.random().toString(36).slice(2, 10)}`
            await pool.query(`CREATE ROLE ${role} LOGIN PASSWORD '${RUNTIME_PASSWORD}'`)
            const url = new URL(migratedUrl)
            url.username = role
            url.password = RUNTIME_PASSWORD
            const db = new Pool({ connectionString: migratedUrl })
            try {
                await db.query(`GRANT SELECT, INSERT ON audit_log TO ${role}`)
                await db.query(grant(role))
            } finally {
                await db.end()
            }

            await boot({ url: url.toString(), poolSize: 2 }, undefined, false, 'prod-us')

            expect(bootedServer().integrationsPool()).toBeUndefined()
        })

        it('refuses a runtime role that owns the schema of the audit log', async () => {
            const role = `credentials_guard_${Math.random().toString(36).slice(2, 10)}`
            await pool.query(`CREATE ROLE ${role} LOGIN PASSWORD '${RUNTIME_PASSWORD}'`)
            const url = new URL(migratedUrl)
            url.username = role
            url.password = RUNTIME_PASSWORD
            const db = new Pool({ connectionString: migratedUrl })
            const schema = await db.query<{ nspname: string; owner: string }>(
                `SELECT n.nspname, pg_get_userbyid(n.nspowner) AS owner
                 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE c.oid = 'audit_log'::regclass`
            )
            const row = schema.rows[0]
            if (!row) {
                throw new Error('audit_log has no schema')
            }
            const { nspname, owner } = row
            try {
                await db.query(`GRANT SELECT, INSERT ON audit_log TO ${role}`)
                await db.query(`ALTER SCHEMA "${nspname}" OWNER TO ${role}`)

                await boot({ url: url.toString(), poolSize: 2 }, undefined, false, 'prod-us')

                expect(bootedServer().integrationsPool()).toBeUndefined()
            } finally {
                await db.query(`ALTER SCHEMA "${nspname}" OWNER TO "${owner}"`)
                await db.end()
            }
        })

        it.each(['Prod-us', 'prod_us', 'PRODUCTION'])('treats the typo %s as production', async (env) => {
            await boot({ url: migratedUrl, poolSize: 2 }, undefined, false, env)

            expect(bootedServer().integrationsPool()).toBeUndefined()
        })
    })
})
