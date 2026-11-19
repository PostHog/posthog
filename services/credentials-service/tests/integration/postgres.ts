// Postgres for the integration tests that migrate the way a deployed environment does: with a
// runtime role, so the audit_log migration needs pg_partman and pg_cron.

import { PostgreSqlContainer, type StartedPostgreSqlContainer } from '@testcontainers/postgresql'
import { join } from 'node:path'
import { Pool } from 'pg'
import { GenericContainer } from 'testcontainers'

const IMAGE = 'posthog-credentials-service-test-postgres:17'

/** pg_cron runs in one database per cluster, so only `cronDatabase` can hold the extensions. */
export async function startPostgresWithPartman(cronDatabase: string): Promise<StartedPostgreSqlContainer> {
    await GenericContainer.fromDockerfile(join(import.meta.dirname, 'postgres')).build(IMAGE, {
        deleteOnExit: false,
    })
    return new PostgreSqlContainer(IMAGE)
        .withCommand(['postgres', '-c', 'shared_preload_libraries=pg_cron', '-c', `cron.database_name=${cronDatabase}`])
        .start()
}

/** What infra does on the deployed database, as the master user, before the migrations run. */
export async function createAuditExtensions(databaseUrl: string): Promise<void> {
    const pool = new Pool({ connectionString: databaseUrl })
    try {
        await pool.query('CREATE SCHEMA IF NOT EXISTS partman')
        await pool.query('CREATE EXTENSION IF NOT EXISTS pg_partman SCHEMA partman')
        await pool.query('CREATE EXTENSION IF NOT EXISTS pg_cron')
    } finally {
        await pool.end()
    }
}
