import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'

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
