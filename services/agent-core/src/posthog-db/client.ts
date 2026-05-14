import { Pool, PoolConfig } from 'pg'

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
}

export class PosthogDbClient {
    public readonly pool: Pool

    constructor(config: PosthogDbConfig) {
        const poolConfig: PoolConfig = {
            connectionString: config.dbUrl,
            max: config.maxConnections ?? 10,
            idleTimeoutMillis: config.idleTimeoutMs ?? 30_000,
            statement_timeout: config.statementTimeoutMs ?? 5_000,
        }
        this.pool = new Pool(poolConfig)
    }

    async disconnect(): Promise<void> {
        await this.pool.end()
    }
}
