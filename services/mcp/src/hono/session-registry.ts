// In-memory session store with lazy TTL eviction and per-token isolation.
//
// Replaces a hand-rolled Map + per-request O(n) eviction sweep. Lookup is O(1)
// and only the requested entry is checked against the TTL; a `compact()` sweep
// is exposed for capacity checks but isn't required on the hot path.

export type SessionEntry<T> = {
    value: T
    createdAt: number
    tokenHash: string
}

export class SessionRegistry<T> {
    private entries = new Map<string, SessionEntry<T>>()

    constructor(private ttlMs: number) {}

    set(id: string, value: T, tokenHash: string): void {
        this.entries.set(id, { value, createdAt: Date.now(), tokenHash })
    }

    // Lookup with implicit TTL eviction and token-hash isolation. Returns the
    // entry if it exists, isn't stale, and matches the caller's token; otherwise
    // returns undefined (and removes a stale entry as a side effect).
    get(id: string, tokenHash: string): T | undefined {
        const entry = this.entries.get(id)
        if (!entry) {
            return undefined
        }
        if (Date.now() - entry.createdAt > this.ttlMs) {
            this.entries.delete(id)
            return undefined
        }
        if (entry.tokenHash !== tokenHash) {
            return undefined
        }
        return entry.value
    }

    delete(id: string): void {
        this.entries.delete(id)
    }

    get size(): number {
        return this.entries.size
    }

    // Drop every entry whose TTL has elapsed. O(n); call only when checking
    // capacity, not on the request hot path.
    compact(): void {
        const cutoff = Date.now() - this.ttlMs
        for (const [id, entry] of this.entries) {
            if (entry.createdAt < cutoff) {
                this.entries.delete(id)
            }
        }
    }
}
