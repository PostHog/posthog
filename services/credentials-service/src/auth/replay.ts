// Memory of token ids already used, so a token verifies at most once.
//
// A token lives at most 60s and clocks may differ by 30s either way, so one token verifies for
// under 120s in total. A 2-minute window therefore covers every moment a replay could still
// verify.
//
// `ReplayStore` is the seam. `MemoryReplayStore` is per pod: it serves the tests and the mode
// with no database, and a replay sent to another pod passes it. The Postgres store makes a
// replay fail on every pod. It lands with the database PR, which owns the pool and the
// migrations. Its contract:
//
//   CREATE TABLE auth_jti (
//       deployment text        NOT NULL,
//       jti        text        NOT NULL,
//       expires_at timestamptz NOT NULL,
//       PRIMARY KEY (deployment, jti)
//   );
//
//   -- claim(): zero rows back means the id was already used.
//   INSERT INTO auth_jti (deployment, jti, expires_at) VALUES ($1, $2, $3)
//   ON CONFLICT (deployment, jti) DO NOTHING
//   RETURNING 1;
//
//   -- A sweep deletes rows the replay window no longer needs.
//   DELETE FROM auth_jti WHERE expires_at < now();
//
// A store error must reject the token. Accepting it would turn a database outage into a
// replay window.

import { integrationReplayEvictionsTotal } from '../metrics'

export const REPLAY_WINDOW_MS = 120_000
export const REPLAY_MAX_ENTRIES = 100_000

interface Entry {
    id: string
    expiresAt: number
}

// Compact the queue once this many consumed slots sit at its front.
const COMPACT_AFTER = 1024

/** Records each (deployment, jti) once. */
export interface ReplayStore {
    /**
     * Record a token id. Resolves false when the id was already used and is still inside its
     * window. `expiresAtMs` is the last moment the token can verify (its `exp` plus the
     * clock skew). Rejects when the store cannot answer, and the caller then refuses the token.
     */
    claim(deployment: string, jti: string, expiresAtMs: number, nowMs: number): Promise<boolean>
}

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

/**
 * The per-pod store. It keeps every id for the fixed window, which always outlasts
 * `expiresAtMs`, so it ignores that argument.
 */
export class MemoryReplayStore implements ReplayStore {
    constructor(private readonly cache: ReplayCache = new ReplayCache()) {}

    claim(deployment: string, jti: string, _expiresAtMs: number, nowMs: number): Promise<boolean> {
        // Keyed by deployment, so one deployment cannot burn another deployment's token ids.
        return Promise.resolve(this.cache.claim(`${deployment}\u0000${jti}`, nowMs))
    }
}
