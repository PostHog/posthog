/**
 * Git smart HTTP routes for synthetic plugin distribution.
 *
 * Serves bundles, per-skill, and core plugin repos via the git smart HTTP
 * protocol, enabling per-plugin install attribution through PostHog events.
 *
 * Routes:
 *   GET  /marketplace.json                              → plugin catalog (plain HTTP)
 *   GET  /git/marketplace/...                           → marketplace repo (for `plugin marketplace add`)
 *   GET  /git/core/...                                  → core plugin
 *   GET  /git/bundles/:name/...                         → bundle plugin (multiple skills)
 *   GET  /git/skills/:name/...                          → individual skill plugin
 */

import { createHash } from 'node:crypto'

import { env } from 'cloudflare:workers'
import type { Unzipped } from 'fflate'

import { AnalyticsEvent, getPostHogClient } from '@/lib/analytics'
import { type FileTree, GitRepoCache, handleInfoRefs, handleUploadPack } from '@/lib/git'
import type { RequestLogger } from '@/lib/logging'
import {
    type BundleEntry,
    type RecommendSkill,
    type SkillEntry,
    buildBundlePluginFiles,
    buildCorePluginFiles,
    buildMarketplaceJson,
    buildSkillPluginFiles,
    extractBundlesFromArchive,
    extractSkillsFromArchive,
} from '@/lib/plugin-content'
import { CONTEXT_MILL_URL } from '@/resources/index'

import { unzipSync } from 'fflate'

const repoCache = new GitRepoCache()

let cachedArchive: Unzipped | null = null
let cachedSkills: SkillEntry[] | null = null
let cachedBundles: BundleEntry[] | null = null
let cachedRecommendSkill: RecommendSkill | null = null
let cachedMarketplaceJson: string | null = null

async function getArchive(env?: Record<string, string | undefined>): Promise<Unzipped> {
    if (cachedArchive) {
        return cachedArchive
    }

    const localUrl = env?.POSTHOG_MCP_LOCAL_SKILLS_URL?.trim() || undefined
    const url = localUrl || CONTEXT_MILL_URL

    const response = await fetch(url, localUrl ? { cache: 'no-store' } : {})
    if (!response.ok) {
        throw new Error(`Failed to fetch context-mill archive from ${url}: ${response.statusText}`)
    }

    const buffer = await response.arrayBuffer()
    cachedArchive = unzipSync(new Uint8Array(buffer))
    cachedSkills = null
    cachedBundles = null
    cachedMarketplaceJson = null
    return cachedArchive
}

function getSkills(archive: Unzipped): SkillEntry[] {
    if (cachedSkills) {
        return cachedSkills
    }
    cachedSkills = extractSkillsFromArchive(archive)
    return cachedSkills
}

function getBundlesAndRecommendSkill(archive: Unzipped): { bundles: BundleEntry[]; recommendSkill: RecommendSkill | null } {
    if (cachedBundles) {
        return { bundles: cachedBundles, recommendSkill: cachedRecommendSkill }
    }
    const result = extractBundlesFromArchive(archive)
    cachedBundles = result.bundles
    cachedRecommendSkill = result.recommendSkill
    return result
}

function deriveAnonymousId(request: Request): string {
    const ip = request.headers.get('CF-Connecting-IP') || request.headers.get('X-Forwarded-For') || 'unknown'
    const ua = request.headers.get('User-Agent') || ''
    return createHash('sha256').update(`${ip}:${ua}`).digest('hex').slice(0, 32)
}

function trackFetch(
    request: Request,
    ctx: ExecutionContext,
    pluginType: 'marketplace' | 'core' | 'bundle' | 'skill',
    pluginName: string,
    requestType: 'info_refs' | 'upload_pack',
    contentHash: string
): void {
    try {
        const client = getPostHogClient()
        client.capture({
            distinctId: deriveAnonymousId(request),
            event: AnalyticsEvent.SKILL_FETCHED,
            properties: {
                plugin_type: pluginType,
                plugin_name: pluginName,
                request_type: requestType,
                content_version: contentHash,
                user_agent: request.headers.get('User-Agent') || undefined,
                $ip: request.headers.get('CF-Connecting-IP') || request.headers.get('X-Forwarded-For') || undefined,
            },
        })
        ctx.waitUntil(client.flush())
    } catch {
        // Never let analytics break the request
    }
}

/**
 * Parse a git path segment: "prefix/rest" or bare "prefix".
 * Returns [prefix, gitAction] where gitAction is "" for bare paths.
 */
function parseSegment(gitPath: string, prefix: string): [true, string] | [false] {
    if (gitPath === prefix) {
        return [true, '']
    }
    if (gitPath.startsWith(prefix + '/')) {
        return [true, gitPath.slice(prefix.length + 1)]
    }
    return [false]
}

/**
 * Parse a named segment: "prefix/<name>/rest".
 * Returns [name, gitAction] or null.
 */
function parseNamedSegment(gitPath: string, prefix: string): { name: string; gitAction: string } | null {
    if (!gitPath.startsWith(prefix + '/')) {
        return null
    }
    const rest = gitPath.slice(prefix.length + 1)
    const slashIdx = rest.indexOf('/')
    if (slashIdx === -1) {
        return null
    }
    return { name: rest.slice(0, slashIdx), gitAction: rest.slice(slashIdx + 1) }
}

