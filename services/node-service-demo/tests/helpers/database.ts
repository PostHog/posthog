import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'

import { runPostgresMigrations } from '@posthog/node-migrations'

import { CounterStore } from '../../src/features/counters/counter-store.js'

const TEST_DATABASE_URL = 'postgres://posthog:posthog@localhost:5432/test_posthog'

export interface TestStore {
    pool: Pool
    store: CounterStore
    counterName: string
    close(): Promise<void>
}

export function getTestDatabaseUrl(): string {
    const databaseUrl = process.env.DATABASE_URL ?? TEST_DATABASE_URL
    const databaseName = new URL(databaseUrl).pathname.slice(1)
    if (!databaseName.includes('test')) {
        throw new Error(`Refusing to run the demo service tests against database ${databaseName}`)
    }
    return databaseUrl
}

export async function createTestStore(): Promise<TestStore> {
    const databaseUrl = getTestDatabaseUrl()
    await runPostgresMigrations({ databaseUrl, serviceName: 'node-service-demo' })

    const pool = new Pool({ connectionString: databaseUrl })
    const counterName = `test-${randomUUID()}`

    return {
        pool,
        store: new CounterStore(pool),
        counterName,
        close: async () => {
            await pool.query('DELETE FROM node_service_demo_counters WHERE name = $1', [counterName])
            await pool.end()
        },
    }
}
