/**
 * Server-side storage for planned scripts, keyed by `scriptHash`, so the agent
 * cannot submit different code at apply time. `MemoryPlanStore` (Map + expiry)
 * backs tests and local dev; `RedisPlanStore` mirrors the `NonceLedgerRedis`
 * pattern over a minimal `{ set(key, value, 'EX', ttl), get(key) }` surface.
 */

import type { Plan } from './types'

export interface StoredPlan {
    script: string
    plan: Plan
    /** User identity the plan was minted for. */
    sub: string
}

export interface PlanStore {
    put(key: string, value: StoredPlan, ttlSeconds: number): Promise<void>
    get(key: string): Promise<StoredPlan | null>
}

export interface MemoryPlanStoreOptions {
    /** Injectable clock (ms) for deterministic expiry in tests. */
    now?: () => number
}

export class MemoryPlanStore implements PlanStore {
    private readonly entries = new Map<string, { value: StoredPlan; expiresAt: number }>()
    private readonly now: () => number

    constructor(options: MemoryPlanStoreOptions = {}) {
        this.now = options.now ?? (() => Date.now())
    }

    async put(key: string, value: StoredPlan, ttlSeconds: number): Promise<void> {
        this.entries.set(key, { value, expiresAt: this.now() + Math.max(1, ttlSeconds) * 1000 })
    }

    async get(key: string): Promise<StoredPlan | null> {
        const entry = this.entries.get(key)
        if (!entry) {
            return null
        }
        if (this.now() >= entry.expiresAt) {
            this.entries.delete(key)
            return null
        }
        return entry.value
    }
}

/** Minimal Redis surface the plan store needs — satisfied by `ioredis` and test stubs. */
export interface PlanStoreRedis {
    set(key: string, value: string, mode: 'EX', ttlSeconds: number): Promise<unknown>
    get(key: string): Promise<string | null>
}

export interface RedisPlanStoreOptions {
    keyPrefix?: string
}

const DEFAULT_KEY_PREFIX = 'mcp:code-exec:plan'

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
        return JSON.parse(raw) as StoredPlan
    }

    private redisKey(key: string): string {
        return `${this.keyPrefix}:${key}`
    }
}
