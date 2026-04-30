import type { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js'

import { MAX_SESSIONS_PER_INSTANCE, SESSION_TTL_MS } from './constants'
import { SessionRegistry } from './session-registry'

// Streamable HTTP transports keyed by session id. Lazy TTL eviction lives in
// `SessionRegistry`; this layer adds the global pod cap and a contention sweep.
//
// SSE intentionally has no equivalent — see services/mcp/src/hono/streamable-handler.ts
// for the only transport this Hono runtime serves. Stateful SSE would need
// pod-pinning at the ingress, which we explicitly opted out of.
export class SessionStore {
    readonly streamable = new SessionRegistry<WebStandardStreamableHTTPServerTransport>(SESSION_TTL_MS)

    /** Returns true if a new session can be reserved. Compacts stale entries on contention. */
    reserve(): boolean {
        if (this.streamable.size < MAX_SESSIONS_PER_INSTANCE) {
            return true
        }
        // At capacity — sweep stale entries before rejecting.
        this.streamable.compact()
        return this.streamable.size < MAX_SESSIONS_PER_INSTANCE
    }
}
