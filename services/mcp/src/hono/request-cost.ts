import { Method } from './dispatcher'
import type { RequestCharge } from './rate-limiter'

// `server/discover` is the stateless dialect's `initialize`, so it belongs on
// the same side of the line. `notifications/initialized` is a client
// notification with no dispatch entry of its own.
const HANDSHAKE_METHODS: ReadonlySet<string> = new Set<string>([
    Method.Initialize,
    Method.Discover,
    Method.Ping,
    Method.ToolsList,
    'notifications/initialized',
])

/**
 * A request takes the handshake charge only when every message in it is
 * overhead. A batch that carries one tool call pays the work charge, and so
 * does a body we could not parse — nothing unreadable buys the cheaper bucket.
 */
export function classifyRequestCharge(methods: readonly string[]): RequestCharge {
    if (methods.length === 0) {
        return 'work'
    }
    return methods.every((method) => HANDSHAKE_METHODS.has(method)) ? 'handshake' : 'work'
}