export async function handleGitRequest(
    request: Request,
    url: URL,
    ctx: ExecutionContext,
    log: RequestLogger
): Promise<Response | null> {
    const baseUrl = `${url.protocol}//${url.host}`

    // --- Marketplace catalog (plain HTTP) ---
    if (url.pathname === '/marketplace.json' && request.method === 'GET') {
        log.extend({ route: 'marketplace.json' })
        const archive = await getArchive(env as unknown as Record<string, string | undefined>)
        const { bundles } = getBundlesAndRecommendSkill(archive)

        if (!cachedMarketplaceJson) {
            cachedMarketplaceJson = buildMarketplaceJson(bundles, baseUrl)
        }

        try {
            const client = getPostHogClient()
            client.capture({
                distinctId: deriveAnonymousId(request),
                event: AnalyticsEvent.MARKETPLACE_VIEWED,
                properties: {
                    bundle_count: bundles.length,
                    user_agent: request.headers.get('User-Agent') || undefined,
                },
            })
            ctx.waitUntil(client.flush())
        } catch {
            // Never let analytics break the request
        }

        return new Response(cachedMarketplaceJson, {
            headers: { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=300' },
        })
    }

    // --- Git endpoints ---
    if (!url.pathname.startsWith('/git/')) {
        return null
    }

    const gitPath = url.pathname.slice(5) // strip "/git/"

    let pluginType: 'marketplace' | 'core' | 'bundle' | 'skill'
    let itemName: string | null = null
    let gitAction: string

    // marketplace
    const mp = parseSegment(gitPath, 'marketplace')
    if (mp[0]) {
        pluginType = 'marketplace'
        gitAction = mp[1]
    // core
    } else if (gitPath.startsWith('core/')) {
        pluginType = 'core'
        gitAction = gitPath.slice(5)
    // bundles/:name
    } else {
        const bundleMatch = parseNamedSegment(gitPath, 'bundles')
        if (bundleMatch) {
            pluginType = 'bundle'
            itemName = bundleMatch.name
            gitAction = bundleMatch.gitAction
        } else {
            // skills/:name
            const skillMatch = parseNamedSegment(gitPath, 'skills')
            if (skillMatch) {
                pluginType = 'skill'
                itemName = skillMatch.name
                gitAction = skillMatch.gitAction
            } else {
                return null
            }
        }
    }

    log.extend({ route: 'git', pluginType, itemName, gitAction })

    // Build file tree
    const archive = await getArchive(env as unknown as Record<string, string | undefined>)
    const skills = getSkills(archive)
    let files: FileTree
    let cacheKey: string

    const { bundles, recommendSkill } = getBundlesAndRecommendSkill(archive)

    if (pluginType === 'marketplace') {
        const marketplaceContent = buildMarketplaceJson(bundles, baseUrl)
        files = { '.claude-plugin/marketplace.json': marketplaceContent }
        cacheKey = 'marketplace'
    } else if (pluginType === 'core') {
        const version = skills[0]?.version ?? '0.0.0'
        files = buildCorePluginFiles(version, recommendSkill)
        cacheKey = 'core'
    } else if (pluginType === 'bundle') {
        const bundle = bundles.find((b) => b.name === itemName)
        if (!bundle) {
            return new Response('Unknown bundle', { status: 404 })
        }
        files = buildBundlePluginFiles(bundle, skills)
        cacheKey = `bundle:${itemName}`
    } else {
        const skill = skills.find((s) => s.name === itemName)
        if (!skill) {
            return new Response('Unknown skill', { status: 404 })
        }
        files = buildSkillPluginFiles(skill)
        cacheKey = `skill:${itemName}`
    }

    const { objects, headSha, contentHash } = repoCache.getOrBuild(cacheKey, files)
    const pluginName =
        pluginType === 'marketplace'
            ? 'marketplace'
            : pluginType === 'core'
              ? 'posthog'
              : `posthog-${itemName}`

    // Bare path — Claude Code probes the URL before cloning
    if (gitAction === '' && request.method === 'GET') {
        if (pluginType === 'marketplace') {
            const content = buildMarketplaceJson(bundles, baseUrl)
            return new Response(content, {
                headers: { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=300' },
            })
        }
        return new Response('', { status: 200, headers: { 'Content-Type': 'text/plain' } })
    }

    // info/refs
    if (gitAction === 'info/refs' && request.method === 'GET') {
        if (url.searchParams.get('service') !== 'git-upload-pack') {
            return new Response('Unsupported service', { status: 403 })
        }
        trackFetch(request, ctx, pluginType, pluginName, 'info_refs', contentHash)
        return handleInfoRefs(headSha)
    }

    // upload-pack
    if (gitAction === 'git-upload-pack' && request.method === 'POST') {
        trackFetch(request, ctx, pluginType, pluginName, 'upload_pack', contentHash)
        return handleUploadPack(request, objects, headSha)
    }

    return new Response('Not found', { status: 404 })
}
