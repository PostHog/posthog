/**
 * Single-use nonce ledger for signed-state tokens.
 *
 * Each successful `consume()` writes the nonce to Redis with `SET NX EX` and
 * the token's remaining TTL. A second consume of the same nonce within that
 * window finds the key already set and rejects.
 *
 * Why a ledger and not just TTL: TTL alone bounds the window but a model
 * could call the destructive execute twice in quick succession (or be
 * prompted to retry on a transient error). Single-use closes that footgun
 * cheaply (one `SET NX` per execute, key auto-expires).
 */

import { NONCE_KEY_PREFIX } from './constants'
import { SignedStateAlreadyConsumed } from './errors'

/**
 * Minimal Redis surface — just what the ledger needs. Both `ioredis` (prod)
 * and the in-memory test stubs satisfy this.
 */
export interface NonceLedgerRedis {
    set(key: string, value: string, ...args: (string | number)[]): Promise<string | null>
}

export class NonceLedger {
    constructor(private readonly redis: NonceLedgerRedis) {}

    /**
     * Mark the nonce consumed. Throws `SignedStateAlreadyConsumed` if it was
     * already consumed within the (remaining) TTL window.
     *
     * `ttlSeconds` is the remaining lifetime of the token: setting the
     * ledger entry to that means abandoned nonces self-clean exactly when
     * the token they protect can no longer be replayed.
     */
    async consume(nonce: string, ttlSeconds: number): Promise<void> {
        const key = `${NONCE_KEY_PREFIX}:${nonce}`
        const safeTtl = Math.max(1, Math.ceil(ttlSeconds))
        const result = await this.redis.set(key, '1', 'EX', safeTtl, 'NX')
        if (result === null) {
            throw new SignedStateAlreadyConsumed(`Nonce ${nonce} has already been consumed within its TTL window`)
        }
    }
}
