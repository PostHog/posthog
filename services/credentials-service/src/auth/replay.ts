// Per-pod memory of token ids already used. A token lives at most 60s and clocks may differ by
// 30s either way, so one token verifies for under 120s in total. A 2-minute window therefore
// covers every moment a replay could still verify.

import { integrationReplayEvictionsTotal } from '../metrics'

export const REPLAY_WINDOW_MS = 120_000
export const REPLAY_MAX_ENTRIES = 100_000

export class ReplayCache {
    // Map keeps insertion order, and every entry gets the same window, so the oldest entry
    // is always first and expired entries leave from the front.
    private readonly seen = new Map<string, number>()

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
            const oldest = this.seen.keys().next().value
            if (oldest !== undefined) {
                this.seen.delete(oldest)
                integrationReplayEvictionsTotal.inc()
            }
        }
        this.seen.set(id, nowMs + this.windowMs)
        return true
    }

    get size(): number {
        return this.seen.size
    }

    private dropExpired(nowMs: number): void {
        for (const [id, expiresAt] of this.seen) {
            if (expiresAt > nowMs) {
                return
            }
            this.seen.delete(id)
        }
    }
}
