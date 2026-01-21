import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { type Unzipped, strFromU8, unzipSync } from 'fflate'

import type { Context } from '@/tools/types'

import { loadSkillsManifest } from './manifest-loader'
import type { ResourceManifest, SkillsManifest } from './manifest-types'

/**
 * URL to the PostHog skills resources ZIP (latest release)
 * Contains manifest.json + individual skill ZIPs
 */
const SKILLS_RESOURCES_URL = 'https://github.com/PostHog/examples/releases/latest/download/skills-mcp-resources.zip'

// Cache for skills resources ZIP contents
let cachedSkillsResources: Unzipped | null = null

/**
 * Fetches and caches the skills resources ZIP
 * For local testing, set POSTHOG_MCP_LOCAL_SKILLS_URL to a local HTTP URL
 */
async function fetchSkillsResources(context: Context): Promise<Unzipped> {
    // Check for local URL override in environment (for testing)
    const localUrlRaw = (context.env as Record<string, string | undefined>)?.POSTHOG_MCP_LOCAL_SKILLS_URL
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
 * Generate a shell command to install a skill from its download URL.
 * This command can be run by any agent with Bash access.
 */
function generateInstallCommand(skillId: string, downloadUrl: string): string {
    if (!/^[a-zA-Z0-9_-]+$/.test(skillId)) {
        throw new Error(`Invalid skill ID: ${skillId}`)
    }

    // Escape single quotes in URL for safe shell interpolation
    const escapedUrl = downloadUrl.replace(/'/g, "'\\''")

    const targetDir = `.claude/skills/${skillId}`
    const tempFile = `/tmp/posthog-skill-${skillId}.zip`

    return `mkdir -p ${targetDir} && curl -sL '${escapedUrl}' -o ${tempFile} && unzip -o ${tempFile} -d ${targetDir} && rm ${tempFile}`
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
    await registerSkillResources(server, context)
}
