import { type Unzipped, strFromU8, unzipSync } from 'fflate'

import { loadContextMillManifest } from './manifest-loader'
import type { ContextMillManifest, ContextMillResource } from './manifest-types'

const CONTEXT_MILL_URL = 'https://github.com/PostHog/context-mill/releases/latest/download/skills-mcp-resources.zip'

// Bound the upstream fetch so a slow/hung GitHub release download can't stall a
// cold-start warmup indefinitely (it would otherwise hold the Redis writer lock
// and time out the integration harness `beforeAll`). One retry smooths over the
// transient slowness common on the `releases/latest/download` CDN redirect.
const ARCHIVE_FETCH_TIMEOUT_MS = 15_000
const ARCHIVE_FETCH_ATTEMPTS = 2

let cachedResources: Unzipped | null = null

export type ArchiveLoader = (url: string) => Promise<Uint8Array>

async function defaultArchiveLoader(url: string, noStore: boolean): Promise<Uint8Array> {
    let lastError: unknown
    for (let attempt = 1; attempt <= ARCHIVE_FETCH_ATTEMPTS; attempt++) {
        try {
            const response = await fetch(url, {
                ...(noStore ? { cache: 'no-store' } : {}),
                signal: AbortSignal.timeout(ARCHIVE_FETCH_TIMEOUT_MS),
            })
            if (!response.ok) {
                throw new Error(`Failed to fetch context-mill resources from ${url}: ${response.statusText}`)
            }
            const arrayBuffer = await response.arrayBuffer()
            return new Uint8Array(arrayBuffer)
        } catch (err) {
            lastError = err
        }
    }
    throw new Error(`Failed to fetch context-mill resources from ${url}: ${String(lastError)}`)
}

/**
 * Fetches and caches the context-mill resources ZIP.
 *
 * When `archiveLoader` is provided (hono runtime), the upstream fetch is
 * delegated to it so multiple instances share a Redis-backed cache with
 * single-writer coordination. The in-memory `cachedResources` still acts
 * as a per-process fast path on top of that layer.
 *
 * `localUrl` (`POSTHOG_MCP_LOCAL_SKILLS_URL`) always bypasses both caches.
 */
export async function fetchContextMillResources(localUrl?: string, archiveLoader?: ArchiveLoader): Promise<Unzipped> {
    const url = localUrl || CONTEXT_MILL_URL

    if (cachedResources && !localUrl) {
        return cachedResources
    }

    const bytes =
        !localUrl && archiveLoader ? await archiveLoader(url) : await defaultArchiveLoader(url, Boolean(localUrl))
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
    const url = localUrl || CONTEXT_MILL_URL
    const bytes = await defaultArchiveLoader(url, Boolean(localUrl))
    const archive = unzipSync(bytes)
    const manifest = loadManifestFromArchive(archive)
    return filterValidEntries(manifest.resources, archive)
}
