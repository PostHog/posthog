import type { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js'

import { MAX_SESSIONS_PER_INSTANCE, SESSION_TTL_MS } from './constants'
import { sessionsActive } from './metrics'

type Entry = {
    transport: WebStandardStreamableHTTPServerTransport
    lastUsedAt: number
    tokenHash: string
}

const GC_INTERVAL_MS = 5 * 60 * 1000

export class SessionStore {
    private entries = new Map<string, Entry>()
    private gcTimer: ReturnType<typeof setInterval> | undefined

    startGc(): void {
        if (!this.gcTimer) {
            this.gcTimer = setInterval(() => this.compact(), GC_INTERVAL_MS)
            this.gcTimer.unref()
        }
    }

    stopGc(): void {
        if (this.gcTimer) {
            clearInterval(this.gcTimer)
            this.gcTimer = undefined
        }
    }

    isFull(): boolean {
        if (this.entries.size < MAX_SESSIONS_PER_INSTANCE) {
            return false
        }
        this.compact()
        return this.entries.size >= MAX_SESSIONS_PER_INSTANCE
    }

    set(id: string, transport: WebStandardStreamableHTTPServerTransport, tokenHash: string): void {
        this.entries.set(id, { transport, lastUsedAt: Date.now(), tokenHash })
        sessionsActive.set(this.entries.size)
    }

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

    closeAll(): void {
        for (const [id, entry] of this.entries) {
            this.evict(id, entry)
        }
    }

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
