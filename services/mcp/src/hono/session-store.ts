import type { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js'
import type { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js'

import { MAX_SESSIONS_PER_INSTANCE, SESSION_TTL_MS } from './constants'
import type { HonoMcpServer } from './mcp-server'
import { SessionRegistry } from './session-registry'

export type SseEntry = { transport: SSEServerTransport; server: HonoMcpServer }

// Bundles the two transport-specific session registries with a shared capacity
// guard. Lazy TTL eviction lives in `SessionRegistry`; this layer adds the
// global pod cap and the contention sweep.
export class SessionStore {
    readonly streamable = new SessionRegistry<WebStandardStreamableHTTPServerTransport>(SESSION_TTL_MS)
    readonly sse = new SessionRegistry<SseEntry>(SESSION_TTL_MS)

    /** Returns true if a new session can be reserved. Compacts stale entries on contention. */
    reserve(): boolean {
        if (this.total() < MAX_SESSIONS_PER_INSTANCE) {
            return true
        }
        // At capacity — sweep stale entries before rejecting.
        this.streamable.compact()
        this.sse.compact()
        return this.total() < MAX_SESSIONS_PER_INSTANCE
    }

    private total(): number {
        return this.streamable.size + this.sse.size
    }
}
