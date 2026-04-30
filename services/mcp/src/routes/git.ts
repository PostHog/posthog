/**
 * Git smart HTTP routes for synthetic plugin distribution.
 *
 * Serves per-skill and core plugin repos via the git smart HTTP protocol,
 * enabling per-plugin install attribution through PostHog analytics events.
 *
 * Routes:
 *   GET  /marketplace.json                              → plugin catalog (plain HTTP)
 *   GET  /git/marketplace/info/refs?service=...         → marketplace repo (for `plugin marketplace add`)
 *   POST /git/marketplace/git-upload-pack               → marketplace repo packfile
 *   GET  /git/core/info/refs?service=git-upload-pack    → core plugin
 *   POST /git/core/git-upload-pack                      → core plugin packfile
 *   GET  /git/skills/:name/info/refs?service=...        → per-skill plugin
 *   POST /git/skills/:name/git-upload-pack              → per-skill packfile
 */

import { createHash } from 'node:crypto'

import type { Unzipped } from 'fflate'

import { AnalyticsEvent, getPostHogClient } from '@/lib/analytics'
import { type FileTree, GitRepoCache, handleInfoRefs, handleUploadPack } from '@/lib/git'
import type { RequestLogger } from '@/lib/logging'
import {
    buildCorePluginFiles,
    buildMarketplaceJson,
    buildSkillPluginFiles,
    extractSkillsFromArchive,
    type SkillEntry,
} from '@/lib/plugin-content'
import { CONTEXT_MILL_URL } from '@/resources/index'

import { strFromU8, unzipSync } from 'fflate'

const repoCache = new GitRepoCache()

// Module-level cache for context-mill archive (shared with resources/index.ts pattern)
let cachedArchive: Unzipped | null = null
let cachedSkills: SkillEntry[] | null = null
let cachedMarketplaceJson: string | null = null

async function getArchive(): Promise<Unzipped> {
    if (cachedArchive) {
        return cachedArchive
    }

    const response = await fetch(CONTEXT_MILL_URL)
    if (!response.ok) {
        throw new Error(`Failed to fetch context-mill archive: ${response.statusText}`)
    }

    const buffer = await response.arrayBuffer()
    cachedArchive = unzipSync(new Uint8Array(buffer))
    cachedSkills = null
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

function deriveAnonymousId(request: Request): string {
    const ip = request.headers.get('CF-Connecting-IP') || request.headers.get('X-Forwarded-For') || 'unknown'
    const ua = request.headers.get('User-Agent') || ''
    return createHash('sha256').update(`${ip}:${ua}`).digest('hex').slice(0, 32)
}

function trackSkillFetch(
    request: Request,
    ctx: ExecutionContext,
    pluginType: 'marketplace' | 'core' | 'skill',
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
 * Handle git and marketplace requests. Returns a Response if the path matches,
 * or null to let the main router continue.
 */
export async function handleGitRequest(
    request: Request,
    url: URL,
    ctx: ExecutionContext,
    log: RequestLogger
): Promise<Response | null> {
    const baseUrl = `${url.protocol}//${url.host}`

    // --- Marketplace catalog ---
    if (url.pathname === '/marketplace.json' && request.method === 'GET') {
        log.extend({ route: 'marketplace.json' })
        const archive = await getArchive()
        const skills = getSkills(archive)

        if (!cachedMarketplaceJson) {
            cachedMarketplaceJson = buildMarketplaceJson(skills, baseUrl)
        }

        try {
            const client = getPostHogClient()
            client.capture({
                distinctId: deriveAnonymousId(request),
                event: AnalyticsEvent.MARKETPLACE_VIEWED,
                properties: {
                    skill_count: skills.length,
                    user_agent: request.headers.get('User-Agent') || undefined,
                },
            })
            ctx.waitUntil(client.flush())
        } catch {
            // Never let analytics break the request
        }

        return new Response(cachedMarketplaceJson, {
            headers: {
                'Content-Type': 'application/json',
                'Cache-Control': 'public, max-age=300',
            },
        })
    }

    // --- Git endpoints ---
    if (!url.pathname.startsWith('/git/')) {
        return null
    }

    const gitPath = url.pathname.slice(5) // strip "/git/"

    // Parse: "marketplace/info/refs", "marketplace/git-upload-pack",
    //        "core/info/refs", "core/git-upload-pack",
    //        "skills/<name>/info/refs", "skills/<name>/git-upload-pack"
    let pluginType: 'marketplace' | 'core' | 'skill'
    let skillName: string | null = null
    let gitAction: string

    if (gitPath === 'marketplace' || gitPath.startsWith('marketplace/')) {
        pluginType = 'marketplace'
        gitAction = gitPath.length > 12 ? gitPath.slice(12) : '' // strip "marketplace/" if present
    } else if (gitPath.startsWith('core/')) {
        pluginType = 'core'
        gitAction = gitPath.slice(5) // strip "core/"
    } else if (gitPath.startsWith('skills/')) {
        pluginType = 'skill'
        const rest = gitPath.slice(7) // strip "skills/"
        const slashIdx = rest.indexOf('/')
        if (slashIdx === -1) {
            return new Response('Not found', { status: 404 })
        }
        skillName = rest.slice(0, slashIdx)
        gitAction = rest.slice(slashIdx + 1)
    } else {
        return null
    }

    log.extend({ route: 'git', pluginType, skillName, gitAction })

    // Build file tree
    let files: FileTree
    let cacheKey: string

    if (pluginType === 'marketplace') {
        const archive = await getArchive()
        const skills = getSkills(archive)
        const marketplaceContent = buildMarketplaceJson(skills, baseUrl)
        files = { '.claude-plugin/marketplace.json': marketplaceContent }
        cacheKey = 'marketplace'
    } else if (pluginType === 'core') {
        files = buildCorePluginFiles()
        cacheKey = 'core'
    } else {
        const archive = await getArchive()
        const skills = getSkills(archive)
        const skill = skills.find((s) => s.name === skillName)
        if (!skill) {
            return new Response('Unknown skill', { status: 404 })
        }
        files = buildSkillPluginFiles(skill)
        cacheKey = `skill:${skillName}`
    }

    const { objects, headSha, contentHash } = repoCache.getOrBuild(cacheKey, files)
    const pluginName =
        pluginType === 'marketplace' ? 'marketplace' : pluginType === 'core' ? 'posthog' : `posthog-${skillName}`

    // Bare path (e.g. GET /git/marketplace) — Claude Code probes the URL before cloning.
    // For the marketplace, serve the catalog JSON directly so the schema validator passes.
    if (gitAction === '' && request.method === 'GET') {
        if (pluginType === 'marketplace') {
            const archive = await getArchive()
            const skills = getSkills(archive)
            const content = buildMarketplaceJson(skills, baseUrl)
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
        trackSkillFetch(request, ctx, pluginType, pluginName, 'info_refs', contentHash)
        return handleInfoRefs(headSha)
    }

    // upload-pack
    if (gitAction === 'git-upload-pack' && request.method === 'POST') {
        trackSkillFetch(request, ctx, pluginType, pluginName, 'upload_pack', contentHash)
        return handleUploadPack(request, objects, headSha)
    }

    return new Response('Not found', { status: 404 })
}
