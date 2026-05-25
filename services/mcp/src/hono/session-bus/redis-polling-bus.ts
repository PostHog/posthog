/**
 * Production `SessionResponseBus` for the Hono deployment.
 *
 * Uses two of the simplest Redis primitives — `SET … EX` and `GET`/`DEL` —
 * to bridge a parked promise on one pod with a delivered response on (possibly)
 * another. No pub/sub, no second client, no extension to `RedisLike`.
 *
 * Why polling and not pub/sub:
 * 1. Polling only happens while a confirmation modal is open — a tiny,
 *    bursty population. At our scale the steady-state Redis traffic is
 *    indistinguishable from idle.
 * 2. The `RedisLike` interface in this service is intentionally minimal
 *    (`get`/`set`/`del`/`scan`). Adding pub/sub means a second connection
 *    and a wider interface for a sub-100ms latency win that doesn't matter
 *    here.
 * 3. Polling fails open in a useful way: a Redis blip causes the next poll
 *    to retry, not a dropped subscription requiring resubscribe-and-recover
 *    bookkeeping.
 *
 * If the elicit-latency profile ever changes (e.g. high-frequency
 * automated confirmations), swap to a `PubSubSessionResponseBus` behind
 * the same interface — call sites won't change.
 */

import type { RedisLike } from '@/hono/cache/RedisCache'

import { createAdaptivePollSchedule, type AdaptivePollSchedule, DEFAULT_ADAPTIVE_POLL_CONFIG } from './adaptive-poll'
import { SessionBusAbortedError, SessionBusTimeoutError, SessionBusUnhealthyError } from './errors'
import type { AwaitOptions, BusAwaitMetrics, SessionResponseBus } from './types'

/** Default TTL on stored response payloads. Long enough to bridge the slowest
 *  realistic awaiter cycle (1s polling + jitter), short enough to keep Redis
 *  clean of abandoned responses. */
const DEFAULT_RESPONSE_TTL_SECONDS = 60

/** Maximum consecutive Redis errors before the await gives up with
 *  `SessionBusUnhealthyError`. Lower than typical infra retry budgets — we'd
 *  rather fail closed quickly than keep a human waiting on a broken bus. */
const DEFAULT_MAX_CONSECUTIVE_ERRORS = 5

/** Namespace for all session-response keys. Keep it greppable and
 *  stable — `redis-cli --scan --pattern "mcp:session-response:*"` is a
 *  load-bearing debugging tool. */
const KEY_PREFIX = 'mcp:session-response'

export interface RedisPollingSessionResponseBusOptions {
    /** Polling cadence schedule. Defaults to the adaptive default. */
    schedule?: AdaptivePollSchedule
    /** TTL on each delivered response, in seconds. Defaults to 60s. */
    responseTtlSeconds?: number
    /** Maximum consecutive Redis errors tolerated before failing the await. */
    maxConsecutiveErrors?: number
}

export class RedisPollingSessionResponseBus implements SessionResponseBus {
    private readonly schedule: AdaptivePollSchedule
    private readonly responseTtlSeconds: number
    private readonly maxConsecutiveErrors: number

    constructor(
        private readonly redis: RedisLike,
        options: RedisPollingSessionResponseBusOptions = {}
    ) {
        this.schedule = options.schedule ?? createAdaptivePollSchedule(DEFAULT_ADAPTIVE_POLL_CONFIG)
        this.responseTtlSeconds = options.responseTtlSeconds ?? DEFAULT_RESPONSE_TTL_SECONDS
        this.maxConsecutiveErrors = options.maxConsecutiveErrors ?? DEFAULT_MAX_CONSECUTIVE_ERRORS
    }

