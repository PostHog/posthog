import { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js'

import type { Lifecycle } from './app'
import type { RedisLike } from './cache/RedisCache'
import { HonoMcpServer } from './mcp-server'
import { authenticateAndParse, handleCatchError, passThrough } from './request-utils'
import type { HonoCtx } from './types'

export class StreamableMcpHandler {
    constructor(
        private readonly redis: RedisLike,
        private readonly lifecycle: Lifecycle
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

        try {
            const mcpServer = new HonoMcpServer(this.redis, auth.props)
            await mcpServer.init()
            const transport = new WebStandardStreamableHTTPServerTransport({})
            await mcpServer.server.connect(transport)
            return passThrough(await transport.handleRequest(c.req.raw))
        } catch (error) {
            return handleCatchError(error, auth.props)
        }
    }
}
