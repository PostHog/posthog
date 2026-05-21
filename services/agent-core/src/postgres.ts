import { DateTime } from 'luxon'
import { Pool, types as pgTypes } from 'pg'

/**
 * Postgres helpers shared across the agent runtime — the queue DB (`SessionQuery`,
 * `SessionQueueWorker`, `SessionQueueManager`, `SessionQueueJanitor`) and the
 * main posthog DB (`PosthogDbClient`).
 *
 * `createAgentPgPool` is the single chokepoint for building a `Pool`: it installs
 * the timestamp type parsers first, so no caller can forget.
 */

/**
 * node-postgres parses `TIME` / `TIMESTAMP` / `TIMESTAMPTZ` columns into JS
 * `Date` objects (in the local timezone) by default. The agent runtime wants
 * UTC ISO strings instead — e.g. `SessionQuery.rowToView` feeds these values
 * straight into `DateTime.fromISO`, which only accepts strings; handed a `Date`
 * it yields an *invalid* DateTime whose `.toISO()` is silently `null`.
 *
 * The plugin-server installs equivalent parsers (nodejs/src/utils/db/postgres.ts)
 * but that's process-local to the plugin-server — the agent runtime services
 * run in their own processes and must install their own. `setTypeParser`
 * mutates the global `pg-types` registry and must run before any Pool issues a
 * query; routing every Pool through `createAgentPgPool` guarantees that.
 */
let typeParsersInstalled = false

function installAgentPgTypeParsers(): void {
    if (typeParsersInstalled) {
        return
    }
    typeParsersInstalled = true

    const toUtcIso = (value: string | null): string | null =>
        value ? DateTime.fromSQL(value, { zone: 'utc' }).toISO() : null

    pgTypes.setTypeParser(1083 /* TIME */, toUtcIso)
    pgTypes.setTypeParser(1114 /* TIMESTAMP */, toUtcIso)
    pgTypes.setTypeParser(1184 /* TIMESTAMPTZ */, toUtcIso)
}

export interface AgentPgPoolConfig {
    dbUrl: string
    maxConnections?: number
    idleTimeoutMs?: number
    /** Per-statement timeout. Omitted from the Pool when undefined. */
    statementTimeoutMs?: number
}

/**
 * The one way the agent runtime should create a Postgres `Pool`. Installs the
 * timestamp type parsers, then builds the Pool with the shared option defaults.
 * `defaultMax` lets each caller pick its own connection ceiling (read-mostly
 * surfaces want fewer); an explicit `config.maxConnections` always wins.
 */
export function createAgentPgPool(config: AgentPgPoolConfig, defaultMax = 10): Pool {
    installAgentPgTypeParsers()
    return new Pool({
        connectionString: config.dbUrl,
        max: config.maxConnections ?? defaultMax,
        idleTimeoutMillis: config.idleTimeoutMs ?? 30_000,
        ...(config.statementTimeoutMs !== undefined ? { statement_timeout: config.statementTimeoutMs } : {}),
    })
}
