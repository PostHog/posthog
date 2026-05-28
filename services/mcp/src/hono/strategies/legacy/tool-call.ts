/**
 * Legacy (`2025-06-18`) `tools/call` dispatch.
 *
 * Race between the tool handler and the first elicit:
 *
 * - Handler completes first → return plain JSON.
 * - First elicit fires first → upgrade response to SSE, flush the
 *   `elicitation/create` message, continue awaiting the handler in the
 *   background, then write the final tool result to the SSE stream and close.
 *
 * Capability-gated: the binding is only installed when the client declared
 * `elicitation` at initialize. Otherwise the handler runs without one and
 * `context.requestInput` resolves to `undefined`.
 */

import { ErrorCode, JSONRPC_VERSION, type JSONRPCRequest } from '@modelcontextprotocol/sdk/types.js'

import type { RequestProperties } from '@/lib/request-properties'

import { CapabilityStore, supportsAnyElicitation } from '../../capability-store'
import { ElicitBinding } from '../../elicit-binding'
import type { ProtocolStrategy, ToolCallStrategy } from '../../protocol-strategy'
import type { ResolvedState } from '../../request-state-resolver'
import { type BusAwaitMetrics, type SessionResponseBus } from '../../session-bus'
import { createSseResponse, type SseResponseHandle } from '../../sse-response'
import { ToolExecutor } from '../../tool-executor'

type JsonRpcResponse =
    | { jsonrpc: typeof JSONRPC_VERSION; id: number | string; result: unknown }
    | { jsonrpc: typeof JSONRPC_VERSION; id: number | string; error: { code: number; message: string } }

type HandlerOutcome = { kind: 'success'; value: unknown } | { kind: 'error'; error: unknown }

export interface LegacyToolCallDeps {
    capabilityStore: CapabilityStore
    sessionBus: SessionResponseBus
    busMetrics: BusAwaitMetrics | undefined
    toolExecutor: ToolExecutor
}

export class LegacyToolCallStrategy implements ToolCallStrategy {
    constructor(private readonly deps: LegacyToolCallDeps) {}

    /** Legacy seam: inbound JSON-RPC responses go to the session bus. */
    async deliverInboundResponse(id: string | number, payload: unknown): Promise<void> {
        await this.deps.sessionBus.deliver(id, payload)
    }

    async dispatchToolsCall(
        request: JSONRPCRequest,
        props: RequestProperties,
        state: ResolvedState,
        requestSignal: AbortSignal
    ): Promise<Response> {
        const { id, params } = request

        const caps = await this.deps.capabilityStore.get(props.userHash)
        const elicitAllowed = supportsAnyElicitation(caps)

        if (!elicitAllowed) {
            // Fast path — no binding, no SSE possible. Same shape as a
            // pre-elicit tool call.
            const outcome = await this.runHandler(params, props, state)
            return jsonResponse(this.buildJsonRpcResponse(id, outcome))
        }

        const binding = new ElicitBinding({
            bus: this.deps.sessionBus,
            createSseHandle: async () => createSseResponse(),
            requestSignal,
            ...(this.deps.busMetrics !== undefined ? { gatewayOptions: { metrics: this.deps.busMetrics } } : {}),
        })
        state.reqCtx.setElicitBinding(binding)

        const handlerPromise = this.runHandler(params, props, state)

        const winner = await Promise.race([
            handlerPromise.then(() => 'handler' as const),
            binding.firstElicit.then(() => 'elicit' as const),
        ])

        if (winner === 'handler') {
            const outcome = await handlerPromise
            return jsonResponse(this.buildJsonRpcResponse(id, outcome))
        }

        // SSE path — the binding already wrote `elicitation/create`.
        // Return the streaming Response now; flush the final tool result
        // asynchronously.
        const sseHandle = binding.getSseHandle()
        if (!sseHandle) {
            return jsonResponse(internalError(id))
        }
        void this.finalizeSseResponse(sseHandle, id, handlerPromise)
        return sseHandle.response
    }

    private async runHandler(params: unknown, props: RequestProperties, state: ResolvedState): Promise<HandlerOutcome> {
        return await this.deps.toolExecutor
            .handleToolCall(params as Record<string, unknown> | undefined, props, state)
            .then((value): HandlerOutcome => ({ kind: 'success', value }))
            .catch((error): HandlerOutcome => ({ kind: 'error', error }))
    }

    private async finalizeSseResponse(
        sseHandle: SseResponseHandle,
        id: number | string,
        handlerPromise: Promise<HandlerOutcome>
    ): Promise<void> {
        try {
            const outcome = await handlerPromise
            const result = this.buildJsonRpcResponse(id, outcome)
            await sseHandle.writer.write(result)
        } catch (error) {
            console.error('[LegacyToolCallStrategy] SSE finalize failed:', error)
        } finally {
            try {
                await sseHandle.writer.close()
            } catch {
                /* already closed */
            }
        }
    }

    private buildJsonRpcResponse(id: number | string, outcome: HandlerOutcome): JsonRpcResponse {
        if (outcome.kind === 'success') {
            return { jsonrpc: JSONRPC_VERSION, id, result: outcome.value }
        }
        console.error('[LegacyToolCallStrategy] Internal error:', outcome.error)
        return internalError(id)
    }
}

function internalError(id: number | string): JsonRpcResponse {
    return { jsonrpc: JSONRPC_VERSION, id, error: { code: ErrorCode.InternalError, message: 'Internal error' } }
}

function jsonResponse(body: JsonRpcResponse): Response {
    return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
    })
}

// Re-export the strategy aggregate factory so call sites get a single import.
export function buildLegacyStrategy(deps: {
    capabilityStore: CapabilityStore
    sessionBus: SessionResponseBus
    busMetrics: BusAwaitMetrics | undefined
    toolExecutor: ToolExecutor
    handshake: import('./handshake').LegacyHandshakeStrategy
}): ProtocolStrategy {
    return {
        version: 'legacy',
        allowBatches: true,
        preDispatch: { async validate() {} },
        handshake: deps.handshake,
        toolCall: new LegacyToolCallStrategy({
            capabilityStore: deps.capabilityStore,
            sessionBus: deps.sessionBus,
            busMetrics: deps.busMetrics,
            toolExecutor: deps.toolExecutor,
        }),
    }
}
