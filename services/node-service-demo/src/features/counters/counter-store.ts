import type { Pool } from 'pg'

export interface CounterValue {
    name: string
    value: number
}

export class CounterStore {
    constructor(private readonly pool: Pool) {}

    async increment(name: string): Promise<CounterValue> {
        const result = await this.pool.query<{ name: string; value: number }>(
            `
                INSERT INTO node_service_demo_counters (name, value)
                VALUES ($1, 1)
                ON CONFLICT (name)
                DO UPDATE SET value = node_service_demo_counters.value + 1
                RETURNING name, value
            `,
            [name]
        )
        const counter = result.rows[0]
        if (!counter) {
            throw new Error('Counter update returned no row')
        }
        return counter
    }

    async get(name: string): Promise<CounterValue | null> {
        const result = await this.pool.query<{ name: string; value: number }>(
            'SELECT name, value FROM node_service_demo_counters WHERE name = $1',
            [name]
        )
        return result.rows[0] ?? null
    }
}
