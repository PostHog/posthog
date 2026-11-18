import { runner, type RunnerOption } from 'node-pg-migrate'

import { logger } from '../lib/logging'

/** Relative to the working directory: the package root in dev and tests, /code in the image. */
export const MIGRATIONS_DIR = 'migrations'

export const MIGRATIONS_TABLE = 'pgmigrations'

const CONNECTION_TIMEOUT_MS = 10_000

type MigrationDirection = RunnerOption['direction']

export interface MigrateOptions {
    databaseUrl: string
    direction: MigrationDirection
    /** How many migrations to run. Every pending one when unset for `up`, one for `down`. */
    count?: number
    dir?: string
    /** The role that gets the runtime grants. Unset skips them. */
    runtimeRole?: string
}

/** Applies or reverts the SQL migrations. Returns the names of the migrations it ran. */
export async function runMigrations(options: MigrateOptions): Promise<string[]> {
    const ran = await runner({
        // Queries stay unbounded: the advisory lock wait and a long migration are both legitimate.
        databaseUrl: {
            connectionString: options.databaseUrl,
            connectionTimeoutMillis: CONNECTION_TIMEOUT_MS,
            keepAlive: true,
            // Read by the grants migration through current_setting().
            ...(options.runtimeRole ? { options: `-c credentials_service.runtime_role=${options.runtimeRole}` } : {}),
        },
        dir: options.dir ?? MIGRATIONS_DIR,
        direction: options.direction,
        count: options.count ?? (options.direction === 'up' ? Infinity : 1),
        migrationsTable: MIGRATIONS_TABLE,
        checkOrder: true,
        // Two Jobs that start together wait for each other instead of one failing.
        advisoryLockMode: 'wait',
        logger: {
            debug: (message: string) => logger.debug('migrate:log', { message }),
            info: (message: string) => logger.info('migrate:log', { message }),
            warn: (message: string) => logger.warn('migrate:log', { message }),
            error: (message: string) => logger.error('migrate:log', { message }),
        },
    })
    return ran.map((migration) => migration.name)
}
