/**
 * Builds file trees for synthetic git plugin distribution.
 *
 * Assembles FileTree maps (path → content) for:
 * - The core PostHog plugin (MCP config, hooks, auth)
 * - Individual skill plugins (each with a dependency on core)
 *
 * Content is sourced from the context-mill archive already fetched
 * by the MCP server for resource registration.
 */

import type { Unzipped } from 'fflate'
import { strFromU8, unzipSync } from 'fflate'

import type { FileTree } from '@/lib/git'

import { loadContextMillManifest } from '@/resources/manifest-loader'
import type { ContextMillManifest } from '@/resources/manifest-types'

const MCP_SERVER_URL = 'https://mcp.posthog.com/mcp'

function parseVersionFromFrontmatter(content: string): string | undefined {
    const match = content.match(/^---\n([\s\S]*?)\n---/)
    if (!match?.[1]) {
        return undefined
    }
    const versionLine = match[1].split('\n').find((l) => l.trim().startsWith('version:'))
    return versionLine?.split(':')[1]?.trim()
}

export interface SkillEntry {
    name: string
    description: string
    version: string
    files: Record<string, string>
}

/**
 * Extract skill entries from the context-mill archive.
 * Each resource references an inner ZIP containing SKILL.md + references/.
 * Version is pulled from the SKILL.md frontmatter.
 */
export function extractSkillsFromArchive(archive: Unzipped): SkillEntry[] {
    const manifestData = archive['manifest.json']
    if (!manifestData) {
        return []
    }

    const rawManifest = JSON.parse(strFromU8(manifestData))
    let manifest: ContextMillManifest
    try {
        manifest = loadContextMillManifest(rawManifest)
    } catch {
        return []
    }

    const skills: SkillEntry[] = []

    for (const resource of manifest.resources) {
        if (!resource.file) {
            continue
        }

        const zipData = archive[resource.file]
        if (!zipData) {
            continue
        }

        try {
            const inner = unzipSync(zipData)
            const files: Record<string, string> = {}

            for (const [path, data] of Object.entries(inner)) {
                if (data.length === 0) {
                    continue
                }
                files[path] = strFromU8(data)
            }

            if (Object.keys(files).length > 0) {
                const skillMd = files['SKILL.md'] ?? ''
                const version = parseVersionFromFrontmatter(skillMd) ?? '0.0.0'

                skills.push({
                    name: resource.id,
                    description: resource.resource.description,
                    version,
                    files,
                })
            }
        } catch {
            continue
        }
    }

    return skills
}

/**
 * Build the file tree for the core PostHog plugin.
 * Contains MCP server config and plugin metadata — no skills.
 */
export function buildCorePluginFiles(version: string): FileTree {
    const files: FileTree = {}

    files['.claude-plugin/plugin.json'] = JSON.stringify(
        {
            name: 'posthog',
            version,
            description: 'PostHog MCP tools — analytics, feature flags, experiments, error tracking, and more.',
            author: { name: 'PostHog', email: 'hey@posthog.com', url: 'https://posthog.com' },
            homepage: 'https://posthog.com/docs/model-context-protocol',
            repository: 'https://github.com/PostHog/ai-plugin',
            license: 'MIT',
            keywords: ['analytics', 'feature-flags', 'experiments', 'error-tracking', 'a/b-testing', 'llm-analytics'],
        },
        null,
        2
    )

    files['mcp.json'] = JSON.stringify(
        {
            mcpServers: {
                posthog: {
                    type: 'http',
                    url: MCP_SERVER_URL,
                },
            },
        },
        null,
        2
    )

    return files
}

/**
 * Build the file tree for a single skill plugin.
 * Declares a dependency on the core `posthog` plugin.
 * Includes SKILL.md and all reference files from the inner ZIP.
 */
export function buildSkillPluginFiles(skill: SkillEntry): FileTree {
    const files: FileTree = {}

    files['.claude-plugin/plugin.json'] = JSON.stringify(
        {
            name: `posthog-${skill.name}`,
            version: skill.version,
            description: skill.description,
            dependencies: ['posthog'],
            author: { name: 'PostHog', email: 'hey@posthog.com' },
        },
        null,
        2
    )

    for (const [path, content] of Object.entries(skill.files)) {
        files[`skills/${skill.name}/${path}`] = content
    }

    return files
}

/**
 * Build the marketplace.json catalog listing all available plugins.
 * Served at /marketplace.json for Claude Code to discover.
 */
export function buildMarketplaceJson(skills: SkillEntry[], baseUrl: string): string {
    const plugins = [
        {
            name: 'posthog',
            source: { source: 'url', url: `${baseUrl}/git/core` },
            description: 'PostHog MCP tools — analytics, feature flags, experiments, error tracking, and more.',
            policy: { installation: 'AVAILABLE', authentication: 'ON_INSTALL' },
            category: 'Productivity',
        },
        ...skills.map((skill) => ({
            name: `posthog-${skill.name}`,
            source: { source: 'url', url: `${baseUrl}/git/skills/${skill.name}` },
            description: skill.description,
            dependencies: ['posthog'],
            category: 'Productivity',
        })),
    ]

    return JSON.stringify(
        {
            name: 'posthog',
            owner: { name: 'PostHog', email: 'hey@posthog.com' },
            interface: { displayName: 'PostHog' },
            plugins,
        },
        null,
        2
    )
}
