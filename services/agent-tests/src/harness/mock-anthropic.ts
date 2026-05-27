/* eslint-disable no-console */
import { type Server, createServer } from 'node:http'

/**
 * In-process mock Anthropic Messages API server for e2e tests.
 *
 * The Claude Agent SDK POSTs to `<ANTHROPIC_BASE_URL>/v1/messages` with
 * streaming SSE responses. We listen on a port that the shared bins
 * are configured to reach (`ANTHROPIC_BASE_URL` is set at spawn time,
 * so the port is decided by globalSetup before tests run); the
 * test-worker process boots the actual server lazily on first use.
 *
 * Routing key is the model name in the request body:
 *
 *   - `mock-echo` — echoes the latest user message verbatim. Multi-turn
 *     conversations: each turn echoes the newest user input.
 *   - `mock-static:<text>` — always replies with `<text>` (URL-decoded).
 *   - `mock-noop` — empty assistant reply. Tests that don't care about
 *     content (parking semantics, etc.).
 *   - `mock-slow:<ms>` — sleeps `<ms>` ms then echoes the latest user
 *     message. Honours request aborts: when the SDK's AbortController
 *     fires (e.g. /cancel arrives), the client disconnects and the
 *     sleep cuts short. Use for "agent is working" tests.
 *   - `mock-error:<type>` — returns an Anthropic-shaped error response.
 *     `<type>` is `overloaded`, `invalid_request`, `authentication`,
 *     `permission`, `not_found`, `rate_limit`, `api`, or a numeric
 *     status code (`mock-error:503`). The SDK surfaces the error and
 *     the runner produces a `failed` outcome.
 *
 * Anything else falls through to `proxyUpstream` when set — lets
 * real-Claude tests coexist by forwarding `claude-*` model names to
 * `api.anthropic.com`. Without a proxy upstream, unmapped models get
 * a 400 with a clear error message so the failure is legible.
 *
 * Programmability — `onRequest` / `onModel` register additional
 * handlers ahead of the built-ins. Tests use this for bespoke
 * scripted responses. `reset()` clears scripts + recorded requests
 * between tests in the same suite.
 */
export interface MockAnthropicHandle {
    readonly baseUrl: string
    readonly port: number
    onRequest(handler: MockRequestHandler): void
    onModel(model: string, response: MockResponse | MockResponseFn): void
    /** Every `/v1/messages` POST observed since the last `reset()`. */
    requests(): MockAnthropicRequest[]
    /** Clear scripts + recorded requests. Built-in models stay available. */
    reset(): void
    /** Stop listening. The harness keeps the server alive for the suite. */
    close(): Promise<void>
}

export interface MockAnthropicRequest {
    model: string
    system?: unknown
    messages: Array<{ role: string; content: unknown }>
    raw: Record<string, unknown>
}

export interface MockResponse {
    text: string
    stopReason?: 'end_turn' | 'max_tokens' | 'stop_sequence'
}

export type MockResponseFn = (req: MockAnthropicRequest) => MockResponse | Promise<MockResponse> | undefined
export type MockRequestHandler = (req: MockAnthropicRequest) => MockResponse | Promise<MockResponse> | undefined

export interface StartMockAnthropicOptions {
    /**
     * Port to listen on. globalSetup picks one before the shared bins
     * boot and passes it to them via `ANTHROPIC_BASE_URL`; the test
     * worker boots the mock on the same port. Required — there is no
     * sensible default in this architecture.
     */
    port: number
    /**
     * URL to forward unmapped requests to. When set, any `/v1/messages`
     * POST that no handler matched is forwarded verbatim. Lets the mock
     * coexist with real-Claude tests — auth headers + body pass through
     * unchanged.
     */
    proxyUpstream?: string
}

