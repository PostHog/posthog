import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'

import type { Context } from '@/tools/types'

import { getManifest, getResourceText } from './kv-store'
import type { ContextMillManifest, ContextMillResource, ResourceManifest } from './manifest-types'

export { getManifest, getResourceText } from './kv-store'

export async function getPromptsFromManifest(): Promise<ResourceManifest['resources']['prompts']> {
    return []
}

/**
 * Register every context-mill resource with the MCP server using metadata only.
 * The read handler resolves the actual text lazily via {@link getResourceText},
 * which hits KV first and the origin only on miss — so `resources/list` costs
 * nothing extra in heap per DO, and `resources/read` pays a single KV lookup
 * for the requested URI rather than the whole catalog.
 */
export function registerResourceEntries(
    server: McpServer,
    env: { MCP_KV: KVNamespace | undefined },
    manifestVersion: string,
    entries: readonly ContextMillResource[]
): void {
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
                        text: await getResourceText(env, manifestVersion, entry),
                    },
                ],
            })
        )
    }
}

async function registerContextMillResources(server: McpServer, context: Context): Promise<void> {
    // The Cloudflare-generated `Env` doesn't list every binding (e.g. test-only
    // env vars like `TEST` or `POSTHOG_MCP_LOCAL_SKILLS_URL`), so reach for
    // them through an `unknown` cast rather than asserting the wrong shape.
    const envExtras = context.env as unknown as Record<string, string | undefined>
    if (envExtras.TEST === '1') {
        return
    }
    try {
        const localUrlRaw = envExtras.POSTHOG_MCP_LOCAL_SKILLS_URL
        const localUrl = localUrlRaw && localUrlRaw.trim() !== '' ? localUrlRaw : undefined
        const manifest = await getManifest(context.env, localUrl)
        registerResourceEntries(server, context.env, manifest.version, manifest.resources)
    } catch (error) {
        console.error('Failed to register context-mill resources:', error)
    }
}

export async function registerResources(server: McpServer, context: Context): Promise<void> {
    await registerContextMillResources(server, context)
}

export type { ContextMillManifest }
