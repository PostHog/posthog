/**
 * Builds file trees for synthetic git plugin distribution.
 *
 * Assembles FileTree maps (path → content) for:
 * - The core PostHog plugin (MCP config, hooks, auth)
 * - Individual skill plugins (each with a dependency on core)
 * - Bundle plugins (multiple skills grouped by framework)
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

export interface BundleEntry {
    name: string
    displayName: string
    description: string
    keywords: string[]
    skills: string[]
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

export interface RecommendSkill {
    name: string
    content: string
}

/**
 * Extract bundle definitions and recommend skill from the context-mill manifest.
 */
export function extractBundlesFromArchive(archive: Unzipped): { bundles: BundleEntry[]; recommendSkill: RecommendSkill | null } {
    const manifestData = archive['manifest.json']
    if (!manifestData) {
        return { bundles: [], recommendSkill: null }
    }

    const rawManifest = JSON.parse(strFromU8(manifestData))

    const bundles: BundleEntry[] = []
    const rawBundles = rawManifest.bundles as Record<string, {
        name: string
        description: string
        keywords?: string[]
        skills: string[]
    }> | undefined

    if (rawBundles) {
        for (const [id, bundle] of Object.entries(rawBundles)) {
            bundles.push({
                name: id,
                displayName: bundle.name,
                description: bundle.description,
                keywords: bundle.keywords ?? [],
                skills: bundle.skills,
            })
        }
    }

    const recommendSkill = rawManifest.recommendSkill as RecommendSkill | undefined

    return { bundles, recommendSkill: recommendSkill ?? null }
}

/**
 * Build the file tree for the core PostHog plugin.
 * Contains MCP server config, the recommend-skills skill (from context-mill), and plugin metadata.
 */
export function buildCorePluginFiles(version: string, recommendSkill?: RecommendSkill | null): FileTree {
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

    if (recommendSkill) {
        files[`skills/${recommendSkill.name}/SKILL.md`] = recommendSkill.content
    }

    return files
}

/**
 * Build the file tree for a single skill plugin.
 * Declares a dependency on the core `posthog` plugin.
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
 * Build the file tree for a bundle plugin.
 * Inlines all referenced skills into a single plugin.
 */
export function buildBundlePluginFiles(bundle: BundleEntry, skills: SkillEntry[]): FileTree {
    const files: FileTree = {}
    const skillMap = new Map(skills.map((s) => [s.name, s]))

    const resolvedSkills = bundle.skills
        .map((id) => skillMap.get(id))
        .filter((s): s is SkillEntry => s !== undefined)

    const version = resolvedSkills[0]?.version ?? '0.0.0'

    files['.claude-plugin/plugin.json'] = JSON.stringify(
        {
            name: `posthog-${bundle.name}`,
            version,
            description: bundle.description,
            dependencies: ['posthog'],
            author: { name: 'PostHog', email: 'hey@posthog.com' },
            keywords: bundle.keywords,
        },
        null,
        2
    )

    for (const skill of resolvedSkills) {
        for (const [path, content] of Object.entries(skill.files)) {
            files[`skills/${skill.name}/${path}`] = content
        }
    }

    return files
}

/**
 * Build the marketplace.json catalog.
 * Lists the core plugin and bundles (not individual skills).
 */
export function buildMarketplaceJson(bundles: BundleEntry[], baseUrl: string): string {
    const plugins = [
        {
            name: 'posthog',
            source: { source: 'url', url: `${baseUrl}/git/core` },
            description: 'PostHog MCP tools — analytics, feature flags, experiments, error tracking, and more.',
            policy: { installation: 'AVAILABLE', authentication: 'ON_INSTALL' },
            category: 'Productivity',
        },
        ...bundles.map((bundle) => ({
            name: `posthog-${bundle.name}`,
            source: { source: 'url', url: `${baseUrl}/git/bundles/${bundle.name}` },
            description: bundle.description,
            dependencies: ['posthog'],
            keywords: bundle.keywords,
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