export async function startMockAnthropic(options: StartMockAnthropicOptions): Promise<MockAnthropicHandle> {
    const handlers: MockRequestHandler[] = []
    const seen: MockAnthropicRequest[] = []

    const server: Server = createServer((req, res) => {
        if (req.method !== 'POST' || !req.url?.startsWith('/v1/messages')) {
            res.writeHead(404, { 'content-type': 'application/json' })
            res.end(JSON.stringify({ type: 'error', error: { type: 'not_found', message: req.url } }))
            return
        }
        readBody(req)
            .then(async (raw) => {
                const parsed = parseRequest(raw)
                seen.push(parsed)
                // Dispatch order:
                //   1. Scripted handlers (`onModel` / `onRequest`)
                //   2. Direct-write built-ins (`mock-slow`, `mock-error`) —
                //      these need req/res access for abort handling or
                //      non-200 status; they bypass the MockResponse shape.
                //   3. Text-only built-ins (`mock-echo`, `mock-static:`,
                //      `mock-noop`) via the streaming path.
                //   4. Proxy upstream, or 400 if none configured.
                let response: MockResponse | undefined
                for (const handler of handlers) {
                    const result = await handler(parsed)
                    if (result) {
                        response = result
                        break
                    }
                }
                if (response) {
                    writeStreamingResponse(res, parsed, response)
                    return
                }
                if (await builtInDirectWrite(parsed, req, res)) {
                    return
                }
                response = builtInTextResponse(parsed)
                if (response) {
                    writeStreamingResponse(res, parsed, response)
                    return
                }
                if (options.proxyUpstream) {
                    await proxyRequest(options.proxyUpstream, req, res, raw)
                    return
                }
                res.writeHead(400, { 'content-type': 'application/json' })
                res.end(
                    JSON.stringify({
                        type: 'error',
                        error: {
                            type: 'invalid_request_error',
                            message: `[mock-anthropic] no handler matched for model=${parsed.model} and no proxy upstream configured`,
                        },
                    })
                )
            })
            .catch((err: unknown) => {
                console.error('[mock-anthropic] handler error', err)
                if (!res.headersSent) {
                    res.writeHead(500)
                }
                res.end()
            })
    })

    await new Promise<void>((resolve, reject) => {
        server.on('error', reject)
        server.listen(options.port, '127.0.0.1', () => {
            server.removeListener('error', reject)
            resolve()
        })
    })

    // Allow the test process to exit when nothing else is running —
    // jest's worker shouldn't hang on the mock's listening port.
    server.unref()

    return {
        baseUrl: `http://127.0.0.1:${options.port}`,
        port: options.port,
        onRequest(handler) {
            handlers.push(handler)
        },
        onModel(model, response) {
            handlers.push((req) => {
                if (req.model !== model) {
                    return undefined
                }
                return typeof response === 'function' ? response(req) : response
            })
        },
        requests() {
            return [...seen]
        },
        reset() {
            handlers.length = 0
            seen.length = 0
        },
        close: () => new Promise<void>((resolve, reject) => server.close((err) => (err ? reject(err) : resolve()))),
    }
}

/* ===== built-in mock models ===== */

/**
 * Text-only built-ins that fit the `MockResponse` shape. Dispatched
 * through `writeStreamingResponse` for the canonical Anthropic
 * streaming wire format.
 */
function builtInTextResponse(req: MockAnthropicRequest): MockResponse | undefined {
    if (req.model === 'mock-echo') {
        return { text: lastUserText(req) ?? '', stopReason: 'end_turn' }
    }
    if (req.model === 'mock-noop') {
        return { text: '', stopReason: 'end_turn' }
    }
    const staticPrefix = 'mock-static:'
    if (req.model.startsWith(staticPrefix)) {
        return { text: decodeURIComponent(req.model.slice(staticPrefix.length)), stopReason: 'end_turn' }
    }
    return undefined
}

/**
 * Built-ins that need direct access to `req`/`res` — `mock-slow:<ms>`
 * (must await req-abort to short-circuit the sleep) and
 * `mock-error:<type>` (non-200 response, not streaming SSE). Returns
 * `true` if the request was handled here; `false` to fall through to
 * `builtInTextResponse`.
 */
async function builtInDirectWrite(
    req: MockAnthropicRequest,
    rawReq: import('node:http').IncomingMessage,
    res: import('node:http').ServerResponse
): Promise<boolean> {
    const slowPrefix = 'mock-slow:'
    if (req.model.startsWith(slowPrefix)) {
        const ms = Number(req.model.slice(slowPrefix.length))
        if (!Number.isFinite(ms) || ms < 0) {
            res.writeHead(400, { 'content-type': 'application/json' })
            res.end(
                JSON.stringify({
                    type: 'error',
                    error: {
                        type: 'invalid_request_error',
                        message: `[mock-anthropic] mock-slow needs a non-negative ms suffix (got ${JSON.stringify(req.model)})`,
                    },
                })
            )
            return true
        }
        // Sleep but bail early if the client (the SDK / runner) aborts
        // — e.g. the agent's AbortController fires when /cancel arrives.
        // Without this, /cancel during a `mock-slow:30000` would still
        // wait the full duration.
        const aborted = await sleepUntilAborted(ms, rawReq)
        if (aborted) {
            // Client gone; nothing to respond to. Mirror what real
            // Anthropic does on a closed connection — just end.
            res.end()
            return true
        }
        writeStreamingResponse(res, req, { text: lastUserText(req) ?? '', stopReason: 'end_turn' })
        return true
    }

    const errorPrefix = 'mock-error:'
    if (req.model.startsWith(errorPrefix)) {
        const spec = req.model.slice(errorPrefix.length)
        const { status, body } = anthropicErrorFor(spec)
        res.writeHead(status, { 'content-type': 'application/json' })
        res.end(JSON.stringify(body))
        return true
    }

    return false
}

