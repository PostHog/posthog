import type { Lifecycle } from './app'
import type { RedisLike } from './cache/RedisCache'
import { McpDispatcher } from './dispatcher'
import { recordRateLimitBlock } from './rate-limit-telemetry'
import { buildRateLimitResponse, DEFAULT_BURST_LIMIT, DEFAULT_SUSTAINED_LIMIT, RateLimiter } from './rate-limiter'
import { authenticateAndParse, handleCatchError } from './request-utils'
import { ToolCatalog } from './tool-catalog'
import type { HonoCtx } from './types'

export class StreamableMcpHandler {
    private readonly dispatcher: McpDispatcher
    private readonly rateLimiter: RateLimiter

    constructor(
        private readonly redis: RedisLike,
        private readonly lifecycle: Lifecycle
    ) {
        this.dispatcher = new McpDispatcher(new ToolCatalog(), redis)
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
            void recordRateLimitBlock(this.redis, auth.props, rateLimit).catch(() => {})
            return buildRateLimitResponse(rateLimit)
        }

        try {
            return await this.dispatcher.handleRequest(c.req.raw, auth.props)
        } catch (error) {
            return handleCatchError(error, auth.props)
        }
    }
}
