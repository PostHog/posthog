/**
 * MCP-specific glue between the elicit call site and the session bus.
 *
 * This is the only file in `session-bus/` that knows about MCP. The bus
 * itself is generic — anything below this layer treats payloads as opaque
 * JSON keyed by JSONRPC request id.
 *
 * Why we don't use the SDK's `Server.request()` / `elicitInput()` here:
 * the Hono dispatcher is a hand-rolled JSON-RPC server (it does not
 * instantiate `McpServer`). The SDK's per-process pending-request map
 * isn't in play at all. We emit `elicitation/create` directly via a
 * caller-supplied `TransportMessageSender` (the SSE writer for the
 * current request) and park on the bus until the client POSTs a response
 * that the streamable handler routes via `bus.deliver`.
 */

import type { ElicitRequestFormParams, ElicitResult } from '@modelcontextprotocol/sdk/types.js'

import { validateElicitResult } from './elicit-result-validator'
import { ElicitationNotSupportedError } from './errors'
import type { BusAwaitMetrics, SessionResponseBus } from './types'

/**
 * Sends raw JSONRPC messages to the client.
 *
 * Decoupled from any specific transport. The concrete implementation in
 * `dispatcher.ts` wraps the per-request SSE writer.
 */
export interface TransportMessageSender {
    /** Push a JSONRPC request message to the client. */
    send(message: JsonRpcRequestMessage): Promise<void>
}

export interface JsonRpcRequestMessage {
    jsonrpc: '2.0'
    id: string
    method: string
    params: unknown
}

export interface ElicitationGatewayOptions {
    /** Default deadline for an elicit. May be overridden per call. */
    defaultTimeoutMs?: number
    /** Optional metrics hook applied to every await. */
    metrics?: BusAwaitMetrics
}

export interface ElicitCallOptions {
    /** Override the gateway's default timeout for this call. */
    timeoutMs?: number
    /** Abort the elicit immediately when this signal fires. The originating
     *  HTTP request's `AbortSignal` is the typical source. */
    signal?: AbortSignal
}

/** Default elicit timeout. 5 minutes — comfortable for human interaction. */
const DEFAULT_ELICIT_TIMEOUT_MS = 5 * 60 * 1000

function safeMetric(fn: () => void): void {
    try {
        fn()
    } catch {
        /* metrics must never affect gateway behavior */
    }
}

export class ElicitationGateway {
    constructor(
        private readonly bus: SessionResponseBus,
        private readonly sender: TransportMessageSender,
        private readonly options: ElicitationGatewayOptions = {}
    ) {}

    /**
     * Send an `elicitation/create` request to the client and await its
     * response via the session bus.
     *
     * Throws (no recovery):
     * - `SessionBusTimeoutError` if no response within the deadline.
     * - `SessionBusAbortedError` if `options.signal` aborts.
     * - `ElicitationNotSupportedError` if the client returned a JSON-RPC error
     *   envelope (e.g. `-32601 Method not found` from a client that didn't
     *   advertise elicitation support). Tool authors should catch this and
     *   fall back to a non-interactive path (typically: refuse the operation
     *   and return an instructional message).
     * - `SessionBusUnhealthyError` if the bus transport fails or the payload
     *   is structurally invalid (not a result, not a JSON-RPC error envelope).
     */
    async elicit(params: ElicitRequestFormParams, options: ElicitCallOptions = {}): Promise<ElicitResult> {
        const requestId = crypto.randomUUID()
        const timeoutMs = options.timeoutMs ?? this.options.defaultTimeoutMs ?? DEFAULT_ELICIT_TIMEOUT_MS

        await this.sender.send({
            jsonrpc: '2.0',
            id: requestId,
            method: 'elicitation/create',
            params: params as unknown,
        })

        const awaitOptions: import('./types').AwaitOptions = { timeoutMs }
        if (options.signal !== undefined) {
            awaitOptions.signal = options.signal
        }
        if (this.options.metrics !== undefined) {
            awaitOptions.metrics = this.options.metrics
        }
        const raw = await this.bus.await<unknown>(requestId, awaitOptions)

        try {
            return validateElicitResult(raw)
        } catch (error) {
            if (error instanceof ElicitationNotSupportedError) {
                safeMetric(() => this.options.metrics?.onNotSupported?.(requestId, error.code))
            }
            throw error
        }
    }
}