/**
 * Resolve a `mock-error:<spec>` suffix to a status code + Anthropic
 * error body. `<spec>` is either a known error type
 * (`overloaded`, `invalid_request`, `authentication`, `permission`,
 * `not_found`, `rate_limit`, `api`) or a numeric HTTP status. The
 * body matches Anthropic's documented shape so the SDK's error
 * surface stays consistent.
 */
function anthropicErrorFor(spec: string): { status: number; body: Record<string, unknown> } {
    const knownTypes: Record<string, { status: number; type: string; message: string }> = {
        invalid_request: { status: 400, type: 'invalid_request_error', message: 'Invalid request' },
        authentication: { status: 401, type: 'authentication_error', message: 'Authentication failed' },
        permission: { status: 403, type: 'permission_error', message: 'Permission denied' },
        not_found: { status: 404, type: 'not_found_error', message: 'Not found' },
        rate_limit: { status: 429, type: 'rate_limit_error', message: 'Rate limit exceeded' },
        api: { status: 500, type: 'api_error', message: 'Internal server error' },
        overloaded: { status: 529, type: 'overloaded_error', message: 'Overloaded' },
    }
    const entry = knownTypes[spec]
    if (entry) {
        return {
            status: entry.status,
            body: { type: 'error', error: { type: entry.type, message: entry.message } },
        }
    }
    const status = Number(spec)
    if (Number.isFinite(status) && status >= 400 && status < 600) {
        return {
            status,
            body: { type: 'error', error: { type: 'api_error', message: `mock-error: HTTP ${status}` } },
        }
    }
    return {
        status: 400,
        body: {
            type: 'error',
            error: {
                type: 'invalid_request_error',
                message: `[mock-anthropic] unknown mock-error spec: ${JSON.stringify(spec)}`,
            },
        },
    }
}

/**
 * Sleep `ms` milliseconds OR until the request fires `close` (i.e. the
 * client aborted). Returns `true` if the abort fired, `false` if the
 * sleep completed normally. Used by `mock-slow` so /cancel doesn't
 * pay the full sleep budget.
 */
function sleepUntilAborted(ms: number, req: import('node:http').IncomingMessage): Promise<boolean> {
    if (req.destroyed) {
        return Promise.resolve(true)
    }
    return new Promise<boolean>((resolve) => {
        const timer = setTimeout(() => {
            req.removeListener('close', onClose)
            resolve(false)
        }, ms)
        const onClose = (): void => {
            clearTimeout(timer)
            resolve(true)
        }
        req.once('close', onClose)
    })
}

function lastUserText(req: MockAnthropicRequest): string | undefined {
    // Walk tail-first; for each user message, extract the first text
    // block whose content survives `stripSdkBoilerplate`. The Claude
    // Agent SDK injects `<system-reminder>` MCP boilerplate (and other
    // tagged sections) as user-role messages alongside the actual
    // prompt; without stripping them, mock-echo ends up echoing
    // server-config blurbs instead of what the user typed.
    for (let i = req.messages.length - 1; i >= 0; i--) {
        const m = req.messages[i]
        if (m.role !== 'user') {
            continue
        }
        if (typeof m.content === 'string') {
            const cleaned = stripSdkBoilerplate(m.content)
            if (cleaned) {
                return cleaned
            }
            continue
        }
        if (Array.isArray(m.content)) {
            for (const block of m.content) {
                if (block && typeof block === 'object') {
                    const b = block as Record<string, unknown>
                    if (b.type === 'text' && typeof b.text === 'string') {
                        const cleaned = stripSdkBoilerplate(b.text)
                        if (cleaned) {
                            return cleaned
                        }
                    }
                }
            }
        }
    }
    return undefined
}

