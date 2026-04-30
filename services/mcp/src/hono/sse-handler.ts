import type { RequestProperties } from '@/lib/request-properties'

import type { RedisLike } from './cache/RedisCache'
import type { HonoMcpServer } from './mcp-server'
import { authenticateAndParse, bootMcpServer, handleCatchError } from './request-utils'
import type { SessionStore } from './session-store'
import { createSSEResponseAdapter, handleSSEPostMessage } from './sse-adapter'
import type { HonoCtx } from './types'

/**
 * SSE transport (`/sse`). Two flows:
 *   GET   – open the SSE event stream; the response body is the channel the
 *           server uses to push events to the client.
 *   POST  – client→server messages, routed to the existing SSE session by id.
 */
export class SseMcpHandler {
    constructor(private readonly redis: RedisLike, private readonly store: SessionStore) {}

    fetch = async (c: HonoCtx): Promise<Response> => {
        const auth = await authenticateAndParse(c, 'sse')
        if ('error' in auth) {
            return auth.error
        }
        const { props } = auth

        try {
            switch (c.req.method) {
                case 'GET':
                    return await this.openStream(c, props)
                case 'POST':
                    return await this.handlePost(c, props)
                default:
                    return new Response('Method not allowed', { status: 405 })
            }
        } catch (error) {
            return handleCatchError(error, props)
        }
    }

    private async openStream(_c: HonoCtx, props: RequestProperties): Promise<Response> {
        if (!this.store.reserve()) {
            return new Response('Too many active sessions', { status: 503 })
        }
        const mcpServer = await bootMcpServer(this.redis, props)
        const stream = new ReadableStream({
            start: (controller) => this.connectSseTransport(controller, mcpServer, props.userHash),
        })
        return new Response(stream, {
            headers: {
                'Content-Type': 'text/event-stream',
                'Cache-Control': 'no-cache',
                Connection: 'keep-alive',
            },
        })
    }

    // SSEServerTransport generates its own sessionId in its constructor and
    // advertises it to the client via the initial `endpoint` event. The client
    // then POSTs back with that id, so the registry MUST be keyed on
    // `transport.sessionId` — keying on a separately generated uuid produces
    // a 404 on every POST.
    private connectSseTransport(
        controller: ReadableStreamDefaultController<Uint8Array>,
        mcpServer: HonoMcpServer,
        tokenHash: string
    ): void {
        let sessionId: string | undefined
        const { transport } = createSSEResponseAdapter(controller, () => {
            if (sessionId) {
                this.store.sse.delete(sessionId)
            }
        })
        sessionId = transport.sessionId
        this.store.sse.set(sessionId, { transport, server: mcpServer }, tokenHash)
        // server.connect() calls transport.start() internally, which writes
        // the initial `endpoint` SSE event into the stream we just opened.
        void mcpServer.server.connect(transport)
    }

    private async handlePost(c: HonoCtx, props: RequestProperties): Promise<Response> {
        const sessionId = new URL(c.req.url).searchParams.get('sessionId')
        if (!sessionId) {
            return new Response('Missing sessionId', { status: 400 })
        }
        const session = this.store.sse.get(sessionId, props.userHash)
        if (!session) {
            return new Response('Session not found', { status: 404 })
        }
        const body = await c.req.json()
        await handleSSEPostMessage(session.transport, c.req.raw.headers, c.req.url, body)
        return new Response('Accepted', { status: 202 })
    }
}
