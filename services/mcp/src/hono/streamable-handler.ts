import type { Lifecycle } from './app'
import type { RedisLike } from './cache/RedisCache'
import { McpDispatcher } from './dispatcher'
import { authenticateAndParse, handleCatchError } from './request-utils'
import { ToolCatalog } from './tool-catalog'
import type { HonoCtx } from './types'

export class StreamableMcpHandler {
    private readonly dispatcher: McpDispatcher

    constructor(redis: RedisLike, private readonly lifecycle: Lifecycle) {
        this.dispatcher = new McpDispatcher(new ToolCatalog(), redis)
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

        try {
            return await this.dispatcher.handleRequest(c.req.raw, auth.props)
        } catch (error) {
            return handleCatchError(error, auth.props)
        }
    }
}
