/**
 * Server-side stash for prepared confirmed-action payloads.
 *
 * Signing the full validated args into the confirmation token means the
 * whole payload transits the model's context twice, base64-inflated —
 * unbounded fields (a scout's body + files, say) produce tokens tens of
 * kilobytes long, and long opaque strings invite truncation, which fails
 * as a bad signature. So the payload lives here instead, keyed by the
 * token's nonce, and only its SHA-256 digest is signed: the token stays
 * small and constant-size no matter how large the action args are.
 *
 * `take()` doubles as the single-use guard on this path: GET-then-DEL is
 * not atomic, but only the caller whose DEL returns 1 proceeds, so two
 * concurrent executes can both read the payload while exactly one gets to
 * act on it. No separate nonce-ledger round-trip is needed.
 *
 * Requiring Redis here does not weaken the paradigm's "any server instance
 * can serve execute" property — the single-use nonce ledger already made
 * every execute depend on shared Redis.
 */

import { PAYLOAD_KEY_PREFIX } from './constants'

/**
 * Minimal Redis surface — just what the stash needs. Both `ioredis` (prod)
 * and the in-memory test stubs satisfy this.
 */
export interface PayloadStashRedis {
    set(key: string, value: string, ...args: (string | number)[]): Promise<string | null>
    get(key: string): Promise<string | null>
    del(...keys: string[]): Promise<number>
}

export class PayloadStash {
    constructor(private readonly redis: PayloadStashRedis) {}

    /**
     * Store the serialized payload under the token's nonce. `ttlSeconds`
     * should be the token TTL plus a margin (see
     * `PAYLOAD_STASH_TTL_MARGIN_SECONDS`) so the entry outlives the token.
     */
    async put(nonce: string, payload: string, ttlSeconds: number): Promise<void> {
        const key = `${PAYLOAD_KEY_PREFIX}:${nonce}`
        const safeTtl = Math.max(1, Math.ceil(ttlSeconds))
        const result = await this.redis.set(key, payload, 'EX', safeTtl, 'NX')
        if (result === null) {
            // 128 random bits per nonce: a collision here is a bug (nonce reuse), not chance.
            throw new Error(`Payload stash entry already exists for nonce ${nonce}`)
        }
    }

    /**
     * Fetch and burn the payload for a nonce. Returns `null` when the entry
     * is gone — already consumed, expired, or evicted — or when a concurrent
     * take won the DEL race. A non-null return is the exclusive right to act.
     */
    async take(nonce: string): Promise<string | null> {
        const key = `${PAYLOAD_KEY_PREFIX}:${nonce}`
        const value = await this.redis.get(key)
        if (value === null) {
            return null
        }
        const deleted = await this.redis.del(key)
        if (deleted === 0) {
            return null
        }
        return value
    }
}
