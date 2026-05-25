/**
 * Build a streaming HTTP Response that writes JSONRPC messages as
 * Server-Sent Events.
 *
 * Used by the Hono dispatcher when a tool handler invokes `context.elicit()`:
 * the dispatcher upgrades the in-flight POST response from plain JSON to
 * SSE so it can push the server-initiated `elicitation/create` request to
 * the client *before* the eventual tool result lands on the same stream.
 *
 * Wire format follows the MCP Streamable HTTP transport convention — each
 * message is an SSE `event: message` with the JSON-stringified JSONRPC body
 * in `data:`. Clients that implement the MCP spec (Inspector, Claude Code,
 * Cursor, …) parse this shape natively.
 *
 * The returned Response body is a `ReadableStream` and is consumed lazily,
 * so the dispatcher's tool handler can keep running between `write()`
 * calls. The stream is held open until `close()` is invoked.
 */

export interface SseWriter {
    /** Push one JSONRPC message to the stream. */
    write(message: unknown): Promise<void>
    /** Close the stream. Subsequent writes are no-ops. */
    close(): Promise<void>
    /** True once `close()` has been called or the underlying stream errored. */
    readonly closed: boolean
}

export interface SseResponseHandle {
    response: Response
    writer: SseWriter
}

/**
 * Build an SSE-encoded Response and return both the Response object and a
 * `SseWriter` for emitting messages.
 *
 * The Response should be returned from the request handler synchronously
 * (or with a small awaitable wrapper) so the runtime begins flushing
 * headers to the client immediately. The writer can be used asynchronously
 * for as long as the underlying stream is open.
 */
export function createSseResponse(): SseResponseHandle {
    const encoder = new TextEncoder()
    let controller: ReadableStreamDefaultController<Uint8Array> | undefined
    let closed = false
    let readyResolve!: () => void
    const ready = new Promise<void>((resolve) => {
        // Resolved by the start() callback below. Until that runs the
        // controller is undefined; any write() that races ahead will await
        // this promise rather than touch a null controller.
        readyResolve = resolve
    })

    const stream = new ReadableStream<Uint8Array>({
        start(c) {
            controller = c
            readyResolve()
        },
        cancel() {
            // Client disconnected — mark as closed so subsequent writes
            // become no-ops instead of throwing.
            closed = true
        },
    })

    const writer: SseWriter = {
        get closed(): boolean {
            return closed
        },
        async write(message: unknown): Promise<void> {
            if (closed) {
                return
            }
            await ready
            if (closed || controller === undefined) {
                return
            }
            const payload = `event: message\ndata: ${JSON.stringify(message)}\n\n`
            try {
                controller.enqueue(encoder.encode(payload))
            } catch {
                // The stream was closed (e.g. client disconnect) between
                // our check and enqueue. Treat as closed; the dispatcher's
                // outer handler will observe via subsequent writes or
                // abort signals.
                closed = true
            }
        },
        async close(): Promise<void> {
            if (closed) {
                return
            }
            closed = true
            await ready
            try {
                controller?.close()
            } catch {
                /* already closed */
            }
        },
    }

    const response = new Response(stream, {
        status: 200,
        headers: {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache, no-transform',
            Connection: 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    })

    return { response, writer }
}
