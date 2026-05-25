/**
 * Concrete `BusAwaitMetrics` implementation backed by the same `prom-client`
 * registry the rest of the Hono server publishes to.
 *
 * Stays in this file (not in `metrics.ts`) so the bus stays a self-contained
 * module — anyone importing from `@/hono/session-bus` only pulls in the
 * abstraction, not the Prometheus dependency. Hono bootstrap wires this
 * adapter explicitly.
 */

import { sessionBusAwaitDurationSeconds, sessionBusAwaitsTotal, sessionBusPollsTotal } from '../metrics'
import type { BusAwaitMetrics } from './types'

export function createPromBusMetrics(): BusAwaitMetrics {
    return {
        onPoll() {
            sessionBusPollsTotal.inc()
        },
        onResolve(_requestId, latencyMs) {
            sessionBusAwaitsTotal.inc({ outcome: 'resolved' })
            sessionBusAwaitDurationSeconds.observe({ outcome: 'resolved' }, latencyMs / 1000)
        },
        onTimeout() {
            sessionBusAwaitsTotal.inc({ outcome: 'timeout' })
        },
        onAbort() {
            sessionBusAwaitsTotal.inc({ outcome: 'aborted' })
        },
        onUnhealthy() {
            sessionBusAwaitsTotal.inc({ outcome: 'unhealthy' })
        },
    }
}