/**
 * Remove `<system-reminder>…</system-reminder>` and similar
 * SDK-injected wrapper blocks from a user message; trim whitespace.
 * Returns the empty string when nothing real is left — caller treats
 * that as "skip this message and try the next."
 */
function stripSdkBoilerplate(text: string): string {
    return text
        .replace(/<system-reminder>[\s\S]*?<\/system-reminder>/g, '')
        .replace(/<system>[\s\S]*?<\/system>/g, '')
        .trim()
}

/* ===== streaming wire format ===== */

function writeStreamingResponse(
    res: import('node:http').ServerResponse,
    req: MockAnthropicRequest,
    response: MockResponse
): void {
    res.writeHead(200, {
        'content-type': 'text/event-stream',
        'cache-control': 'no-cache',
        connection: 'keep-alive',
    })

    const messageId = `msg_${Math.random().toString(36).slice(2, 14)}`
    const stopReason = response.stopReason ?? 'end_turn'

    sse(res, 'message_start', {
        type: 'message_start',
        message: {
            id: messageId,
            type: 'message',
            role: 'assistant',
            model: req.model,
            content: [],
            stop_reason: null,
            stop_sequence: null,
            usage: { input_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0, output_tokens: 0 },
        },
    })
    sse(res, 'content_block_start', {
        type: 'content_block_start',
        index: 0,
        content_block: { type: 'text', text: '' },
    })
    for (const chunk of chunkText(response.text, 3)) {
        sse(res, 'content_block_delta', {
            type: 'content_block_delta',
            index: 0,
            delta: { type: 'text_delta', text: chunk },
        })
    }
    sse(res, 'content_block_stop', { type: 'content_block_stop', index: 0 })
    sse(res, 'message_delta', {
        type: 'message_delta',
        delta: { stop_reason: stopReason, stop_sequence: null },
        usage: { output_tokens: response.text.length },
    })
    sse(res, 'message_stop', { type: 'message_stop' })
    res.end()
}

function sse(res: import('node:http').ServerResponse, event: string, data: unknown): void {
    res.write(`event: ${event}\n`)
    res.write(`data: ${JSON.stringify(data)}\n\n`)
}

function chunkText(text: string, parts: number): string[] {
    if (!text) {
        return ['']
    }
    const len = Math.ceil(text.length / parts) || 1
    const out: string[] = []
    for (let i = 0; i < text.length; i += len) {
        out.push(text.slice(i, i + len))
    }
    return out
}

/* ===== proxy ===== */

async function proxyRequest(
    upstream: string,
    req: import('node:http').IncomingMessage,
    res: import('node:http').ServerResponse,
    body: string
): Promise<void> {
    const url = new URL(`/v1/messages${req.url?.slice('/v1/messages'.length) ?? ''}`, upstream)
    const forwarded = await fetch(url, {
        method: 'POST',
        headers: pickForwardableHeaders(req.headers),
        body,
    })
    const headers: Record<string, string> = {}
    forwarded.headers.forEach((value, key) => {
        headers[key] = value
    })
    res.writeHead(forwarded.status, headers)
    if (!forwarded.body) {
        res.end()
        return
    }
    const reader = forwarded.body.getReader()
    while (true) {
        const { done, value } = await reader.read()
        if (done) {
            break
        }
        res.write(value)
    }
    res.end()
}

function pickForwardableHeaders(headers: import('node:http').IncomingHttpHeaders): Record<string, string> {
    const out: Record<string, string> = {}
    for (const [key, value] of Object.entries(headers)) {
        if (value === undefined) {
            continue
        }
        const lower = key.toLowerCase()
        if (lower === 'host' || lower === 'content-length' || lower === 'connection') {
            continue
        }
        out[key] = Array.isArray(value) ? value.join(', ') : value
    }
    return out
}

/* ===== internals ===== */

async function readBody(req: import('node:http').IncomingMessage): Promise<string> {
    return new Promise((resolve, reject) => {
        let body = ''
        req.on('data', (chunk: Buffer) => {
            body += chunk.toString('utf8')
        })
        req.on('end', () => resolve(body))
        req.on('error', reject)
    })
}

function parseRequest(raw: string): MockAnthropicRequest {
    const parsed = JSON.parse(raw) as Record<string, unknown>
    return {
        model: typeof parsed.model === 'string' ? parsed.model : '',
        system: parsed.system,
        messages: Array.isArray(parsed.messages) ? (parsed.messages as MockAnthropicRequest['messages']) : [],
        raw: parsed,
    }
}
