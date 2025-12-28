import { type McpServer, ResourceTemplate } from '@modelcontextprotocol/sdk/server/mcp.js'
import { type Unzipped, strFromU8, unzipSync } from 'fflate'

import type { Context } from '@/tools/types'

import { loadManifest } from './manifest-loader'
import type { ResourceManifest } from './manifest-types'

/**
 * URL to the PostHog examples markdown artifact (latest release)
 * This ZIP contains examples, workflows, and the manifest with all resource URIs
 */
const EXAMPLES_MARKDOWN_URL = 'https://github.com/PostHog/examples/releases/latest/download/examples-mcp-resources.zip'

// Cache for the examples markdown ZIP contents (includes both examples and prompts)
let cachedExamplesMarkdown: Unzipped | null = null

/**
 * Fetches documentation content from a URL with error handling
 */
async function fetchDocumentation(url: string): Promise<string> {
    const response = await fetch(url)

    if (!response.ok) {
        throw new Error(`Failed to fetch documentation: ${response.statusText}`)
    }

    return response.text()
}

/**
 * Fetches and caches the examples markdown ZIP at startup
 * This ZIP contains both example projects and LLM prompts
 *
 * For local testing, set POSTHOG_MCP_LOCAL_EXAMPLES_URL to a local HTTP URL
 * When using a local URL override, caching is disabled for development workflow
 */
async function fetchExamplesMarkdown(context: Context): Promise<Unzipped> {
    // Check for local URL override in environment (for testing)
    // @ts-expect-error - env might have this property
    const localUrlRaw = context.env?.POSTHOG_MCP_LOCAL_EXAMPLES_URL
    // Treat empty string as undefined to avoid issues with default values
    const localUrl = localUrlRaw && localUrlRaw.trim() !== '' ? localUrlRaw : undefined
    const url = localUrl || EXAMPLES_MARKDOWN_URL

    // If using local URL override, skip cache to enable hot-reloading during development
    // Otherwise, use cache for production
    if (cachedExamplesMarkdown && !localUrl) {
        return cachedExamplesMarkdown
    }

    const response = await fetch(url, localUrl ? { cache: 'no-store' } : {})

    if (!response.ok) {
        throw new Error(`Failed to fetch examples markdown from ${url}: ${response.statusText}`)
    }

    const arrayBuffer = await response.arrayBuffer()
    const uint8Array = new Uint8Array(arrayBuffer)
    const unzipped = unzipSync(uint8Array)

    // Only cache if not using local URL override
    if (!localUrl) {
        cachedExamplesMarkdown = unzipped
    }

    return unzipped
}

/**
 * Get prompts from the manifest
 * This allows the prompts module to register them
 */
export async function getPromptsFromManifest(context: Context): Promise<ResourceManifest['resources']['prompts']> {
    try {
        const archive = await fetchExamplesMarkdown(context)
        const manifest = loadManifest(archive)
        return manifest.resources.prompts
    } catch (error) {
        console.error('Failed to load prompts from manifest:', error)
        return []
    }
}

/**
 * Register resources from the manifest
 * Pure reflection - just register what the manifest tells us
 */
function registerManifestResources(server: McpServer, manifest: ResourceManifest, archive: Unzipped): void {
    // Register workflow resources (individual, not templated)
    for (const workflow of manifest.resources.workflows) {
        server.registerResource(
            workflow.name,
            workflow.uri,
            {
                mimeType: 'text/markdown',
                description: workflow.description,
            },
            async (uri) => {
                // Read the workflow file from the ZIP
                // Next-step appending is already done in the build script
                const fileData = archive[workflow.file]
                if (!fileData) {
                    throw new Error(`Workflow file "${workflow.file}" not found in archive`)
                }

                const content = strFromU8(fileData)

                return {
                    contents: [
                        {
                            uri: uri.toString(),
                            text: content,
                        },
                    ],
                }
            }
        )
    }

    // Register resource templates from manifest
    if (manifest.templates) {
        for (const template of manifest.templates) {
            // Get all available parameter values for this template
            const availableValues = template.items.map((item) => item.id)

            server.registerResource(
                template.name,
                new ResourceTemplate(template.uriPattern, {
                    list: async () => {
                        const resources = template.items.map((item) => ({
                            uri: template.uriPattern.replace(`{${template.parameterName}}`, item.id),
                            name: `${template.name} - ${item.id}`,
                            description: template.description,
                            mimeType: 'text/markdown',
                        }))

                        return { resources }
                    },
                    complete: {
                        [template.parameterName]: async () => availableValues,
                    },
                }),
                {
                    mimeType: 'text/markdown',
                    description: `${template.description}. Available ${template.parameterName}s: ${availableValues.join(', ')}`,
                },
                async (uri, variables) => {
                    // Extract parameter value from variables object
                    const paramValue = variables[template.parameterName]
                    if (!paramValue) {
                        throw new Error(`Missing parameter ${template.parameterName} in template variables`)
                    }

                    // Ensure it's a string (might be array)
                    const paramValueStr = Array.isArray(paramValue) ? paramValue[0] : paramValue

                    // Look up item in template
                    const item = template.items.find((i) => i.id === paramValueStr)
                    if (!item) {
                        const availableIds = template.items.map((i) => i.id).join(', ')
                        throw new Error(
                            `Unknown ${template.parameterName}: ${paramValueStr}. Available: ${availableIds}`
                        )
                    }

                    let content: string

                    // Get content from file (archive) or URL
                    if (item.file) {
                        const fileData = archive[item.file]
                        if (!fileData) {
                            throw new Error(`File "${item.file}" not found in archive`)
                        }
                        content = strFromU8(fileData)
                    } else if (item.url) {
                        content = await fetchDocumentation(item.url)
                    } else {
                        throw new Error(`Template item has neither file nor url: ${item.id}`)
                    }

                    return {
                        contents: [
                            {
                                uri: uri.toString(),
                                text: content,
                            },
                        ],
                    }
                }
            )
        }
    }

    // Register documentation resources from manifest
    for (const doc of manifest.resources.docs) {
        server.registerResource(
            doc.name,
            doc.uri,
            {
                mimeType: 'text/markdown',
                description: doc.description,
            },
            async (uri) => {
                const content = await fetchDocumentation(doc.url)
                return {
                    contents: [
                        {
                            uri: uri.toString(),
                            text: content,
                        },
                    ],
                }
            }
        )
    }
}

/**
 * Registers all PostHog resources with the MCP server
 * This function purely reflects the manifest - no logic, just registration
 */
export async function registerResources(server: McpServer, context: Context): Promise<void> {
    try {
        // Fetch examples markdown and manifest at startup
        // All resources (workflows, examples, docs) are now defined in the manifest
        const archive = await fetchExamplesMarkdown(context)
        const manifest = loadManifest(archive)
        registerManifestResources(server, manifest, archive)
    } catch (error) {
        console.error('Failed to fetch and register manifest resources:', error)
        throw error
    }
}
