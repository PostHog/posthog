import type { Pool, PoolClient } from 'pg'

import { logger } from '../lib/logging'

/**
 * Runs `fn` in one transaction. Commits when `fn` returns, and rolls back when it throws.
 *
 * A checked-out client has no pool error listener, so a dropped connection while `fn` waits on
 * something else (a KMS call) would reach Node as an uncaught exception. The listener below
 * records the error, and the client is then released as broken so the pool drops it.
 */
export async function withTransaction<T>(pool: Pool, fn: (client: PoolClient) => Promise<T>): Promise<T> {
    const client = await pool.connect()
    let clientError: Error | undefined
    const onError = (err: Error): void => {
        clientError ??= err
        logger.warn('db:checked_out_client_error', { error: err.message })
    }
    client.on('error', onError)
    let result: T
    try {
        await client.query('BEGIN')
        result = await fn(client)
        await client.query('COMMIT')
    } catch (err) {
        try {
            if (clientError) {
                throw clientError
            }
            await client.query('ROLLBACK')
            client.off('error', onError)
            client.release()
        } catch (rollbackErr) {
            // The connection is broken. Release it as broken, so the pool drops it. The listener
            // stays, because a late socket error can still arrive on the closing client.
            client.release(rollbackErr instanceof Error ? rollbackErr : true)
        }
        throw err
    }
    if (clientError) {
        client.release(clientError)
    } else {
        client.off('error', onError)
        client.release()
    }
    return result
}
