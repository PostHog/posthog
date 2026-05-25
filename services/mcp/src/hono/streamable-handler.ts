import type { Lifecycle } from './app'
import type { RedisLike } from './cache/RedisCache'
import { McpDispatcher, type McpDispatcherOptions } from './dispatcher'
import { buildRateLimitResponse, DEFAULT_BURST_LIMIT, DEFAULT_SUSTAINED_LIMIT, RateLimiter } from './rate-limiter'
import { authenticateAndParse, handleCatchError } from './request-utils'
import { ToolCatalog } from './tool-catalog'
import type { HonoCtx } from './types'

export class StreamableMcpHandler {
    private readonly dispatcher: McpDispatcher
    private readonly rateLimiter: RateLimiter

    constructor(
        redis: RedisLike,
        private readonly lifecycle: Lifecycle,
        options: McpDispatcherOptions = {}
    ) {
        this.dispatcher = new McpDispatcher(new ToolCatalog(), redis, options)
        this.rateLimiter = new RateLimiter(redis, [DEFAULT_BURST_LIMIT, DEFAULT_SUSTAINED_LIMIT])
    }

    async warmup(): Promise<void> {
        await this.dispatcher.warmup()
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

        // Classify the body before handing it to the dispatcher. A JSONRPC
        // *response* (no `method`, has `result`/`error`, has `id`) is the
        // client's reply to a server-initiated request (today: elicitation/
        // create) and is routed across pods via the session bus — it never
        // reaches the dispatcher. Everything else (requests / batches / no
        // body / parse errors) falls through unchanged.
        const classification = await classifyBody(c.req.raw)
        if (classification.kind === 'response') {
            try {
                await this.dispatcher.bus.deliver(classification.id, classification.payload)
            } catch (error) {
                return handleCatchError(error, auth.props)
            }
            return new Response(null, { status: 202 })
        }

        try {
            return await this.dispatcher.handleRequest(classification.req, auth.props)
        } catch (error) {
            return handleCatchError(error, auth.props)
        }
    }
}

type BodyClassification =
    | { kind: 'request'; req: Request }
    | { kind: 'response'; id: string | number; payload: unknown }

/**
 * Read the request body once and classify it. Returns a fresh `Request`
 * for the dispatcher to re-parse when the body is a request — we cloned
 * the original before reading, so the dispatcher's body parse stays
 * intact.
 *
 * The classifier is intentionally conservative: ambiguous shapes
 * (arrays, missing id, parse failures) fall through as `request` so
 * existing dispatcher behavior is unchanged.
 */
async function classifyBody(req: Request): Promise<BodyClassification> {
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
    const id = message.id
    const hasResult = 'result' in message
    const hasError = 'error' in message
    const hasMethod = 'method' in message
    const isResponse = !hasMethod && (hasResult || hasError) && (typeof id === 'string' || typeof id === 'number')
    if (!isResponse) {
        return { kind: 'request', req: rebuilt }
    }
    const payload = hasError ? { error: message.error } : message.result
    return { kind: 'response', id: id as string | number, payload }
}
