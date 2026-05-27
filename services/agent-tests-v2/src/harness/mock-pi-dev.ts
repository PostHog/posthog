/* eslint-disable no-console */
/**
 * In-process mock pi.dev HTTP server for e2e tests.
 *
 * Speaks the same wire format as `HttpPiClient` (POST /v1/invoke). Routes by
 * the `model` field in the request body:
 *
 *   - `mock-echo`              — assistant text = last user message.
 *   - `mock-static:<text>`     — assistant text = URL-decoded <text>.
 *   - `mock-noop`              — empty assistant content, stop_reason=end_turn.
 *   - `mock-tool:<id>`         — emits a tool_use block calling <id>. On the
 *                                follow-up turn (after the runner sends back
 *                                tool_result), returns end_turn with a summary.
 *   - `mock-ask`               — emits a tool_use for meta.ask_for_input.v1.
 *   - `mock-end`               — emits a tool_use for meta.end_session.v1.
 *   - `mock-loop`              — every turn emits a tool_use for
 *                                posthog.query.v1 — for max_turns tests.
 *   - `mock-error:<spec>`      — returns an error response.
 *
 * Anything else falls through to `proxyUpstream` when configured — that's the
 * path real-inference tests take. With `PI_DEV_BASE_URL=https://api.pi.dev`
 * and `PI_DEV_API_KEY=…` env, an unknown model name proxies through.
 *
 * Every observed request is recorded; `requests()` returns them. `reset()`
 * clears between tests.
 */

import { type Server, createServer } from 'node:http'

export interface PiInvokeRequest {
    model: string
    system: string
    tools: Array<{ name: string; description: string; input_schema: Record<string, unknown> }>
    messages: PiMessage[]
    max_tokens?: number
}

export type PiMessage =
    | { role: 'user'; content: string | PiUserContentBlock[] }
    | { role: 'assistant'; content: PiAssistantContentBlock[] }

export type PiUserContentBlock =
    | { type: 'text'; text: string }
    | { type: 'tool_result'; tool_use_id: string; content: string; is_error?: boolean }

export type PiAssistantContentBlock =
    | { type: 'text'; text: string }
    | { type: 'tool_use'; id: string; name: string; input: unknown }

export interface PiInvokeResponse {
    stop_reason: 'end_turn' | 'tool_use' | 'max_tokens' | 'error'
    content: PiAssistantContentBlock[]
    usage: { input_tokens: number; output_tokens: number }
}

export interface MockPiHandle {
    readonly baseUrl: string
    readonly port: number
    onModel(model: string, response: PiInvokeResponse | PiResponseFn): void
    onRequest(handler: PiRequestHandler): void
    requests(): Promise<PiInvokeRequest[]>
    reset(): void
    close(): Promise<void>
}

export type PiResponseFn = (req: PiInvokeRequest) => PiInvokeResponse | Promise<PiInvokeResponse> | undefined
export type PiRequestHandler = (req: PiInvokeRequest) => PiInvokeResponse | Promise<PiInvokeResponse> | undefined

export interface StartMockPiOpts {
    port?: number
    proxyUpstream?: string
    proxyApiKey?: string
}

