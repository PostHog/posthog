import { ErrorCode, JSONRPC_VERSION } from '@modelcontextprotocol/sdk/types.js'

export const PROGRESS_HEARTBEAT_INTERVAL_MS = 15_000
const DEFAULT_PROGRESS_MESSAGE = 'Working'

export type ProgressToken = string | number

/** Per-call hooks that the dispatcher gives to a tool handler through `Context`. */
export type ToolCallHooks = {
    reportProgress?: (message: string) => void
    signal?: AbortSignal
}

export function readProgressToken(params: unknown): ProgressToken | undefined {
    if (!params || typeof params !== 'object') {
        return undefined
    }
    const meta = (params as { _meta?: unknown })._meta
    if (!meta || typeof meta !== 'object') {
        return undefined
    }
    const token = (meta as { progressToken?: unknown }).progressToken
    return typeof token === 'string' || typeof token === 'number' ? token : undefined
}

export function acceptsEventStream(headers: Headers): boolean {
    return (headers.get('accept') ?? '').toLowerCase().includes('text/event-stream')
}

export type ProgressStreamOptions = {
    requestId: string | number
    progressToken: ProgressToken
    headers: Record<string, string>
    requestSignal?: AbortSignal
    heartbeatIntervalMs?: number
    /** Runs the call and returns the final JSON-RPC response. */
    run: (hooks: Required<ToolCallHooks>) => Promise<unknown>
}

/**
 * Answers one JSON-RPC request with an SSE stream: progress notifications while the call runs,
 * then the final response as the last event. This is the streamable HTTP "SSE response to a POST".
 */
export function progressStreamResponse(options: ProgressStreamOptions): Response {
    const { requestId, progressToken, requestSignal, run } = options
    const heartbeatIntervalMs = options.heartbeatIntervalMs ?? PROGRESS_HEARTBEAT_INTERVAL_MS
    const encoder = new TextEncoder()
    const abort = new AbortController()

    let controller: ReadableStreamDefaultController<Uint8Array> | undefined
    let ended = false
    let progress = 0
    let lastMessage = DEFAULT_PROGRESS_MESSAGE
    let heartbeat: ReturnType<typeof setTimeout> | undefined

    function end(): void {
        ended = true
        clearTimeout(heartbeat)
        requestSignal?.removeEventListener('abort', onRequestAbort)
    }

    const send = (message: unknown): void => {
        if (ended || !controller) {
            return
        }
        try {
            controller.enqueue(encoder.encode(`event: message\ndata: ${JSON.stringify(message)}\n\n`))
        } catch {
            end()
        }
    }

    const scheduleHeartbeat = (): void => {
        clearTimeout(heartbeat)
        heartbeat = setTimeout(() => reportProgress(lastMessage), heartbeatIntervalMs)
    }

    const reportProgress = (message: string): void => {
        if (ended) {
            return
        }
        progress += 1
        lastMessage = message
        send({
            jsonrpc: JSONRPC_VERSION,
            method: 'notifications/progress',
            params: { progressToken, progress, message },
        })
        scheduleHeartbeat()
    }

    const onRequestAbort = (): void => {
        end()
        abort.abort(requestSignal?.reason)
    }

    const close = (): void => {
        end()
        try {
            controller?.close()
        } catch {
            // The client already cancelled the stream.
        }
    }

    const stream = new ReadableStream<Uint8Array>({
        start(streamController) {
            controller = streamController
            if (requestSignal?.aborted) {
                onRequestAbort()
            } else {
                requestSignal?.addEventListener('abort', onRequestAbort, { once: true })
                scheduleHeartbeat()
            }
            run({ reportProgress, signal: abort.signal }).then(
                (response) => {
                    send(response)
                    close()
                },
                (error: unknown) => {
                    console.error('[progress-stream] Internal error:', error)
                    send({
                        jsonrpc: JSONRPC_VERSION,
                        id: requestId,
                        error: { code: ErrorCode.InternalError, message: 'Internal error' },
                    })
                    close()
                }
            )
        },
        cancel(reason) {
            end()
            abort.abort(reason)
        },
    })

    return new Response(stream, {
        status: 200,
        headers: {
            ...options.headers,
            'Content-Type': 'text/event-stream',
            // Stops proxies from buffering or compressing the stream.
            'Cache-Control': 'no-cache, no-transform',
            'X-Accel-Buffering': 'no',
        },
    })
}
