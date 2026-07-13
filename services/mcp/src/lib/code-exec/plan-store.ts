/**
 * Server-side storage for planned scripts, keyed by `${sub}:${phrase}` (user
 * identity + three-word plan id), so the agent cannot submit different code at
 * apply time and a phrase is only resolvable by the identity that minted it.
 * `consume` is the single-use gate: it atomically takes the plan and leaves a
 * consumed tombstone for the remaining TTL, which is what preserves the
 * distinct "already been applied" message on reuse. `MemoryPlanStore` (Map +
 * expiry) backs tests and local dev; `RedisPlanStore` mirrors the
 * `NonceLedgerRedis` pattern over a minimal ioredis-compatible surface.
 */

import type { Plan } from './types'

interface StoredPlanBase {
    plan: Plan
    /** User identity the plan was minted for. */
    sub: string
    /**
     * Active project the plan was minted against; `apply` refuses to execute
     * under a different active project (the user confirmed changes to THIS
     * project). Optional only for plans stored before the field existed.
     */
    projectId?: string
}

/** A sandbox-path plan: `apply` re-runs the stored script with the plan enforced. */
export interface StoredScriptPlan extends StoredPlanBase {
    kind: 'script'
    script: string
}

/**
 * A degenerate fast-path plan (spec §4.2): one call-shaped mutation. `apply`
 * replays the call directly through the tool handler — no sandbox, no script.
 */
export interface StoredCallPlan extends StoredPlanBase {
    kind: 'call'
    call: { toolName: string; input: Record<string, unknown> }
}

export type StoredPlan = StoredScriptPlan | StoredCallPlan

export interface PlanStore {
    put(key: string, value: StoredPlan, ttlSeconds: number): Promise<void>
    get(key: string): Promise<StoredPlan | null>
    /**
     * Atomically take the plan, leaving a tombstone that keeps the remaining
     * TTL. `'consumed'` distinguishes reuse from never-existed/expired (`null`).
     */
    consume(key: string): Promise<StoredPlan | 'consumed' | null>
}

export interface MemoryPlanStoreOptions {
    /** Injectable clock (ms) for deterministic expiry in tests. */
    now?: () => number
}

export class MemoryPlanStore implements PlanStore {
    private readonly entries = new Map<string, { value: StoredPlan | null; expiresAt: number }>()
    private readonly now: () => number

    constructor(options: MemoryPlanStoreOptions = {}) {
        this.now = options.now ?? (() => Date.now())
    }

    async put(key: string, value: StoredPlan, ttlSeconds: number): Promise<void> {
        this.entries.set(key, { value, expiresAt: this.now() + Math.max(1, ttlSeconds) * 1000 })
    }

    async get(key: string): Promise<StoredPlan | null> {
        const entry = this.entries.get(key)
        if (!entry || this.now() >= entry.expiresAt) {
            this.entries.delete(key)
            return null
        }
        return entry.value
    }

    async consume(key: string): Promise<StoredPlan | 'consumed' | null> {
        const entry = this.entries.get(key)
        if (!entry || this.now() >= entry.expiresAt) {
            this.entries.delete(key)
            return null
        }
        if (entry.value === null) {
            return 'consumed'
        }
        const { value } = entry
        // Tombstone keeps the original expiry so reuse gets a distinct message until the TTL runs out.
        this.entries.set(key, { value: null, expiresAt: entry.expiresAt })
        return value
    }
}

/** Minimal Redis surface the plan store needs — satisfied by `ioredis` and test stubs. */
export interface PlanStoreRedis {
    set(key: string, value: string, mode: 'EX', ttlSeconds: number): Promise<unknown>
    get(key: string): Promise<string | null>
    ttl(key: string): Promise<number>
    /** GETDEL (Redis ≥ 6.2) makes consume atomic; absent, consume degrades to get+set. */
    getdel?(key: string): Promise<string | null>
}

export interface RedisPlanStoreOptions {
    keyPrefix?: string
}

const DEFAULT_KEY_PREFIX = 'mcp:code-exec:plan'

const CONSUMED_MARKER = JSON.stringify({ consumed: true })

function isConsumedMarker(parsed: unknown): boolean {
    return typeof parsed === 'object' && parsed !== null && (parsed as { consumed?: unknown }).consumed === true
}

export class RedisPlanStore implements PlanStore {
    private readonly keyPrefix: string

    constructor(
        private readonly redis: PlanStoreRedis,
        options: RedisPlanStoreOptions = {}
    ) {
        this.keyPrefix = options.keyPrefix ?? DEFAULT_KEY_PREFIX
    }

    async put(key: string, value: StoredPlan, ttlSeconds: number): Promise<void> {
        await this.redis.set(this.redisKey(key), JSON.stringify(value), 'EX', Math.max(1, Math.ceil(ttlSeconds)))
    }

    async get(key: string): Promise<StoredPlan | null> {
        const raw = await this.redis.get(this.redisKey(key))
        if (raw === null) {
            return null
        }
        const parsed: unknown = JSON.parse(raw)
        // A tombstone reads as absent, so put's collision check treats consumed keys as free.
        if (isConsumedMarker(parsed)) {
            return null
        }
        return parsed as StoredPlan
    }

    async consume(key: string): Promise<StoredPlan | 'consumed' | null> {
        const redisKey = this.redisKey(key)
        // Read remaining TTL first so the tombstone inherits it; a negative answer means missing/no-expiry.
        const remaining = await this.redis.ttl(redisKey)
        // GETDEL (Redis ≥ 6.2) makes get-and-consume atomic; the non-atomic fallback's race window is
        // a single user double-applying their own plan — acceptable per spec §3.6.4.
        const raw = this.redis.getdel ? await this.redis.getdel(redisKey) : await this.redis.get(redisKey)
        if (raw === null) {
            return null
        }
        const parsed: unknown = JSON.parse(raw)
        // Re-SET the tombstone either way: GETDEL removed it, and the fallback path overwrites the plan.
        await this.redis.set(redisKey, CONSUMED_MARKER, 'EX', Math.max(1, remaining))
        if (isConsumedMarker(parsed)) {
            return 'consumed'
        }
        return parsed as StoredPlan
    }

    private redisKey(key: string): string {
        return `${this.keyPrefix}:${key}`
    }
}
