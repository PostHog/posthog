/**
 * Strategy seams between the two MCP protocol versions the Hono dispatcher
 * supports (`2025-06-18` and `2026-07-28`).
 *
 * Only the parts that genuinely differ are abstracted here — everything else
 * (`tools/list`, `ping`, `resources/*`, `prompts/*`, JSON-RPC parse,
 * top-level error responses) is shared in `McpDispatcher`.
 *
 * Three seams:
 *
 *   1. `PreDispatchStrategy` — per-request validation of protocol-specific
 *      headers and request shape. Legacy does almost nothing; v2026 validates
 *      `MCP-Protocol-Version`, `Mcp-Method`, and the `_meta` block.
 *   2. `HandshakeStrategy` — owns the protocol's handshake RPC
 *      (`initialize` for legacy, `server/discover` for v2026). Used for both
 *      method matching and result construction.
 *   3. `ToolCallStrategy` — owns `tools/call` end-to-end, because the two
 *      protocols use fundamentally different mechanisms for surfacing
 *      elicitation: legacy upgrades to SSE and parks on the cross-pod bus;
 *      v2026 returns `InputRequiredResult` synchronously with a signed
 *      `requestState` blob.
 *
 * A `ProtocolStrategy` bundles all three plus a flag for whether JSON-RPC
 * batches are allowed (legacy yes; v2026 no per SEP-2575).
 */

import type { JSONRPCRequest } from '@modelcontextprotocol/sdk/types.js'

import type { RequestProperties } from '@/lib/request-properties'

import type { ResolvedState } from './request-state-resolver'

/**
 * Per-request validation hook. Throws to short-circuit with a JSON-RPC error
 * (typically via `V2026ProtocolError` for v2026, or a JSON-RPC error code
 * for any custom legacy validation).
 *
 * Runs once per HTTP request, BEFORE body classification and state
 * resolution. Cheap by design — anything expensive (state resolution,
 * capability lookups) belongs inside the per-method strategies.
 */
export interface PreDispatchStrategy {
    validate(req: Request, body: unknown, props: RequestProperties): Promise<void>
}

/**
 * Handler for the protocol's handshake RPC. The dispatcher calls
 * `handle(...)` only when `method === request.method` matches. Returns the
 * result object (which the dispatcher wraps in JSON-RPC envelope).
 */
export interface HandshakeStrategy {
    /** Method name this handshake handles, e.g. `'initialize'` or `'server/discover'`. */
    readonly method: string
    handle(request: JSONRPCRequest, props: RequestProperties, state: ResolvedState): Promise<unknown>
}

/**
 * The `tools/call` dispatch path. Owns the entire flow including any
 * protocol-specific elicitation mechanism, returning the final HTTP
 * response. This is the largest divergence between protocols, so it gets
 * its own seam rather than parameter hooks on a shared method.
 */
export interface ToolCallStrategy {
    dispatchToolsCall(
        request: JSONRPCRequest,
        props: RequestProperties,
        state: ResolvedState,
        signal: AbortSignal
    ): Promise<Response>

    /**
     * Legacy-only: route an inbound JSON-RPC *response* (the client's reply
     * to a server-initiated `elicitation/create`) to the session bus.
     *
     * Undefined on v2026 — the new protocol doesn't have separate
     * response POSTs; every retry is a full `tools/call`.
     */
    deliverInboundResponse?(id: string | number, payload: unknown): Promise<void>
}

/**
 * Composite for a protocol. The dispatcher receives one of these at
 * construction time; the streamable handler chooses between two
 * pre-built instances based on the `MCP-Protocol-Version` header.
 */
export interface ProtocolStrategy {
    readonly version: 'legacy' | 'v2026'
    readonly preDispatch: PreDispatchStrategy
    readonly handshake: HandshakeStrategy
    readonly toolCall: ToolCallStrategy
    /**
     * Whether JSON-RPC batches are accepted. Legacy: yes. v2026: no
     * (per SEP-2575 — every request is its own continuation-passing call).
     */
    readonly allowBatches: boolean
}
