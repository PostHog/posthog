import type { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js'

import { MAX_SESSIONS_PER_INSTANCE, SESSION_TTL_MS } from './constants'
import { sessionReservationsTotal, sessionsActive } from './metrics'

type Entry = {
    transport: WebStandardStreamableHTTPServerTransport
    lastUsedAt: number
    tokenHash: string
}

export type Reservation = {
    /** Call when the reservation is no longer needed (boot error, abandoned init). */
    release: () => void
}

/**
 * In-memory transport registry for the Streamable HTTP `/mcp` endpoint.
 *
 * Sessions are keyed by the SDK-issued `mcp-session-id`, isolated per token
 * (so id-guessing across tenants is a non-event), and evicted on idle TTL.
 * Concurrent `reserve()` calls share a pending counter so the per-pod cap
 * holds even when many opens race.
 *
 * SSE has no equivalent — pinning a long-lived TCP stream to a pod was
 * deliberately rejected at the ingress.
 */
export class SessionStore {
    private entries = new Map<string, Entry>()
    private pending = 0

    /** Reserve a slot for a new session; returns null when the cap is reached. */
    reserve(): Reservation | null {
        if (this.entries.size + this.pending >= MAX_SESSIONS_PER_INSTANCE) {
            this.compact()
            if (this.entries.size + this.pending >= MAX_SESSIONS_PER_INSTANCE) {
                sessionReservationsTotal.inc({ result: 'rejected' })
                return null
            }
        }
        this.pending += 1
        sessionReservationsTotal.inc({ result: 'accepted' })
        let released = false
        return {
            release: () => {
                if (released) {
                    return
                }
                released = true
                this.pending -= 1
            },
        }
    }

    set(id: string, transport: WebStandardStreamableHTTPServerTransport, tokenHash: string): void {
        this.entries.set(id, { transport, lastUsedAt: Date.now(), tokenHash })
        sessionsActive.set(this.entries.size)
    }

    /** Lookup with idle-TTL eviction and per-token isolation. Active use refreshes lastUsedAt. */
    get(id: string, tokenHash: string): WebStandardStreamableHTTPServerTransport | undefined {
        const entry = this.entries.get(id)
        if (!entry) {
            return undefined
        }
        if (Date.now() - entry.lastUsedAt > SESSION_TTL_MS) {
            this.evict(id, entry)
            return undefined
        }
        if (entry.tokenHash !== tokenHash) {
            return undefined
        }
        entry.lastUsedAt = Date.now()
        return entry.transport
    }

    delete(id: string): void {
        const entry = this.entries.get(id)
        if (entry) {
            this.evict(id, entry)
        }
    }

    /** Force-close every live transport. Used during graceful shutdown. */
    closeAll(): void {
        for (const [id, entry] of this.entries) {
            this.evict(id, entry)
        }
    }

    get size(): number {
        return this.entries.size
    }

    /** Drop every entry whose TTL has elapsed. O(n); only called on `reserve()` contention. */
    private compact(): void {
        const cutoff = Date.now() - SESSION_TTL_MS
        for (const [id, entry] of this.entries) {
            if (entry.lastUsedAt < cutoff) {
                this.evict(id, entry)
            }
        }
    }

    private evict(id: string, entry: Entry): void {
        this.entries.delete(id)
        sessionsActive.set(this.entries.size)
        try {
            entry.transport.close()
        } catch (err) {
            console.error('[SessionStore] failed to close transport on evict:', err)
        }
    }
}
