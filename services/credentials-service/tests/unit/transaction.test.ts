import { EventEmitter } from 'node:events'
import type { Pool, PoolClient } from 'pg'
import { describe, expect, it, vi } from 'vitest'

import { withTransaction } from '@/db/transaction'

class FakeClient extends EventEmitter {
    queries: string[] = []
    release = vi.fn()
    constructor(private readonly failOn?: string) {
        super()
    }
    async query(text: string): Promise<void> {
        this.queries.push(text)
        if (text === this.failOn) {
            throw new Error(`${text} failed`)
        }
    }
}

const poolOf = (client: FakeClient): Pool => ({ connect: async () => client as unknown as PoolClient }) as Pool

describe('withTransaction', () => {
    it('commits and releases a healthy client', async () => {
        const client = new FakeClient()

        expect(await withTransaction(poolOf(client), async () => 'done')).toBe('done')

        expect(client.queries).toEqual(['BEGIN', 'COMMIT'])
        expect(client.release).toHaveBeenCalledWith()
        expect(client.listenerCount('error')).toBe(0)
    })

    it('rolls back and releases a healthy client when the callback throws', async () => {
        const client = new FakeClient()

        await expect(
            withTransaction(poolOf(client), async () => {
                throw new Error('boom')
            })
        ).rejects.toThrow('boom')

        expect(client.queries).toEqual(['BEGIN', 'ROLLBACK'])
        expect(client.release).toHaveBeenCalledWith()
    })

    it('survives a connection error while the callback waits, and releases the client as broken', async () => {
        const client = new FakeClient()
        const connectionError = new Error('connection terminated')

        await expect(
            withTransaction(poolOf(client), async () => {
                // Without a listener, EventEmitter throws an 'error' event. In Node that is an uncaught exception.
                client.emit('error', connectionError)
                throw new Error('query failed after the drop')
            })
        ).rejects.toThrow('query failed after the drop')

        expect(client.queries).toEqual(['BEGIN'])
        expect(client.release).toHaveBeenCalledWith(connectionError)
        expect(() => client.emit('error', new Error('late socket error'))).not.toThrow()
    })

    it('releases the client as broken when the rollback fails', async () => {
        const client = new FakeClient('ROLLBACK')

        await expect(
            withTransaction(poolOf(client), async () => {
                throw new Error('boom')
            })
        ).rejects.toThrow('boom')

        expect(client.release).toHaveBeenCalledWith(expect.any(Error))
    })
})
