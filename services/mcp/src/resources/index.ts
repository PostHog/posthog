import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { ReadResourceRequestSchema, type ReadResourceResult } from '@modelcontextprotocol/sdk/types.js'

import type { Context } from '@/tools/types'

import type { ContextMillResource, ResourceManifest } from './manifest-types'
import { fetchContextMillResources, filterValidEntries, loadManifestFromArchive } from './internals'

export { fetchContextMillResources, filterValidEntries, loadManifestFromArchive }

export async function getPromptsFromManifest(): Promise<ResourceManifest['resources']['prompts']> {
    return []
}

export function registerResourceEntries(server: McpServer, entries: readonly ContextMillResource[]): void {
    for (const entry of entries) {
        server.registerResource(
            entry.name,
            entry.uri,
            {
                mimeType: entry.resource.mimeType,
                description: entry.resource.description,
            },
            async (uri) => ({
                contents: [
                    {
                        uri: uri.toString(),
                        mimeType: entry.resource.mimeType,
                        text: entry.resource.text,
                    },
                ],
            })
        )
    }
}

async function registerContextMillResources(server: McpServer, context: Context): Promise<void> {
    if ((context.env as Record<string, string | undefined>)?.TEST === '1') {
        return
    }
    try {
        const localUrlRaw = (context.env as Record<string, string | undefined>)?.POSTHOG_MCP_LOCAL_SKILLS_URL
        const localUrl = localUrlRaw && localUrlRaw.trim() !== '' ? localUrlRaw : undefined
        const archive = await fetchContextMillResources(localUrl)
        const manifest = loadManifestFromArchive(archive)

        registerResourceEntries(server, filterValidEntries(manifest.resources, archive))
    } catch (error) {
        console.error('Failed to register context-mill resources:', error)
    }
}

export async function registerResources(server: McpServer, context: Context): Promise<void> {
    await registerContextMillResources(server, context)
}

/**
 * Override `resources/read` so unknown URIs resolve to empty contents instead
 * of an MCP "Resource not found" error. The Hono dispatcher already does this
 * via its own catalog; mirror that on Cloudflare Workers so both transports
 * agree on the protocol contract.
 *
 * Must be called after every `server.registerResource(...)` — once installed,
 * the SDK's `assertCanSetRequestHandler` would reject any subsequent
 * registration that tries to overwrite the same handler.
 */
export function installResourceReadFallback(server: McpServer): void {
    type Handler = (request: unknown, extra: unknown) => Promise<unknown>
    type InternalServer = { _requestHandlers: Map<string, Handler> }
    const handlers = (server.server as unknown as InternalServer)._requestHandlers
    const original = handlers.get('resources/read')
    if (!original) {
        // No resources were ever registered — install a pure empty handler.
        server.server.registerCapabilities({ resources: { listChanged: false } })
        server.server.setRequestHandler(
            ReadResourceRequestSchema,
            async (): Promise<ReadResourceResult> => ({ contents: [] })
        )
        return
    }
    handlers.set('resources/read', async (request, extra) => {
        try {
            return await original(request, extra)
        } catch (error: unknown) {
            const code = (error as { code?: number })?.code
            const message = (error as { message?: string })?.message ?? ''
            if (code === -32602 || /not found/i.test(message)) {
                return { contents: [] }
            }
            throw error
        }
    })
}