export async function startMockPi(opts: StartMockPiOpts = {}): Promise<MockPiHandle> {
    const handlers: PiRequestHandler[] = []
    const seen: PiInvokeRequest[] = []
    // mock-tool state — per-conversation turn counter so we can return
    // tool_use on turn N and end_turn on turn N+1.
    const conversationTurn = new Map<string, number>()

    const server: Server = createServer((req, res) => {
        if (req.url === '/__control__/requests' && req.method === 'GET') {
            res.writeHead(200, { 'content-type': 'application/json' })
            res.end(JSON.stringify(seen))
            return
        }
        if (req.url === '/__control__/reset' && req.method === 'POST') {
            handlers.length = 0
            seen.length = 0
            conversationTurn.clear()
            res.writeHead(204)
            res.end()
            return
        }
        if (req.method !== 'POST' || !req.url?.startsWith('/v1/invoke')) {
            res.writeHead(404, { 'content-type': 'application/json' })
            res.end(JSON.stringify({ error: { type: 'not_found', message: req.url } }))
            return
        }
        readBody(req)
            .then(async (raw) => {
                const parsed = JSON.parse(raw) as PiInvokeRequest
                seen.push(parsed)
                for (const handler of handlers) {
                    const r = await handler(parsed)
                    if (r) {
                        writeJson(res, 200, r)
                        return
                    }
                }
                const builtin = builtIn(parsed, conversationTurn)
                if (builtin) {
                    if ('__error' in builtin) {
                        writeJson(res, builtin.status, builtin.body)
                        return
                    }
                    writeJson(res, 200, builtin)
                    return
                }
                if (opts.proxyUpstream) {
                    await proxyRequest(opts.proxyUpstream, opts.proxyApiKey, raw, res)
                    return
                }
                writeJson(res, 400, {
                    error: {
                        type: 'invalid_request_error',
                        message: `[mock-pi-dev] no handler for model=${parsed.model} and no proxy upstream`,
                    },
                })
            })
            .catch((err: unknown) => {
                console.error('[mock-pi-dev] handler error', err)
                if (!res.headersSent) {
                    res.writeHead(500)
                }
                res.end()
            })
    })

    const port = opts.port ?? 0
    await new Promise<void>((resolve, reject) => {
        server.on('error', reject)
        server.listen(port, '127.0.0.1', () => {
            server.removeListener('error', reject)
            resolve()
        })
    })
    const addr = server.address()
    const boundPort = typeof addr === 'object' && addr ? addr.port : port
    server.unref()

    return {
        baseUrl: `http://127.0.0.1:${boundPort}`,
        port: boundPort,
        onRequest: (h) => {
            handlers.push(h)
        },
        onModel: (model, response) => {
            handlers.push((req) => {
                if (req.model !== model) {
                    return undefined
                }
                return typeof response === 'function' ? response(req) : response
            })
        },
        requests: () => Promise.resolve([...seen]),
        reset: () => {
            handlers.length = 0
            seen.length = 0
            conversationTurn.clear()
        },
        close: () =>
            new Promise<void>((resolve, reject) => {
                server.close((err) => (err ? reject(err) : resolve()))
            }),
    }
}

/* -------------------------------------------------------------------------- */

type BuiltInError = { __error: true; status: number; body: Record<string, unknown> }

/**
 * Built-in models. Drive behavior off "what was the last message?" rather than
 * turn counting, so they're robust to multi-session reuse and message
 * permutations.
 *
 * `lastMessageKind`:
 *   - "user_text"   → the most recent user message is plain text (or contains a text block).
 *                     Used as the trigger for an initial response (tool_use or text).
 *   - "tool_result" → the most recent user message is a tool_result (follow-up after a
 *                     tool dispatch). Used to emit a final end_turn summary.
 */
function builtIn(req: PiInvokeRequest, _turns: Map<string, number>): PiInvokeResponse | BuiltInError | null {
    const kind = lastMessageKind(req)
    const callIdSeed = req.messages.length // unique per turn within a conversation

    if (req.model === 'mock-echo') {
        return endTurn(lastUserText(req) ?? '')
    }
    if (req.model === 'mock-noop') {
        return endTurn('')
    }
    if (req.model.startsWith('mock-static:')) {
        return endTurn(decodeURIComponent(req.model.slice('mock-static:'.length)))
    }
    if (req.model === 'mock-ask') {
        if (kind === 'user_text') {
            return toolUse(callIdSeed, 'meta.ask_for_input.v1', { prompt: 'Continue?' })
        }
        return endTurn('resumed after input')
    }
    if (req.model === 'mock-end') {
        if (kind === 'user_text') {
            return toolUse(callIdSeed, 'meta.end_session.v1', { summary: 'all done' })
        }
        return endTurn('done')
    }
    if (req.model === 'mock-loop') {
        // Always emit a tool_use that the runner will dispatch + loop on. Used to
        // exercise max_turns ceilings.
        return toolUse(callIdSeed, 'posthog.query.v1', { query: 'select 1' })
    }
    if (req.model.startsWith('mock-tool:')) {
        const id = req.model.slice('mock-tool:'.length)
        if (kind === 'user_text') {
            return toolUse(callIdSeed, id, {})
        }
        return endTurn(`called ${id}`)
    }
    if (req.model.startsWith('mock-multi-tool:')) {
        // Format: mock-multi-tool:a,b,c — calls a, then b, then c, then ends.
        const ids = req.model.slice('mock-multi-tool:'.length).split(',')
        const toolResultsSoFar = countToolResults(req)
        if (toolResultsSoFar < ids.length) {
            return toolUse(callIdSeed, ids[toolResultsSoFar], {})
        }
        return endTurn(`called all: ${ids.join(',')}`)
    }
    if (req.model.startsWith('mock-error:')) {
        const spec = req.model.slice('mock-error:'.length)
        const status = Number(spec)
        if (Number.isFinite(status)) {
            return { __error: true, status, body: { error: { type: 'api_error', message: `mock-error ${status}` } } }
        }
        return { __error: true, status: 500, body: { error: { type: 'api_error', message: `mock-error ${spec}` } } }
    }
    return null
}

