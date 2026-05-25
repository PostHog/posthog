/**
 * Session-keyed response bus — the abstraction over cross-pod delivery of
 * server-initiated MCP request responses (elicitation, sampling, roots/list).
 *
 * The bus knows nothing about MCP itself. Its only job is to hold a parked
 * promise on one process until some other process (possibly the same one)
 * publishes a response keyed by the JSONRPC request id. Higher layers map
 * that primitive onto MCP-specific flows.
 *
 * Implementations:
 * - `InMemorySessionResponseBus` — single-process, used in tests and as the
 *   reference implementation.
 * - `RedisPollingSessionResponseBus` — Redis-backed polling for multi-pod
 *   Hono deployments. The default in production.
 *
 * The interface intentionally avoids exposing the transport (HTTP, SSE,
 * pub/sub, polling, …). Swapping the implementation requires no changes at
 * call sites; this is the load-bearing seam of the design.
 *
 * Correlation key: the JSONRPC request id (UUID for server-initiated
 * requests) is globally unique by construction, so it is the sole key. We
 * intentionally do not key on session id — MCP clients (notably the
 * Inspector) do not reliably echo `Mcp-Session-Id` across the request that
 * triggered the elicit and the request that delivers its response, so
 * requiring session-level correlation would strand legitimate replies.
 */

export interface SessionResponseBus {
    /**
     * Block until a response for `requestId` is delivered, or until
     * `options.timeoutMs` elapses, or `options.signal` is aborted.
     *
     * Resolves at most once. The bus deletes any underlying state once the
     * promise resolves (one-shot semantics — replay attempts after resolution
     * find nothing).
     *
     * Throws:
     * - `SessionBusTimeoutError` when the deadline elapses with no response.
     * - `SessionBusAbortedError` when `options.signal` aborts before a
     *   response arrives.
     * - `SessionBusUnhealthyError` when the underlying transport is failing
     *   in a way the bus cannot recover from (e.g. Redis unreachable). Always
     *   wraps the original cause via `.cause`.
     */
    await<T>(requestId: string | number, options: AwaitOptions): Promise<T>

    /**
     * Make a response payload available to whichever process is awaiting it.
     *
     * Idempotent within the TTL window: calling twice with the same key
     * overwrites the stored payload. The awaiting promise resolves on the
     * first observation; subsequent deliveries are no-ops by virtue of the
     * one-shot read semantics on the await side.
     *
     * `payload` is stored opaquely. Validation belongs to the caller of
     * `await`, not the bus.
     */
    deliver(requestId: string | number, payload: unknown): Promise<void>
}

export interface AwaitOptions {
    /** Hard deadline in milliseconds. Required — there is no implicit default. */
    timeoutMs: number
    /** Optional abort signal — fires `SessionBusAbortedError` when triggered. */
    signal?: AbortSignal
    /** Optional metrics hook — see `BusAwaitMetrics`. */
    metrics?: BusAwaitMetrics
}

/**
 * Observation hooks for the await lifecycle. All methods are optional and
 * synchronous; exceptions thrown from them are caught and logged but do not
 * affect the bus's behavior.
 *
 * Provide a concrete implementation (Prometheus, statsd, PostHog analytics,
 * etc.) when wiring the bus. The default in tests and dev is a no-op.
 */
export interface BusAwaitMetrics {
    /** Called once at the start of each `await` invocation. */
    onAwaitStart?(requestId: string | number): void

    /** Called on each underlying poll attempt (no-op in non-polling impls). */
    onPoll?(requestId: string | number): void

    /** Called once when the await resolves with a payload. `latencyMs` is the
     *  time from `await` invocation to resolution. */
    onResolve?(requestId: string | number, latencyMs: number): void

    /** Called when the await deadline expires with no response. */
    onTimeout?(requestId: string | number): void

    /** Called when an `AbortSignal` cuts the await short. */
    onAbort?(requestId: string | number, reason: string): void

    /** Called when the underlying transport fails irrecoverably. */
    onUnhealthy?(requestId: string | number, cause: unknown): void
}
