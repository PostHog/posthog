import { type Unzipped, strFromU8, unzipSync } from 'fflate'

import { loadContextMillManifest } from './manifest-loader'
import type { ContextMillManifest, ContextMillResource } from './manifest-types'

const CONTEXT_MILL_URL = 'https://github.com/PostHog/context-mill/releases/latest/download/skills-mcp-resources.zip'

// The archive is served by the GitHub release CDN, which drops connections and
// serves the odd 5xx often enough to fail a single-shot fetch.
const ARCHIVE_FETCH_MAX_ATTEMPTS = 3
const ARCHIVE_FETCH_BASE_BACKOFF_MS = 250
// Per attempt, because the runtime awaits warmup before it listens and holds a
// 60s writer lock while it fetches. Without a bound, undici's 300s default times
// three attempts would stall boot and outlive that lock. Every attempt plus its
// backoff still fits in the lock, and 15s is far above a healthy download of an
// 8 MB archive, so this only fires on a stalled connection.
const ARCHIVE_FETCH_TIMEOUT_MS = 15_000

let cachedResources: Unzipped | null = null

/** A response the CDN will keep giving us, such as a 404 for a missing release. */
class PermanentArchiveError extends Error {}

function isTransientStatus(status: number): boolean {
    return status === 408 || status === 429 || status >= 500
}

async function fetchArchiveOnce(url: string, noStore: boolean): Promise<Uint8Array> {
    const response = await fetch(url, {
        signal: AbortSignal.timeout(ARCHIVE_FETCH_TIMEOUT_MS),
        ...(noStore ? { cache: 'no-store' as const } : {}),
    })
    if (!response.ok) {
        const message = `Failed to fetch context-mill resources from ${url}: ${response.statusText}`
        throw isTransientStatus(response.status) ? new Error(message) : new PermanentArchiveError(message)
    }
    const arrayBuffer = await response.arrayBuffer()
    return new Uint8Array(arrayBuffer)
}

async function fetchArchiveWithRetry(localUrl?: string): Promise<Uint8Array> {
    const url = localUrl || CONTEXT_MILL_URL
    const noStore = Boolean(localUrl)

    for (let attempt = 0; ; attempt++) {
        try {
            return await fetchArchiveOnce(url, noStore)
        } catch (error) {
            if (error instanceof PermanentArchiveError || attempt >= ARCHIVE_FETCH_MAX_ATTEMPTS - 1) {
                throw error
            }
            const backoffMs = ARCHIVE_FETCH_BASE_BACKOFF_MS * 2 ** attempt
            // Equal jitter so concurrent warmups don't retry in lockstep.
            await new Promise((resolve) => setTimeout(resolve, backoffMs / 2 + Math.random() * (backoffMs / 2)))
        }
    }
}

/**
 * Fetches and caches the context-mill resources ZIP.
 *
 * `localUrl` (`POSTHOG_MCP_LOCAL_SKILLS_URL`) always bypasses the in-process
 * cache. The hono runtime does not come through here: it calls
 * `fetchAndExtractEntries` so instances share the Redis-backed cache.
 */
export async function fetchContextMillResources(localUrl?: string): Promise<Unzipped> {
    if (cachedResources && !localUrl) {
        return cachedResources
    }

    const bytes = await fetchArchiveWithRetry(localUrl)
    const unzipped = unzipSync(bytes)

    if (!localUrl) {
        cachedResources = unzipped
    }

    return unzipped
}

export function loadManifestFromArchive(archive: Unzipped): ContextMillManifest {
    const manifestData = archive['manifest.json']
    if (!manifestData) {
        throw new Error('manifest.json not found in archive')
    }
    const rawManifest = JSON.parse(strFromU8(manifestData))
    return loadContextMillManifest(rawManifest)
}

export function filterValidEntries(entries: readonly ContextMillResource[], archive: Unzipped): ContextMillResource[] {
    return entries.filter((entry) => {
        if (entry.file && !archive[entry.file]) {
            console.warn(`Resource file "${entry.file}" not found in archive, skipping`)
            return false
        }
        return true
    })
}

export function clearResourceCache(): void {
    cachedResources = null
}

/**
 * Fetch + unzip + parse the context-mill manifest, returning the filtered
 * entries. Does not touch the module-level `cachedResources`; used by the
 * hono runtime to push entries into a Redis-sharded cache without retaining
 * the archive in process memory.
 */
export async function fetchAndExtractEntries(localUrl?: string): Promise<ContextMillResource[]> {
    const bytes = await fetchArchiveWithRetry(localUrl)
    const archive = unzipSync(bytes)
    const manifest = loadManifestFromArchive(archive)
    return filterValidEntries(manifest.resources, archive)
}
