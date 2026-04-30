import { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js'
import { v4 as uuidv4 } from 'uuid'

import type { RequestProperties } from '@/lib/request-properties'

import type { RedisLike } from './cache/RedisCache'
import { authenticateAndParse, bootMcpServer, handleCatchError, passThrough } from './request-utils'
import type { SessionStore } from './session-store'
import type { HonoCtx } from './types'

/**
 * Streamable HTTP transport (`/mcp`). Each request method has its own dispatch:
 *   POST    – existing session → forward; otherwise spin up a new one.
 *   GET     – long-poll the existing session's stream (no session → 405).
 *   DELETE  – shut down the session via its transport, then evict.
 */
export class StreamableMcpHandler {
    constructor(private readonly redis: RedisLike, private readonly store: SessionStore) {}

    fetch = async (c: HonoCtx): Promise<Response> => {
        const auth = await authenticateAndParse(c, 'streamable-http')
        if ('error' in auth) {
            return auth.error
        }
        const { props } = auth
        const sessionId = c.req.header('mcp-session-id')

        try {
            switch (c.req.method) {
                case 'POST':
                    return await this.handlePost(c, props, sessionId)
                case 'GET':
                    return await this.handleGet(c, props, sessionId)
                case 'DELETE':
                    return await this.handleDelete(c, props, sessionId)
                default:
                    return new Response('Method not allowed', { status: 405 })
            }
        } catch (error) {
            return handleCatchError(error, props)
        }
    }

    private async handlePost(c: HonoCtx, props: RequestProperties, sessionId: string | undefined): Promise<Response> {
        if (sessionId) {
            const transport = this.store.streamable.get(sessionId, props.userHash)
            if (transport) {
                return passThrough(await transport.handleRequest(c.req.raw))
            }
        }
        return this.openSession(c, props)
    }

    private async handleGet(c: HonoCtx, props: RequestProperties, sessionId: string | undefined): Promise<Response> {
        const transport = sessionId ? this.store.streamable.get(sessionId, props.userHash) : undefined
        if (!transport) {
            return new Response('Method not allowed', { status: 405 })
        }
        return passThrough(await transport.handleRequest(c.req.raw))
    }

    private async handleDelete(c: HonoCtx, props: RequestProperties, sessionId: string | undefined): Promise<Response> {
        if (!sessionId) {
            return new Response('Session not found', { status: 404 })
        }
        const transport = this.store.streamable.get(sessionId, props.userHash)
        if (!transport) {
            return new Response('Session not found', { status: 404 })
        }
        await transport.handleRequest(c.req.raw)
        this.store.streamable.delete(sessionId)
        return new Response(null, { status: 200 })
    }

    private async openSession(c: HonoCtx, props: RequestProperties): Promise<Response> {
        if (!this.store.reserve()) {
            return new Response('Too many active sessions', { status: 503 })
        }
        const mcpServer = await bootMcpServer(this.redis, props)
        const transport = new WebStandardStreamableHTTPServerTransport({
            sessionIdGenerator: () => uuidv4(),
            onsessioninitialized: (sid) => this.store.streamable.set(sid, transport, props.userHash),
        })
        transport.onclose = () => {
            if (transport.sessionId) {
                this.store.streamable.delete(transport.sessionId)
            }
        }
        await mcpServer.server.connect(transport)
        return passThrough(await transport.handleRequest(c.req.raw))
    }
}
