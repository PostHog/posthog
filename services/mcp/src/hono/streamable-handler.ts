/**
 * HTTP entry-point for the MCP server.
 *
 * Owns auth, rate-limiting, body classification (legacy-only), and protocol
 * routing. Holds one `McpDispatcher` per protocol; both share the underlying
 * tool catalog + state resolver via `buildSharedDeps`.
 */

import type { Lifecycle } from './app'
import type { RedisLike } from './cache/RedisCache'
import { CapabilityStore } from './capability-store'
import { buildSharedDeps, McpDispatcher, type SharedDispatcherDeps } from './dispatcher'
import { buildRateLimitResponse, DEFAULT_BURST_LIMIT, DEFAULT_SUSTAINED_LIMIT, RateLimiter } from './rate-limiter'
import { authenticateAndParse, handleCatchError } from './request-utils'
import { type BusAwaitMetrics, RedisPollingSessionResponseBus, type SessionResponseBus } from './session-bus'
import { LegacyHandshakeStrategy } from './strategies/legacy/handshake'
import { buildLegacyStrategy } from './strategies/legacy/tool-call'
import { ToolCatalog } from './tool-catalog'
import type { HonoCtx } from './types'
import { PROTOCOL_VERSION_2025_06_18, PROTOCOL_VERSION_2026_07_28, PROTOCOL_VERSION_HEADER } from './v2026/constants'
import { V2026HandshakeStrategy } from './v2026/handshake'
import { loadSigningKeysFromEnv, RequestStateCodec } from './v2026/request-state'
import { buildV2026Strategy } from './v2026/tool-call'

export interface StreamableMcpHandlerOptions {
    /** Override the session bus for the legacy pipeline (tests inject InMemory). */
    sessionBus?: SessionResponseBus
    /** Override the bus metrics adapter (default: prom-client). */
    busMetrics?: BusAwaitMetrics
    /** Override the capability cache (legacy initialize-driven). */
    capabilityStore?: CapabilityStore
    /** Override the v2026 dispatcher (tests inject a deterministic codec). */
    dispatcher2026?: McpDispatcher
    /** Override the legacy dispatcher (rare — for diagnostic tests). */
    dispatcherLegacy?: McpDispatcher
}

export class StreamableMcpHandler {
    private readonly dispatcherLegacy: McpDispatcher
    private readonly dispatcher2026: McpDispatcher
    private readonly rateLimiter: RateLimiter

    constructor(
        redis: RedisLike,
        private readonly lifecycle: Lifecycle,
        options: StreamableMcpHandlerOptions = {}
    ) {
        const catalog = new ToolCatalog()
        const shared: SharedDispatcherDeps = buildSharedDeps(catalog, redis)

        const capabilityStore = options.capabilityStore ?? new CapabilityStore(redis)
        const sessionBus = options.sessionBus ?? new RedisPollingSessionResponseBus(redis)
        const busMetrics = options.busMetrics

        const legacyHandshake = new LegacyHandshakeStrategy(capabilityStore, shared.instructionsBuilder)
        const legacyStrategy = buildLegacyStrategy({
            capabilityStore,
            sessionBus,
            busMetrics,
            toolExecutor: shared.toolExecutor,
            handshake: legacyHandshake,
        })
        this.dispatcherLegacy = options.dispatcherLegacy ?? new McpDispatcher(shared, legacyStrategy)

        if (options.dispatcher2026) {
            this.dispatcher2026 = options.dispatcher2026
        } else {
            const { primary, secondary } = loadSigningKeysFromEnv()
            const codec = new RequestStateCodec(primary, secondary)
            const v2026Handshake = new V2026HandshakeStrategy(shared.instructionsBuilder)
            const v2026Strategy = buildV2026Strategy({
                codec,
                toolExecutor: shared.toolExecutor,
                handshake: v2026Handshake,
            })
            this.dispatcher2026 = new McpDispatcher(shared, v2026Strategy)
        }

        this.rateLimiter = new RateLimiter(redis, [DEFAULT_BURST_LIMIT, DEFAULT_SUSTAINED_LIMIT])
    }

