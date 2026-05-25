/**
 * Per-request binding that connects a tool handler's `context.elicit()` call
 * to the dispatcher's response writer.
 *
 * The dispatcher knows: the session bus, the request signal, and how to
 * create an SSE response when one is needed. The tool handler only sees
 * `Context.elicit(params)`. This binding is the seam.
 *
 * Lifecycle:
 *
 * 1. Dispatcher constructs `ElicitBinding` for a `tools/call` request and
 *    installs it on the `RequestContext` via `setElicitBinding`.
 * 2. Dispatcher races the tool handler's promise against `firstElicit`.
 * 3. If the tool handler finishes first (no elicit), dispatcher returns
 *    plain JSON — same path as today.
 * 4. If `firstElicit` resolves first, dispatcher retrieves the `SseResponseHandle`
 *    via `getSseHandle()` and returns its `response`. The dispatcher then
 *    awaits the still-running tool handler in the background and writes
 *    the final tool-call result (or error) to the same SSE stream before
 *    closing it.
 *
 * The binding ensures elicits are serialized through a single SSE writer
 * even when a tool handler invokes elicit multiple times.
 */

import type { ElicitRequestFormParams, ElicitResult } from '@modelcontextprotocol/sdk/types.js'

import {
    ElicitationGateway,
    type ElicitationGatewayOptions,
    type SessionResponseBus,
    type TransportMessageSender,
} from './session-bus'
import type { SseResponseHandle } from './sse-response'

export interface ElicitBindingDeps {
    /** Cross-pod response bus. */
    bus: SessionResponseBus
    /**
     * Lazily produce the SSE response handle for this request. The binding
     * calls this once on the first elicit invocation, at which point the
     * in-flight HTTP response transitions from JSON to SSE.
     */
    createSseHandle: () => Promise<SseResponseHandle>
    /**
     * The originating HTTP request's AbortSignal — propagates client
     * disconnects into any pending elicit awaits.
     */
    requestSignal?: AbortSignal
    /** Optional gateway-level options (metrics, default timeout). */
    gatewayOptions?: ElicitationGatewayOptions
}

export class ElicitBinding {
    private gatewayPromise: Promise<ElicitationGateway> | undefined
    private sseHandle: SseResponseHandle | undefined

    private firstElicitResolve!: () => void
    /**
     * Resolves the first time a tool handler invokes `elicit()`. The
     * dispatcher races this against the tool handler's completion promise
     * to decide whether to return a plain JSON response or upgrade to SSE.
     */
    readonly firstElicit: Promise<void>

    constructor(private readonly deps: ElicitBindingDeps) {
        this.firstElicit = new Promise((resolve) => {
            this.firstElicitResolve = resolve
        })
    }

    /**
     * Invoke an elicit. Lazily upgrades the response to SSE on first call,
     * sends the `elicitation/create` message, and parks on the bus until
     * the client responds (or until timeout / abort).
     */
    async invoke(
        params: ElicitRequestFormParams,
        options?: { timeoutMs?: number; signal?: AbortSignal }
    ): Promise<ElicitResult> {
        const gateway = await this.getGateway()
        const callOptions: { timeoutMs?: number; signal?: AbortSignal } = {}
        if (options?.timeoutMs !== undefined) {
            callOptions.timeoutMs = options.timeoutMs
        }
        // Prefer the per-call signal if provided; otherwise fall back to the
        // request-level signal so client disconnects propagate.
        const signal = options?.signal ?? this.deps.requestSignal
        if (signal !== undefined) {
            callOptions.signal = signal
        }
        return gateway.elicit(params, callOptions)
    }

    /**
     * Returns the SSE response handle if the dispatcher upgraded the
     * response, otherwise `undefined`. The dispatcher reads this after
     * `firstElicit` resolves to obtain the streaming Response object.
     */
    getSseHandle(): SseResponseHandle | undefined {
        return this.sseHandle
    }

    private async getGateway(): Promise<ElicitationGateway> {
        if (!this.gatewayPromise) {
            this.gatewayPromise = (async () => {
                const handle = await this.deps.createSseHandle()
                this.sseHandle = handle
                this.firstElicitResolve()
                const sender: TransportMessageSender = {
                    async send(message) {
                        await handle.writer.write(message)
                    },
                }
                return new ElicitationGateway(this.deps.bus, sender, this.deps.gatewayOptions ?? {})
            })()
        }
        return this.gatewayPromise
    }
}