function toolUse(seed: number, name: string, input: unknown): PiInvokeResponse {
    return {
        stop_reason: 'tool_use',
        content: [{ type: 'tool_use', id: `tu_${seed}`, name, input }],
        usage: { input_tokens: 0, output_tokens: 0 },
    }
}

function lastMessageKind(req: PiInvokeRequest): 'user_text' | 'tool_result' | 'none' {
    for (let i = req.messages.length - 1; i >= 0; i--) {
        const m = req.messages[i]
        if (m.role !== 'user') {
            continue
        }
        if (typeof m.content === 'string') {
            return 'user_text'
        }
        for (const b of m.content) {
            if (b.type === 'tool_result') {
                return 'tool_result'
            }
            if (b.type === 'text') {
                return 'user_text'
            }
        }
    }
    return 'none'
}

function countToolResults(req: PiInvokeRequest): number {
    let n = 0
    for (const m of req.messages) {
        if (m.role !== 'user' || typeof m.content === 'string') {
            continue
        }
        for (const b of m.content) {
            if (b.type === 'tool_result') {
                n++
            }
        }
    }
    return n
}

function endTurn(text: string): PiInvokeResponse {
    return {
        stop_reason: 'end_turn',
        content: [{ type: 'text', text }],
        usage: { input_tokens: 0, output_tokens: 0 },
    }
}

function lastUserText(req: PiInvokeRequest): string | undefined {
    for (let i = req.messages.length - 1; i >= 0; i--) {
        const m = req.messages[i]
        if (m.role !== 'user') {
            continue
        }
        if (typeof m.content === 'string') {
            return m.content
        }
        if (Array.isArray(m.content)) {
            for (const block of m.content) {
                if (block && typeof block === 'object' && 'type' in block && block.type === 'text') {
                    return (block as { text: string }).text
                }
            }
        }
    }
    return undefined
}

/* -------------------------------------------------------------------------- */

async function proxyRequest(
    upstream: string,
    apiKey: string | undefined,
    rawBody: string,
    res: import('node:http').ServerResponse
): Promise<void> {
    const headers: Record<string, string> = { 'content-type': 'application/json' }
    if (apiKey) {
        headers.Authorization = `Bearer ${apiKey}`
    }
    const forwarded = await fetch(`${upstream}/v1/invoke`, {
        method: 'POST',
        headers,
        body: rawBody,
    })
    const text = await forwarded.text()
    res.writeHead(forwarded.status, { 'content-type': forwarded.headers.get('content-type') ?? 'application/json' })
    res.end(text)
}

function writeJson(res: import('node:http').ServerResponse, status: number, body: unknown): void {
    res.writeHead(status, { 'content-type': 'application/json' })
    res.end(JSON.stringify(body))
}

function readBody(req: import('node:http').IncomingMessage): Promise<string> {
    return new Promise((resolve, reject) => {
        let body = ''
        req.on('data', (chunk: Buffer) => {
            body += chunk.toString('utf-8')
        })
        req.on('end', () => resolve(body))
        req.on('error', reject)
    })
}