    async warmup(): Promise<void> {
        await Promise.all([this.dispatcherLegacy.warmup(), this.dispatcher2026.warmup()])
    }

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

        // After auth so the bucket is keyed per token, not per IP — corporate
        // NATs shouldn't share buckets across unrelated users.
        const rateLimit = await this.rateLimiter.check(auth.props.userHash)
        if (rateLimit && !rateLimit.allowed) {
            return buildRateLimitResponse(rateLimit)
        }

        const dispatcher = selectPipeline(c.req.raw) === 'v2026' ? this.dispatcher2026 : this.dispatcherLegacy

        // The legacy strategy treats inbound JSON-RPC responses (replies to a
        // server-initiated `elicitation/create`) as bus deliveries, not as
        // dispatcher requests. v2026 has no separate response POSTs — every
        // retry is a fresh `tools/call` — so this branch is legacy-only.
        if (dispatcher.strategy.toolCall.deliverInboundResponse) {
            const classification = await classifyBody(c.req.raw)
            if (classification.kind === 'response') {
                try {
                    await dispatcher.strategy.toolCall.deliverInboundResponse(classification.id, classification.payload)
                } catch (error) {
                    return handleCatchError(error, auth.props)
                }
                return new Response(null, { status: 202 })
            }
            try {
                return await dispatcher.handleRequest(classification.req, auth.props)
            } catch (error) {
                return handleCatchError(error, auth.props)
            }
        }

        try {
            return await dispatcher.handleRequest(c.req.raw, auth.props)
        } catch (error) {
            return handleCatchError(error, auth.props)
        }
    }
}

/**
 * Choose the protocol pipeline for an incoming request. The
 * `MCP-Protocol-Version` header is authoritative — routing infrastructure
 * may inspect it without parsing the body.
 *
 * - `2026-07-28` → v2026.
 * - `2025-06-18` (explicit) → legacy.
 * - No header → legacy (every client in the field today omits this header).
 * - Anything else → legacy. The v2026 dispatcher's meta parser would
 *   reject mismatches itself.
 */
export function selectPipeline(req: Request): 'legacy' | 'v2026' {
    const headerVersion = req.headers.get(PROTOCOL_VERSION_HEADER)
    if (headerVersion === PROTOCOL_VERSION_2026_07_28) {
        return 'v2026'
    }
    if (headerVersion === PROTOCOL_VERSION_2025_06_18 || !headerVersion) {
        return 'legacy'
    }
    return 'legacy'
}

// ---------------------------------------------------------------------------
// Body classification — legacy only. Determines whether an inbound POST is a
// JSON-RPC request (→ dispatcher) or a response (→ session bus).
// ---------------------------------------------------------------------------

export type BodyClassification =
    | { kind: 'request'; req: Request }
    | { kind: 'response'; id: string | number; payload: unknown }

export async function classifyBody(req: Request): Promise<BodyClassification> {
    let bodyText: string
    try {
        bodyText = await req.clone().text()
    } catch {
        return { kind: 'request', req }
    }

    const rebuilt = new Request(req.url, {
        method: req.method,
        headers: req.headers,
        body: bodyText,
        signal: req.signal,
    })

    if (bodyText.trim().length === 0) {
        return { kind: 'request', req: rebuilt }
    }
    let parsed: unknown
    try {
        parsed = JSON.parse(bodyText)
    } catch {
        return { kind: 'request', req: rebuilt }
    }

    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return { kind: 'request', req: rebuilt }
    }

    const message = parsed as Record<string, unknown>
    const id = message['id']
    const hasResult = 'result' in message
    const hasError = 'error' in message
    const hasMethod = 'method' in message
    const isResponse = !hasMethod && (hasResult || hasError) && (typeof id === 'string' || typeof id === 'number')
    if (!isResponse) {
        return { kind: 'request', req: rebuilt }
    }
    const payload = hasError ? { error: message['error'] } : message['result']
    return { kind: 'response', id: id as string | number, payload }
}
