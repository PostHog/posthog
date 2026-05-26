/**
 * Public API for the Hono session-response bus.
 *
 * Import from `@/hono/session-bus` rather than reaching into individual
 * files — these exports are the supported surface; everything else is an
 * implementation detail and can change.
 */

export {
    ElicitationNotSupportedError,
    SessionBusAbortedError,
    SessionBusTimeoutError,
    SessionBusUnhealthyError,
} from './errors'

export type { AwaitOptions, BusAwaitMetrics, SessionResponseBus } from './types'

export { InMemorySessionResponseBus } from './in-memory-bus'

export { RedisPollingSessionResponseBus, type RedisPollingSessionResponseBusOptions } from './redis-polling-bus'

export {
    DEFAULT_ADAPTIVE_POLL_CONFIG,
    createAdaptivePollSchedule,
    type AdaptivePollConfig,
    type AdaptivePollSchedule,
} from './adaptive-poll'

export {
    ElicitationGateway,
    type ElicitationGatewayOptions,
    type ElicitCallOptions,
    type JsonRpcRequestMessage,
    type TransportMessageSender,
} from './elicitation-gateway'

export { validateElicitResult } from './elicit-result-validator'

export { createPromBusMetrics } from './prom-metrics'
