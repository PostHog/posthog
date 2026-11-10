import type { Pool, PoolClient } from 'pg'

/** Runs `fn` in one transaction. Commits when `fn` returns, and rolls back when it throws. */
export async function withTransaction<T>(pool: Pool, fn: (client: PoolClient) => Promise<T>): Promise<T> {
    const client = await pool.connect()
    let result: T
    try {
        await client.query('BEGIN')
        result = await fn(client)
        await client.query('COMMIT')
    } catch (err) {
        try {
            await client.query('ROLLBACK')
            client.release()
        } catch (rollbackErr) {
            // The connection is broken. Release it as broken, so the pool drops it.
            client.release(rollbackErr instanceof Error ? rollbackErr : true)
        }
        throw err
    }
    client.release()
    return result
}
