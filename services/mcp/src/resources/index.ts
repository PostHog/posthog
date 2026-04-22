import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { type Unzipped, strFromU8, unzipSync } from 'fflate'

import { shouldIncludeByFlag } from '@/lib/feature-flag-gating'
import type { Context } from '@/tools/types'

import { loadContextMillManifest } from './manifest-loader'
import type { ContextMillManifest, ResourceManifest } from './manifest-types'

/**
 * URL to the context-mill resources ZIP (latest release)
 * Contains manifest.json + individual resource ZIPs
 */
export const CONTEXT_MILL_URL =
    'https://github.com/PostHog/context-mill/releases/latest/download/skills-mcp-resources.zip'

// Promise-typed so concurrent cold-path callers collapse onto one fetch.
let cachedResourcesPromise: Promise<Unzipped> | null = null

/**
 * Fetches and caches the context-mill resources ZIP
 * For local testing, set POSTHOG_MCP_LOCAL_SKILLS_URL to a local HTTP URL
 */
async function fetchContextMillResources(env: Context['env']): Promise<Unzipped> {
    const localUrlRaw = (env as Record<string, string | undefined>)?.POSTHOG_MCP_LOCAL_SKILLS_URL
    const localUrl = localUrlRaw && localUrlRaw.trim() !== '' ? localUrlRaw : undefined

    const doFetch = async (url: string, noStore: boolean): Promise<Unzipped> => {
        const response = await fetch(url, noStore ? { cache: 'no-store' } : {})
        if (!response.ok) {
            throw new Error(`Failed to fetch context-mill resources from ${url}: ${response.statusText}`)
        }
        return unzipSync(new Uint8Array(await response.arrayBuffer()))
    }

    if (localUrl) {
        return doFetch(localUrl, true)
    }
    if (!cachedResourcesPromise) {
        cachedResourcesPromise = doFetch(CONTEXT_MILL_URL, false).catch((err) => {
            cachedResourcesPromise = null
            throw err
        })
    }
    return cachedResourcesPromise
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
 * Resources declaring `feature_flag` are filtered via `shouldIncludeByFlag`.
 */
async function registerContextMillResources(
    server: McpServer,
    context: Context,
    featureFlags?: Record<string, boolean>
): Promise<void> {
    try {
        const archive = await fetchContextMillResources(context.env)
        const manifest = loadManifestFromArchive(archive)

        for (const entry of manifest.resources) {
            if (!shouldIncludeByFlag(entry, featureFlags)) {
                continue
            }

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

/** Distinct feature flag keys referenced by context-mill resources. */
export async function getRequiredSkillFlags(env: Context['env']): Promise<string[]> {
    try {
        const archive = await fetchContextMillResources(env)
        const manifest = loadManifestFromArchive(archive)
        const flags = new Set<string>()
        for (const entry of manifest.resources) {
            if (entry.feature_flag) {
                flags.add(entry.feature_flag)
            }
        }
        return [...flags]
    } catch {
        return []
    }
}

/**
 * Registers all PostHog resources with the MCP server
 * Resources are loaded from context-mill's skills-mcp-resources.zip
 */
export async function registerResources(
    server: McpServer,
    context: Context,
    featureFlags?: Record<string, boolean>
): Promise<void> {
    await registerContextMillResources(server, context, featureFlags)
}
