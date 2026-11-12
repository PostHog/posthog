// Entry point for the schema migrations: `node credentials-service-migrate.mjs [up | down [count]]`.
// It runs as its own process (a Kubernetes Job before a deploy), never inside the server, so
// pods never race each other to change the schema.

import { runMigrations } from './db/migrate'
import { loadMigrateConfig } from './lib/config'
import { logger } from './lib/logging'

function parseArgs(args: string[]): { direction: 'up' | 'down'; count?: number } {
    const [direction = 'up', count, ...rest] = args
    if ((direction !== 'up' && direction !== 'down') || rest.length > 0) {
        throw new Error('usage: credentials-service-migrate [up | down [count]]')
    }
    if (count === undefined) {
        return { direction }
    }
    if (!/^[1-9]\d*$/.test(count)) {
        throw new Error(`count must be a positive integer, got ${JSON.stringify(count)}`)
    }
    return { direction, count: Number.parseInt(count, 10) }
}

async function main(): Promise<void> {
    const database = loadMigrateConfig()
    if (!database) {
        throw new Error('CREDENTIALS_SERVICE_MIGRATE_DATABASE_URL is not set')
    }
    const args = parseArgs(process.argv.slice(2))
    const ran = await runMigrations({ databaseUrl: database.url, runtimeRole: database.runtimeRole, ...args })
    logger.info('migrate:complete', { direction: args.direction, migrations: ran })
}

main().catch((err: unknown) => {
    logger.error('migrate:failed', { error: err instanceof Error ? err.message : String(err) })
    process.exit(1)
})
