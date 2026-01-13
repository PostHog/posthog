import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { type Unzipped, strFromU8, unzipSync } from 'fflate'

import type { Context } from '@/tools/types'

import { loadManifest, loadSkillsManifest } from './manifest-loader'
import type { ResourceManifest, SkillsManifest } from './manifest-types'

/**
 * URL to the PostHog examples markdown artifact (latest release)
 * This ZIP contains examples, workflows, and the manifest with all resource URIs
 */
const EXAMPLES_MARKDOWN_URL = 'https://github.com/PostHog/examples/releases/latest/download/examples-mcp-resources.zip'

/**
 * URL to the PostHog skills resources ZIP (latest release)
 * Contains manifest.json + individual skill ZIPs
 */
const SKILLS_RESOURCES_URL = 'https://github.com/PostHog/examples/releases/latest/download/skills-mcp-resources.zip'

// Cache for the examples markdown ZIP contents (includes both examples and prompts)
let cachedExamplesMarkdown: Unzipped | null = null

// Cache for skills resources ZIP contents
let cachedSkillsResources: Unzipped | null = null

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
    const localUrlRaw = (context.env as Record<string, string | undefined>)?.POSTHOG_MCP_LOCAL_EXAMPLES_URL
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
 * Fetches and caches the skills resources ZIP
 * For local testing, set POSTHOG_MCP_LOCAL_EXAMPLES_URL to a local HTTP URL
 * (Skills replaces the old examples approach, using the same env var)
 */
async function fetchSkillsResources(context: Context): Promise<Unzipped> {
    // Check for local URL override in environment (for testing)
    // Uses same env var as examples since skills replaces examples
    const localUrlRaw = (context.env as Record<string, string | undefined>)?.POSTHOG_MCP_LOCAL_EXAMPLES_URL
    const localUrl = localUrlRaw && localUrlRaw.trim() !== '' ? localUrlRaw : undefined
    const url = localUrl || SKILLS_RESOURCES_URL

    // Skip cache for local development
    if (cachedSkillsResources && !localUrl) {
        return cachedSkillsResources
    }

    const response = await fetch(url, localUrl ? { cache: 'no-store' } : {})

    if (!response.ok) {
        throw new Error(`Failed to fetch skills resources from ${url}: ${response.statusText}`)
    }

    const arrayBuffer = await response.arrayBuffer()
    const uint8Array = new Uint8Array(arrayBuffer)
    const unzipped = unzipSync(uint8Array)

    // Only cache if not using local URL override
    if (!localUrl) {
        cachedSkillsResources = unzipped
    }

    return unzipped
}

/**
 * Load skills manifest from the resources archive
 */
function loadSkillsManifestFromArchive(archive: Unzipped): SkillsManifest {
    const manifestData = archive['manifest.json']
    if (!manifestData) {
        throw new Error('manifest.json not found in skills archive')
    }
    const rawManifest = JSON.parse(strFromU8(manifestData))
    return loadSkillsManifest(rawManifest)
}

/**
 * Get prompts from the manifest
 * Currently returns empty - prompts will be migrated to skills
 */
export async function getPromptsFromManifest(_context: Context): Promise<ResourceManifest['resources']['prompts']> {
    // Prompts are being migrated to skills - return empty for now
    return []
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
 * Generate a shell command to install a skill from its download URL.
 * This command can be run by any agent with Bash access.
 */
function generateInstallCommand(skillId: string, downloadUrl: string): string {
    const targetDir = `.claude/skills/${skillId}`
    // Use a predictable temp file path based on skill ID to avoid conflicts
    const tempFile = `/tmp/posthog-skill-${skillId}.zip`

    // Command breakdown:
    // 1. Create target directory
    // 2. Download ZIP to temp file
    // 3. Extract to target directory
    // 4. Clean up temp file
    return `mkdir -p ${targetDir} && curl -sL "${downloadUrl}" -o ${tempFile} && unzip -o ${tempFile} -d ${targetDir} && rm ${tempFile}`
}

/**
 * Register skill resources from the skills manifest
 * posthog://skills/{id} - returns a ready-to-run shell command
 *
 * The command uses standard Unix tools (curl, unzip) and can be executed
 * by any agent with Bash access. This is the lowest-friction approach
 * for installing skills across different agent implementations.
 */
async function registerSkillResources(server: McpServer, context: Context): Promise<void> {
    try {
        // Fetch the bundled archive containing manifest + all skill ZIPs
        const archive = await fetchSkillsResources(context)
        const manifest = loadSkillsManifestFromArchive(archive)

        // Register each skill as an individual resource with its own description
        for (const skill of manifest.skills) {
            // Verify the skill file exists in the archive (for validation)
            const skillZipData = archive[skill.file]
            if (!skillZipData) {
                console.warn(`Skill file "${skill.file}" not found in archive, skipping`)
                continue
            }

            const installCommand = generateInstallCommand(skill.id, skill.downloadUrl)
            console.log(`Registering skill: ${skill.id}`)

            server.registerResource(
                skill.name,
                `posthog://skills/${skill.id}`,
                {
                    mimeType: 'text/plain',
                    description: skill.description,
                },
                async (uri) => {
                    // Return a ready-to-run shell command
                    // Any agent with Bash access can execute this directly
                    return {
                        contents: [
                            {
                                uri: uri.toString(),
                                mimeType: 'text/plain',
                                description: `${skill.description}. Run this command in Bash to install the skill.`,
                                text: installCommand,
                            },
                        ],
                    }
                }
            )
        }

        console.log(`Registered ${manifest.skills.length} skills (returning install commands)`)
    } catch (error) {
        // Skills are optional - log error but don't fail startup
        console.error('Failed to register skill resources:', error)
    }
}

/**
 * Registers all PostHog resources with the MCP server
 * Skills are the primary resource type - loaded from skills-mcp-resources.zip
 */
export async function registerResources(server: McpServer, context: Context): Promise<void> {
    try {
        await registerSkillResources(server, context)
    } catch (error) {
        console.error('Failed to register skill resources:', error)
        throw error
    }
}
