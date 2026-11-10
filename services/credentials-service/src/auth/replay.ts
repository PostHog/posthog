// Per-pod memory of token ids already used. A token lives at most 60s and clocks may differ by
// 30s either way, so one token verifies for under 120s in total. A 2-minute window therefore
// covers every moment a replay could still verify.

import { integrationReplayEvictionsTotal } from '../metrics'

export const REPLAY_WINDOW_MS = 120_000
export const REPLAY_MAX_ENTRIES = 100_000

interface Entry {
    id: string
    expiresAt: number
}

// Compact the queue once this many consumed slots sit at its front.
const COMPACT_AFTER = 1024

export class ReplayCache {
    private readonly seen = new Map<string, number>()
    // Ids in claim order. Every entry gets the same window, so the oldest is at `head` and
    // expired entries leave from the front. A persistent cursor keeps each lookup O(1)
    // amortized, instead of restarting Map iteration over deleted slots on every claim.
    private queue: Entry[] = []
    private head = 0

    constructor(
        private readonly windowMs: number = REPLAY_WINDOW_MS,
        private readonly maxEntries: number = REPLAY_MAX_ENTRIES
    ) {}

    /** Record a token id. Returns false when the id was already used inside the window. */
    claim(id: string, nowMs: number): boolean {
        this.dropExpired(nowMs)
        const expiresAt = this.seen.get(id)
        if (expiresAt !== undefined && expiresAt > nowMs) {
            return false
        }
        this.seen.delete(id)
        if (this.seen.size >= this.maxEntries) {
            // Dropping a live entry lets that one token be used again. The other choice,
            // refusing new tokens, would turn a traffic spike into an outage.
            this.evictOldest()
        }
        const entry = { id, expiresAt: nowMs + this.windowMs }
        this.seen.set(id, entry.expiresAt)
        this.queue.push(entry)
        return true
    }

    get size(): number {
        return this.seen.size
    }

    /** A queue entry is stale when its id was dropped or claimed again since. */
    private isCurrent(entry: Entry): boolean {
        return this.seen.get(entry.id) === entry.expiresAt
    }

    private dropExpired(nowMs: number): void {
        while (this.head < this.queue.length) {
            const entry = this.queue[this.head]!
            if (entry.expiresAt > nowMs) {
                break
            }
            if (this.isCurrent(entry)) {
                this.seen.delete(entry.id)
            }
            this.head += 1
        }
        this.compact()
    }

    private evictOldest(): void {
        while (this.head < this.queue.length) {
            const entry = this.queue[this.head]!
            this.head += 1
            if (this.isCurrent(entry)) {
                this.seen.delete(entry.id)
                integrationReplayEvictionsTotal.inc()
                break
            }
        }
        this.compact()
    }

    private compact(): void {
        if (this.head >= COMPACT_AFTER && this.head * 2 >= this.queue.length) {
            this.queue = this.queue.slice(this.head)
            this.head = 0
        }
    }
}
