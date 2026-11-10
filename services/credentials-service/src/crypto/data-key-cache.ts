// Unwrapped data keys, kept in process memory only, so a hot row needs no KMS call. Keyed by
// the wrapped key bytes: each record has its own data key, so this is one entry per record.
//
// A key read from the cache must be used before the next `await`. An eviction can zero it at
// any later point.

export interface DataKeyCacheOptions {
    maxEntries: number
    ttlMs: number
    /** Milliseconds. Tests replace it. */
    now?: () => number
}

interface Entry {
    key: Buffer
    expiresAt: number
}

export const DEFAULT_DATA_KEY_CACHE_OPTIONS = { maxEntries: 50_000, ttlMs: 10 * 60_000 } as const

// A key that nobody reads again stays until something evicts it. A sweep on write bounds how
// long an expired key stays in memory when the cache never fills.
const SWEEP_INTERVAL_MS = 60_000

export class DataKeyCache {
    // A Map iterates in insertion order. Moving an entry to the end on each read makes the
    // first entry the least recently used one.
    private readonly entries = new Map<string, Entry>()
    private readonly maxEntries: number
    private readonly ttlMs: number
    private readonly now: () => number
    private nextSweepAt: number

    constructor(options: DataKeyCacheOptions = DEFAULT_DATA_KEY_CACHE_OPTIONS) {
        if (options.maxEntries < 1 || options.ttlMs <= 0) {
            throw new Error('DataKeyCache needs maxEntries >= 1 and ttlMs > 0')
        }
        this.maxEntries = options.maxEntries
        this.ttlMs = options.ttlMs
        this.now = options.now ?? Date.now
        this.nextSweepAt = this.now() + SWEEP_INTERVAL_MS
    }

    get size(): number {
        return this.entries.size
    }

    get(wrappedKey: Buffer): Buffer | undefined {
        const id = wrappedKey.toString('base64')
        const entry = this.entries.get(id)
        if (!entry) {
            return undefined
        }
        this.entries.delete(id)
        if (entry.expiresAt <= this.now()) {
            entry.key.fill(0)
            return undefined
        }
        this.entries.set(id, entry)
        return entry.key
    }

    /** Takes ownership of `plaintextKey`: the cache zeroes it on eviction. */
    set(wrappedKey: Buffer, plaintextKey: Buffer): void {
        const now = this.now()
        if (now >= this.nextSweepAt) {
            this.evictExpired(now)
            this.nextSweepAt = now + SWEEP_INTERVAL_MS
        }
        const id = wrappedKey.toString('base64')
        const previous = this.entries.get(id)
        if (previous) {
            this.entries.delete(id)
            if (previous.key !== plaintextKey) {
                previous.key.fill(0)
            }
        }
        this.entries.set(id, { key: plaintextKey, expiresAt: now + this.ttlMs })
        while (this.entries.size > this.maxEntries) {
            const [oldestId, oldest] = this.entries.entries().next().value as [string, Entry]
            this.entries.delete(oldestId)
            oldest.key.fill(0)
        }
    }

    evictExpired(now = this.now()): void {
        for (const [id, entry] of this.entries) {
            if (entry.expiresAt <= now) {
                this.entries.delete(id)
                entry.key.fill(0)
            }
        }
    }

    clear(): void {
        for (const entry of this.entries.values()) {
            entry.key.fill(0)
        }
        this.entries.clear()
    }
}
