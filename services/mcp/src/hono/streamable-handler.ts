import { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js'

import type { Lifecycle } from './app'
import type { RedisLike } from './cache/RedisCache'
import { HonoMcpServer } from './mcp-server'
import { authenticateAndParse, handleCatchError, passThrough } from './request-utils'
import type { BusAwaitMetrics, JsonRpcRequestMessage, SessionResponseBus, TransportMessageSender } from './session-bus'
import type { HonoCtx } from './types'

/**
 * Streamable-HTTP entry point for MCP requests.
 *
 * Responsibilities:
 *
 * 1. **Inbound request handling** — `tools/call`, `initialize`, etc. flow
 *    through `transport.handleRequest()` as usual. Each request gets a
 *    fresh `HonoMcpServer` + transport; that's the existing pattern and
 *    is unchanged.
 *
 * 2. **Inbound response routing (new)** — when the client POSTs a
 *    server-initiated request's response (today: an elicitation response),
 *    the body is a JSONRPC response shape rather than a request. We detect
 *    that, route the payload to whichever pod is awaiting it via the
 *    {@link SessionResponseBus}, and short-circuit with 202 — the SDK
 *    transport never sees these.
 *
 * The body is read once, classified, then re-supplied to the transport via
 * a fresh `Request` if it turns out to be a request. The classification is
 * cheap and avoids the alternative (multiple transports peeking at the
 * stream or hacking the SDK's response correlation).
 */
export class StreamableMcpHandler {
    constructor(
        private readonly redis: RedisLike,
        private readonly lifecycle: Lifecycle,
        private readonly sessionBus: SessionResponseBus,
        private readonly busMetrics?: BusAwaitMetrics
    ) {}

    fetch = async (c: HonoCtx): Promise<Response> => {
        if (c.req.method !== 'POST') {
            return new Response('Method not allowed', { status: 405 })
        }
        if (this.lifecycle.shuttingDown) {
            return new Response('Server shutting down', { status: 503 })
        }

        const auth = await authenticateAndParse(c, 'streamable-http')
        if ('error' in auth) {
            return auth.error
        }

        // Read the body once. We need to classify it before we know whether to
        // hand it to the SDK transport or to the session bus.
        let bodyText: string
        try {
            bodyText = await c.req.raw.clone().text()
        } catch (error) {
            return handleCatchError(error, auth.props)
        }

        const sessionId = extractOrCreateSessionId(c)
        const classification = classifyBody(bodyText)

        if (classification.kind === 'response') {
            // Server-initiated request's response coming back from the client.
            // Route it across pods via the bus; never touches the SDK.
            try {
                await this.sessionBus.deliver(sessionId, classification.id, classification.payload)
            } catch (error) {
                return handleCatchError(error, auth.props)
            }
            return new Response(null, { status: 202 })
        }

        try {
            const serverOptions: {
                sessionBus: SessionResponseBus
                sessionId: string
                busMetrics?: BusAwaitMetrics
            } = {
                sessionBus: this.sessionBus,
                sessionId,
            }
            if (this.busMetrics !== undefined) {
                serverOptions.busMetrics = this.busMetrics
            }
            const mcpServer = new HonoMcpServer(this.redis, auth.props, serverOptions)
            mcpServer.bindAbortSignal(c.req.raw.signal)
            await mcpServer.init()

            // We do NOT set `sessionIdGenerator` on the SDK transport — its
            // session management is per-instance and we create a fresh
            // transport per request, so it would treat every follow-up call
            // as an uninitialized session. Our `sessionId` lives outside the
            // SDK: clients echo it via `Mcp-Session-Id` and we use it
            // strictly as a session-bus key.
            const transport = new WebStandardStreamableHTTPServerTransport({})
            mcpServer.bindTransportSender(buildTransportSender(transport))

            await mcpServer.server.connect(transport)
            const response = await passThrough(await transport.handleRequest(c.req.raw))
            // Surface the session id to the client on its first response so it
            // can echo it back via `Mcp-Session-Id` on subsequent requests.
            response.headers.set('Mcp-Session-Id', sessionId)
            return response
        } catch (error) {
            return handleCatchError(error, auth.props)
        }
    }
}

/**
 * Build a {@link TransportMessageSender} that wraps the SDK transport's send
 * method. Used by the elicitation gateway to push outbound JSONRPC messages
 * over the active SSE channel without going through the SDK's request
 * correlation (which is per-process and wouldn't survive a cross-pod
 * response).
 */
function buildTransportSender(transport: WebStandardStreamableHTTPServerTransport): TransportMessageSender {
    return {
        async send(message: JsonRpcRequestMessage, options): Promise<void> {
            // Streamable HTTP transports route server-initiated messages over
            // the SSE channel of the related inbound request — `relatedRequestId`
            // tells the SDK which channel to use. Omitting it causes the message
            // to fall through to the (rarely-subscribed) standalone GET stream.
            const sendOptions =
                options?.relatedRequestId !== undefined ? { relatedRequestId: options.relatedRequestId } : undefined
            await transport.send(message as never, sendOptions)
        },
    }
}

/**
 * Read the `Mcp-Session-Id` request header. If absent, generate a new one.
 *
 * Echoing the freshly-generated id back on the response is the streamable
 * handler's responsibility — see `fetch()`.
 */
function extractOrCreateSessionId(c: HonoCtx): string {
    const fromHeader = c.req.header('Mcp-Session-Id') ?? c.req.header('mcp-session-id')
    if (fromHeader && fromHeader.trim().length > 0) {
        return fromHeader.trim()
    }
    return crypto.randomUUID()
}

type BodyClassification = { kind: 'request' } | { kind: 'response'; id: string | number; payload: unknown }

/**
 * Decide whether the inbound body is a JSONRPC **response** (server-initiated
 * request's reply, e.g. an elicit result) or a **request** (everything else).
 *
 * Returns `{ kind: 'request' }` for anything ambiguous or malformed — the SDK
 * transport already has rigorous JSONRPC validation, so we keep this peek
 * intentionally conservative: only short-circuit when we're certain.
 */
function classifyBody(bodyText: string): BodyClassification {
    if (bodyText.trim().length === 0) {
        return { kind: 'request' }
    }
    let parsed: unknown
    try {
        parsed = JSON.parse(bodyText)
    } catch {
        return { kind: 'request' }
    }

    // Streamable HTTP allows batching — handle the single-message common case
    // here; batched arrays fall through to the SDK, which already supports them.
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return { kind: 'request' }
    }

    const message = parsed as Record<string, unknown>
    const id = message.id
    const hasResult = 'result' in message
    const hasError = 'error' in message
    const hasMethod = 'method' in message

    // JSONRPC response: id present, has result or error, no method.
    const isResponse = !hasMethod && (hasResult || hasError) && (typeof id === 'string' || typeof id === 'number')
    if (!isResponse) {
        return { kind: 'request' }
    }
    const payload = hasError ? { error: message.error } : message.result
    return { kind: 'response', id: id as string | number, payload }
}
// trigger rebuild 1779467266
