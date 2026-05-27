import { Pool } from 'pg'

import { createAgentPgPool } from '../postgres'

/**
 * Pool wrapper for the main posthog Postgres database (NOT the agent-runtime queue DB).
 *
 * Runtime services read app/revision rows here directly — no HTTP hop through Django.
 * Models are owned by Django; we write read-only SQL against the stable table names
 * (`agent_stack_*`). Schema drift is caught by tests and by integration with the same
 * `products/agent_stack/` package.
 */
export interface PosthogDbConfig {
    dbUrl: string
    maxConnections?: number
    idleTimeoutMs?: number
    statementTimeoutMs?: number
    /** See `createAgentPgPool`. Tests turn this on so jest workers exit cleanly. */
    allowExitOnIdle?: boolean
}

export class PosthogDbClient {
    public readonly pool: Pool

    constructor(config: PosthogDbConfig) {
        // `createAgentPgPool` installs the shared timestamp type parsers so
        // `agent_stack_*` TIMESTAMPTZ columns come back as UTC ISO strings.
        this.pool = createAgentPgPool(
            {
                dbUrl: config.dbUrl,
                maxConnections: config.maxConnections,
                idleTimeoutMs: config.idleTimeoutMs,
                statementTimeoutMs: config.statementTimeoutMs ?? 5_000,
                allowExitOnIdle: config.allowExitOnIdle,
            },
            10
        )
    }

    async disconnect(): Promise<void> {
        await this.pool.end()
    }
}
