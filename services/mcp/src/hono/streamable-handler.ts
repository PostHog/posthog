import { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js'

import type { ContextMillResource } from '@/resources/manifest-types'

import type { Lifecycle } from './app'
import type { RedisLike } from './cache/RedisCache'
import { HonoMcpServer } from './mcp-server'
import { authenticateAndParse, handleCatchError, passThrough } from './request-utils'
import { ToolCatalog } from './tool-catalog'
import type { HonoCtx } from './types'

export class StreamableMcpHandler {
    private readonly catalog = new ToolCatalog()
    private _resourceEntries: readonly ContextMillResource[] = []

    constructor(
        private readonly redis: RedisLike,
        private readonly lifecycle: Lifecycle
    ) {}

    get resourceEntries(): readonly ContextMillResource[] {
        return this._resourceEntries
    }

    async warmup(): Promise<void> {
        await Promise.all([this.catalog.warmup(), this._warmupResources()])
    }

    private async _warmupResources(): Promise<void> {
        try {
            const { fetchContextMillResources, filterValidEntries, loadManifestFromArchive, clearResourceCache } =
                await import('@/resources/internals')
            const archive = await fetchContextMillResources()
            const manifest = loadManifestFromArchive(archive)
            this._resourceEntries = filterValidEntries(manifest.resources, archive)
            clearResourceCache()
        } catch (error) {
            console.error('[StreamableMcpHandler] Failed to pre-load context-mill resources:', error)
            this._resourceEntries = []
        }
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
            const mcpServer = new HonoMcpServer(this.redis, auth.props, {
                catalog: this.catalog,
                resourceEntries: this._resourceEntries,
            })
            await mcpServer.init()
            const transport = new WebStandardStreamableHTTPServerTransport({})
            await mcpServer.server.connect(transport)
            return passThrough(await transport.handleRequest(c.req.raw))
        } catch (error) {
            return handleCatchError(error, auth.props)
        }
    }
}
