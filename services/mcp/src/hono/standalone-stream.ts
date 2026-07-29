import { randomUUID } from 'node:crypto'

import { MCPClientProfile } from '@/lib/client-detection'
import type { RequestProperties } from '@/lib/request-properties'

import type { Lifecycle } from './app'

/**
 * Streamable HTTP standalone SSE stream (`GET /mcp`).
 *
 * This server never initiates messages toward the client — every capability is
 * advertised `listChanged: false` — so the spec's 405 answer is correct and stays
 * the default. Only sessions opened by a client that can't get past the handshake
 * without the stream (see `needsStandaloneSseStream`) get one, which keeps the
 * connection footprint unchanged for every other client.
 *
 * Whether a session qualifies is encoded in the session id minted on
 * `initialize`, because the standalone GET has no body: the client echoes the id
 * back in `Mcp-Session-Id`, so the prefix travels with it and works across pods
 * without any shared state.
 */
const STANDALONE_SSE_SESSION_PREFIX = 'sse-'

/** SSE comment line. Ignored by parsers, so it carries no JSON-RPC meaning. */
const KEEPALIVE_FRAME = ': ping\n\n'
const KEEPALIVE_INTERVAL_MS = 10_000
/**
 * Close well inside the shutdown drain budget so an idle stream can't hold a
 * draining pod open; clients reopen the stream on their own.
 */
const MAX_STREAM_LIFETIME_MS = 240_000

export function mintSessionId(props: RequestProperties): string {
    const profile = new MCPClientProfile({
        clientName: props.mcpClientName,
        vendorClient: props.mcpVendorClient,
        userAgent: props.clientUserAgent,
    })
    return profile.needsStandaloneSseStream() ? `${STANDALONE_SSE_SESSION_PREFIX}${randomUUID()}` : randomUUID()
}

/**
 * Whether to serve `GET /mcp` for this request. The session marker is the primary
 * signal; the User-Agent is a fallback for a client that opens the stream without
 * echoing the session id.
 */
export function wantsStandaloneSseStream(props: RequestProperties): boolean {
    if (props.mcpSessionId?.startsWith(STANDALONE_SSE_SESSION_PREFIX)) {
        return true
    }
    return new MCPClientProfile({ userAgent: props.clientUserAgent }).needsStandaloneSseStream()
}

/**
 * An idle, keepalive-only SSE stream. The first frame is written immediately —
 * clients that block until the stream produces something would otherwise time out
 * waiting on a stream that, by design, has nothing to say.
 */
export function createStandaloneSseResponse(signal: AbortSignal, lifecycle: Lifecycle): Response {
    const encoder = new TextEncoder()
    let keepalive: ReturnType<typeof setInterval> | undefined
    let lifetime: ReturnType<typeof setTimeout> | undefined
    let onAbort: (() => void) | undefined

    const stream = new ReadableStream<Uint8Array>({
        start(controller) {
            const finish = (): void => {
                if (keepalive !== undefined) {
                    clearInterval(keepalive)
                    keepalive = undefined
                }
                if (lifetime !== undefined) {
                    clearTimeout(lifetime)
                    lifetime = undefined
                }
                if (onAbort) {
                    signal.removeEventListener('abort', onAbort)
                    onAbort = undefined
                }
                try {
                    controller.close()
                } catch {
                    // Already closed by the peer disconnecting.
                }
            }

            controller.enqueue(encoder.encode(KEEPALIVE_FRAME))

            keepalive = setInterval(() => {
                if (lifecycle.shuttingDown) {
                    finish()
                    return
                }
                try {
                    controller.enqueue(encoder.encode(KEEPALIVE_FRAME))
                } catch {
                    finish()
                }
            }, KEEPALIVE_INTERVAL_MS)
            keepalive.unref?.()

            lifetime = setTimeout(finish, MAX_STREAM_LIFETIME_MS)
            lifetime.unref?.()

            onAbort = finish
            signal.addEventListener('abort', onAbort, { once: true })
        },
        cancel() {
            if (keepalive !== undefined) {
                clearInterval(keepalive)
            }
            if (lifetime !== undefined) {
                clearTimeout(lifetime)
            }
        },
    })

    return new Response(stream, {
        status: 200,
        headers: {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache, no-transform',
            Connection: 'keep-alive',
            // Tells proxies that buffer by default not to hold the frames back.
            'X-Accel-Buffering': 'no',
        },
    })
}
