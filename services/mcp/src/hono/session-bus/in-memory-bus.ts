/**
 * In-process implementation of `SessionResponseBus`.
 *
 * Designed for two consumers:
 * 1. **Tests** — deterministic, no I/O, no Redis dependency.
 * 2. **Single-pod dev** — when `REDIS_URL` is unset and the operator opts
 *    into in-memory mode explicitly. Not safe for multi-pod production.
 *
 * Awaits are stored in a `Map` keyed by JSONRPC request id. Deliveries
 * before any awaiter is registered are also held briefly under the same key
 * (60s) so the typical await→deliver race is forgiving in both orderings.
 */

import { SessionBusAbortedError, SessionBusTimeoutError } from './errors'
import type { AwaitOptions, BusAwaitMetrics, SessionResponseBus } from './types'

interface ParkedAwait {
    resolve: (payload: unknown) => void
    reject: (err: Error) => void
}

interface PendingDelivery {
    payload: unknown
    cleanupTimer: ReturnType<typeof setTimeout>
}

/** How long an early delivery is held before any awaiter shows up. */
const EARLY_DELIVERY_TTL_MS = 60_000

export class InMemorySessionResponseBus implements SessionResponseBus {
    private readonly awaits = new Map<string, ParkedAwait>()
    private readonly earlyDeliveries = new Map<string, PendingDelivery>()

    async await<T>(requestId: string | number, options: AwaitOptions): Promise<T> {
        const key = buildKey(requestId)
        const startedAt = Date.now()
        const metrics: BusAwaitMetrics | undefined = options.metrics
        safeMetric(() => metrics?.onAwaitStart?.(requestId))

        // If a deliver() landed before us, return immediately.
        const early = this.earlyDeliveries.get(key)
        if (early !== undefined) {
            clearTimeout(early.cleanupTimer)
            this.earlyDeliveries.delete(key)
            safeMetric(() => metrics?.onResolve?.(requestId, 0))
            return early.payload as T
        }

        if (this.awaits.has(key)) {
            // Two concurrent awaits on the same key would be ambiguous about who
            // wins on deliver(). Refuse rather than silently misbehaving.
            throw new Error(`Concurrent await for the same request=${requestId} is not supported`)
        }

        return await new Promise<T>((resolve, reject) => {
            const timer = setTimeout(() => {
                this.awaits.delete(key)
                safeMetric(() => metrics?.onTimeout?.(requestId))
                reject(new SessionBusTimeoutError(requestId, options.timeoutMs))
            }, options.timeoutMs)

            const abortHandler = (): void => {
                clearTimeout(timer)
                this.awaits.delete(key)
                const reason = describeAbortReason(options.signal)
                safeMetric(() => metrics?.onAbort?.(requestId, reason))
                reject(new SessionBusAbortedError(reason))
            }

            if (options.signal !== undefined) {
                if (options.signal.aborted) {
                    abortHandler()
                    return
                }
                options.signal.addEventListener('abort', abortHandler, { once: true })
            }

            this.awaits.set(key, {
                resolve: (payload: unknown) => {
                    clearTimeout(timer)
                    options.signal?.removeEventListener('abort', abortHandler)
                    safeMetric(() => metrics?.onResolve?.(requestId, Date.now() - startedAt))
                    resolve(payload as T)
                },
                reject: (err: Error) => {
                    clearTimeout(timer)
                    options.signal?.removeEventListener('abort', abortHandler)
                    reject(err)
                },
            })
        })
    }

    deliver(requestId: string | number, payload: unknown): Promise<void> {
        const key = buildKey(requestId)
        const parked = this.awaits.get(key)
        if (parked !== undefined) {
            this.awaits.delete(key)
            parked.resolve(payload)
            return Promise.resolve()
        }
        // No awaiter yet — hold the payload briefly so a slightly-late awaiter
        // can still pick it up. Mirrors the Redis TTL on the writer side.
        const existing = this.earlyDeliveries.get(key)
        if (existing !== undefined) {
            clearTimeout(existing.cleanupTimer)
        }
        const cleanupTimer = setTimeout(() => {
            this.earlyDeliveries.delete(key)
        }, EARLY_DELIVERY_TTL_MS)
        // unref so tests don't hang on the timer
        cleanupTimer.unref?.()
        this.earlyDeliveries.set(key, { payload, cleanupTimer })
        return Promise.resolve()
    }

    /** Drain all parked awaits with the given reason. Used in shutdown. */
    abortAll(reason: string): void {
        for (const [key, parked] of this.awaits.entries()) {
            this.awaits.delete(key)
            parked.reject(new SessionBusAbortedError(reason))
        }
        for (const [key, delivery] of this.earlyDeliveries.entries()) {
            clearTimeout(delivery.cleanupTimer)
            this.earlyDeliveries.delete(key)
        }
    }

    /** Test helper — count parked awaits. Not part of the public interface. */
    parkedCount(): number {
        return this.awaits.size
    }
}

function buildKey(requestId: string | number): string {
    return `${requestId}`
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
        // Metrics hooks must never affect the bus.
    }
}
