import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { type Unzipped, strFromU8, unzipSync } from 'fflate'

import type { Context } from '@/tools/types'

import { loadContextMillManifest } from './manifest-loader'
import type { ContextMillManifest, ResourceManifest } from './manifest-types'

/**
 * URL to the context-mill resources ZIP (latest release)
 * Contains manifest.json + individual resource ZIPs
 */
export const CONTEXT_MILL_URL =
    'https://github.com/PostHog/context-mill/releases/latest/download/skills-mcp-resources.zip'

// Cache for context-mill resources ZIP contents
let cachedResources: Unzipped | null = null

/**
 * Fetches and caches the context-mill resources ZIP
 * For local testing, set POSTHOG_MCP_LOCAL_SKILLS_URL to a local HTTP URL
 */
async function fetchContextMillResources(context: Context): Promise<Unzipped> {
    // Check for local URL override in environment (for testing)
    const localUrlRaw = (context.env as Record<string, string | undefined>)?.POSTHOG_MCP_LOCAL_SKILLS_URL
    const localUrl = localUrlRaw && localUrlRaw.trim() !== '' ? localUrlRaw : undefined
    const url = localUrl || CONTEXT_MILL_URL

    // Skip cache for local development
    if (cachedResources && !localUrl) {
        return cachedResources
    }

    const response = await fetch(url, localUrl ? { cache: 'no-store' } : {})

    if (!response.ok) {
        throw new Error(`Failed to fetch context-mill resources from ${url}: ${response.statusText}`)
    }

    const arrayBuffer = await response.arrayBuffer()
    const uint8Array = new Uint8Array(arrayBuffer)
    const unzipped = unzipSync(uint8Array)

    // Only cache if not using local URL override
    if (!localUrl) {
        cachedResources = unzipped
    }

    return unzipped
}

/**
 * Load context-mill manifest from the resources archive
 */
function loadManifestFromArchive(archive: Unzipped): ContextMillManifest {
    const manifestData = archive['manifest.json']
    if (!manifestData) {
        throw new Error('manifest.json not found in archive')
    }
    const rawManifest = JSON.parse(strFromU8(manifestData))
    return loadContextMillManifest(rawManifest)
}

/**
 * Get prompts from the manifest
 * Currently returns empty - prompts will be migrated to context-mill resources
 */
export async function getPromptsFromManifest(): Promise<ResourceManifest['resources']['prompts']> {
    return []
}

/**
 * Register resources from the context-mill manifest.
 * The manifest fully defines each resource's MCP representation —
 * this function is a pure pass-through.
 */
async function registerContextMillResources(server: McpServer, context: Context): Promise<void> {
    try {
        const archive = await fetchContextMillResources(context)
        const manifest = loadManifestFromArchive(archive)

        for (const entry of manifest.resources) {
            // Validate archive file exists for non-inline resources
            if (entry.file) {
                const zipData = archive[entry.file]
                if (!zipData) {
                    console.warn(`Resource file "${entry.file}" not found in archive, skipping`)
                    continue
                }
            }

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
    } catch (error) {
        console.error('Failed to register context-mill resources:', error)
    }
}

/**
 * Registers all PostHog resources with the MCP server
 * Resources are loaded from context-mill's skills-mcp-resources.zip
 */
export async function registerResources(server: McpServer, context: Context): Promise<void> {
    await registerContextMillResources(server, context)
}