    async await<T>(sessionId: string, requestId: string | number, options: AwaitOptions): Promise<T> {
        const key = buildKey(sessionId, requestId)
        const startedAt = Date.now()
        const deadline = startedAt + options.timeoutMs
        const metrics: BusAwaitMetrics | undefined = options.metrics
        safeMetric(() => metrics?.onAwaitStart?.(sessionId, requestId))

        if (options.signal?.aborted === true) {
            const reason = describeAbortReason(options.signal)
            safeMetric(() => metrics?.onAbort?.(sessionId, requestId, reason))
            throw new SessionBusAbortedError(reason)
        }

        let consecutiveErrors = 0

        // Single poll loop — short, deliberately stateless between iterations.
        // All early-exit conditions live in `checkExit`.
        while (true) {
            const exit = checkExit(deadline, options.signal)
            if (exit !== null) {
                if (exit.kind === 'timeout') {
                    safeMetric(() => metrics?.onTimeout?.(sessionId, requestId))
                    throw new SessionBusTimeoutError(sessionId, requestId, options.timeoutMs)
                }
                safeMetric(() => metrics?.onAbort?.(sessionId, requestId, exit.reason))
                throw new SessionBusAbortedError(exit.reason)
            }

            safeMetric(() => metrics?.onPoll?.(sessionId, requestId))

            let raw: string | null
            try {
                raw = await this.redis.get(key)
                consecutiveErrors = 0
            } catch (error) {
                consecutiveErrors++
                if (consecutiveErrors >= this.maxConsecutiveErrors) {
                    safeMetric(() => metrics?.onUnhealthy?.(sessionId, requestId, error))
                    throw new SessionBusUnhealthyError(
                        `Redis GET failed ${consecutiveErrors} consecutive times for session=${sessionId} request=${requestId}`,
                        { cause: error }
                    )
                }
                // Fall through to sleep-and-retry — a transient Redis blip
                // shouldn't break a 5-minute human-interactive await.
                raw = null
            }

            if (raw !== null) {
                // Deliver-then-DEL gives one-shot semantics. Best-effort: a
                // failed DEL just lets the value linger until its TTL expires.
                this.redis.del(key).catch(() => {
                    /* swallow */
                })
                safeMetric(() => metrics?.onResolve?.(sessionId, requestId, Date.now() - startedAt))
                return parsePayload<T>(raw)
            }

            const elapsedMs = Date.now() - startedAt
            const remainingMs = deadline - Date.now()
            const cadence = this.schedule.nextDelay(elapsedMs)
            const sleepMs = Math.max(0, Math.min(cadence, remainingMs))
            if (sleepMs > 0) {
                await sleepWithAbort(sleepMs, options.signal)
            }
        }
    }

    async deliver(sessionId: string, requestId: string | number, payload: unknown): Promise<void> {
        const key = buildKey(sessionId, requestId)
        const value = JSON.stringify(payload)
        // `SET key value EX seconds` — TTL guarantees abandoned responses
        // self-clean. Last-writer-wins is fine; the await reads exactly once.
        try {
            await this.redis.set(key, value, 'EX', this.responseTtlSeconds)
        } catch (error) {
            throw new SessionBusUnhealthyError(`Redis SET failed for session=${sessionId} request=${requestId}`, {
                cause: error,
            })
        }
    }
}

interface ExitTimeout {
    kind: 'timeout'
}
interface ExitAborted {
    kind: 'aborted'
    reason: string
}

function checkExit(deadline: number, signal: AbortSignal | undefined): ExitTimeout | ExitAborted | null {
    if (signal?.aborted === true) {
        return { kind: 'aborted', reason: describeAbortReason(signal) }
    }
    if (Date.now() >= deadline) {
        return { kind: 'timeout' }
    }
    return null
}

function parsePayload<T>(raw: string): T {
    try {
        return JSON.parse(raw) as T
    } catch (error) {
        throw new SessionBusUnhealthyError(
            `Stored response payload was not valid JSON. The bus contract requires JSON-serializable payloads.`,
            { cause: error }
        )
    }
}

function buildKey(_sessionId: string, requestId: string | number): string {
    // The JSONRPC request id is globally unique (UUID for server-initiated
    // requests), so it alone suffices as the correlation key. The session id
    // is accepted for API symmetry but intentionally not part of the key:
    // clients (notably MCP Inspector) don't reliably echo `Mcp-Session-Id`
    // across the request that triggered the elicit and the request that
    // delivers its response, so requiring session-level correlation would
    // strand legitimate replies.
    return `${KEY_PREFIX}:${requestId}`
}

async function sleepWithAbort(ms: number, signal: AbortSignal | undefined): Promise<void> {
    return await new Promise<void>((resolve) => {
        const timer = setTimeout(() => {
            signal?.removeEventListener('abort', onAbort)
            resolve()
        }, ms)
        const onAbort = (): void => {
            clearTimeout(timer)
            resolve() // resolve, not reject — the outer loop checks `signal.aborted` next.
        }
        if (signal !== undefined) {
            signal.addEventListener('abort', onAbort, { once: true })
        }
    })
}

function describeAbortReason(signal: AbortSignal | undefined): string {
    if (signal === undefined) {
        return 'unknown'
    }
    const reason = (signal as AbortSignal & { reason?: unknown }).reason
    if (reason instanceof Error) {
        return reason.message
    }
    if (typeof reason === 'string') {
        return reason
    }
    return 'aborted'
}

function safeMetric(fn: () => void): void {
    try {
        fn()
    } catch {
        /* metrics must never affect bus behavior */
    }
}
