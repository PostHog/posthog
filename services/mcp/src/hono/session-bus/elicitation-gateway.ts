/**
 * MCP-specific glue between the elicit call site and the session bus.
 *
 * This is the only file in `session-bus/` that knows about MCP. The bus
 * itself is generic — anything below this layer treats payloads as opaque
 * JSON keyed by `(sessionId, requestId)`.
 *
 * Why we don't use the SDK's `Server.request()` to send the elicit:
 * - `Server.request()` correlates the response via the SDK's in-process
 *   pending-request map. That map is on whichever pod sent the request.
 *   In our multi-pod setup the response can arrive on any pod, so the SDK's
 *   correlation never fires — we'd just wait until timeout.
 * - Instead we send the JSONRPC message directly via the connected
 *   transport (which is the open SSE channel to the originating client),
 *   then await via our bus, which is cross-pod by construction.
 *
 * Behavior contract:
 * - Each call generates a fresh JSONRPC request ID via `crypto.randomUUID()`.
 * - The message goes out as a JSONRPC request shape; the client
 *   (Claude Code etc.) is responsible for responding with the matching id.
 * - On the response side, the inbound HTTP handler is expected to detect
 *   JSONRPC responses and call `bus.deliver(sessionId, id, payload)` —
 *   the gateway has no knowledge of how that happens.
 */

import type { ElicitRequestFormParams, ElicitResult } from '@modelcontextprotocol/sdk/types.js'

import { validateElicitResult } from './elicit-result-validator'
import type { BusAwaitMetrics, SessionResponseBus } from './types'

/**
 * Sends raw JSONRPC messages over the active per-request transport.
 *
 * Decoupled from any specific SDK to keep the gateway transport-agnostic.
 * The concrete implementation in `hono/mcp-server.ts` adapts the SDK
 * `WebStandardStreamableHTTPServerTransport`'s outbound API to this shape.
 */
export interface TransportMessageSender {
    /**
     * Push a JSONRPC message to the client. Resolves when the message has
     * been handed to the underlying transport (not when the client receives
     * it).
     *
     * `options.relatedRequestId` associates the outbound message with the
     * inbound request that triggered it — required by the Streamable HTTP
     * transport to route the message over the right open SSE channel. Without
     * it, the message falls to the standalone SSE stream that most clients
     * never subscribe to and the elicit silently goes nowhere.
     */
    send(message: JsonRpcRequestMessage, options?: { relatedRequestId?: string | number }): Promise<void>
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
    /** The id of the inbound JSONRPC request whose handler is making this
     *  elicit. Forwarded to the transport as `relatedRequestId` so the
     *  outbound message is routed over the open SSE channel. */
    relatedRequestId?: string | number
}

/** Default elicit timeout. 5 minutes — comfortable for human interaction. */
const DEFAULT_ELICIT_TIMEOUT_MS = 5 * 60 * 1000

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
     * - `SessionBusUnhealthyError` if the bus or the validation step fails.
     */
    async elicit(
        sessionId: string,
        params: ElicitRequestFormParams,
        options: ElicitCallOptions = {}
    ): Promise<ElicitResult> {
        const requestId = crypto.randomUUID()
        const timeoutMs = options.timeoutMs ?? this.options.defaultTimeoutMs ?? DEFAULT_ELICIT_TIMEOUT_MS

        const sendOptions: { relatedRequestId?: string | number } = {}
        if (options.relatedRequestId !== undefined) {
            sendOptions.relatedRequestId = options.relatedRequestId
        }
        await this.sender.send(
            {
                jsonrpc: '2.0',
                id: requestId,
                method: 'elicitation/create',
                params: params as unknown,
            },
            sendOptions
        )

        const awaitOptions: import('./types').AwaitOptions = { timeoutMs }
        if (options.signal !== undefined) {
            awaitOptions.signal = options.signal
        }
        if (this.options.metrics !== undefined) {
            awaitOptions.metrics = this.options.metrics
        }
        const raw = await this.bus.await<unknown>(sessionId, requestId, awaitOptions)

        return validateElicitResult(raw)
    }
}
