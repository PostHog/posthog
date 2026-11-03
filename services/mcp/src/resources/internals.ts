import { type Unzipped, strFromU8, strToU8, unzipSync, zipSync } from 'fflate'

import { loadContextMillManifest } from './manifest-loader'
import type { ContextMillManifest, ContextMillResource } from './manifest-types'

const CONTEXT_MILL_URL = 'https://github.com/PostHog/context-mill/releases/latest/download/skills-mcp-resources.zip'

const OMNIBUS_ARCHIVE_PATTERN = /^omnibus-([a-z0-9]+(?:-[a-z0-9]+)*)\.zip$/
// A fixed mtime keeps the repacked bytes, and so their sha, stable across refreshes of
// an unchanged release; a wall-clock mtime would make every pod re-parse every refresh.
const OMNIBUS_ARCHIVE_MTIME = new Date('2000-01-01T00:00:00Z')

let cachedResources: Unzipped | null = null

export interface ContextMillArchiveContents {
    entries: ContextMillResource[]
    omnibusSkillsArchive: Uint8Array | null
}

export type ArchiveLoader = (url: string) => Promise<Uint8Array>

async function defaultArchiveLoader(url: string, noStore: boolean): Promise<Uint8Array> {
    const response = await fetch(url, noStore ? { cache: 'no-store' } : {})
    if (!response.ok) {
        throw new Error(`Failed to fetch context-mill resources from ${url}: ${response.statusText}`)
    }
    const arrayBuffer = await response.arrayBuffer()
    return new Uint8Array(arrayBuffer)
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

export function buildOmnibusSkillsArchive(archive: Unzipped): Uint8Array | null {
    const files: Record<string, Uint8Array> = {}
    for (const [entryName, entryBytes] of Object.entries(archive)) {
        const match = OMNIBUS_ARCHIVE_PATTERN.exec(entryName)
        if (!match) {
            continue
        }
        const skillName = match[1]!
        for (const [path, bytes] of Object.entries(unzipSync(entryBytes))) {
            if (path.endsWith('/')) {
                continue
            }
            files[`${skillName}/${path}`] =
                path === 'SKILL.md' ? strToU8(strFromU8(bytes).replace(/^(name:[ \t]*)omnibus-/m, '$1')) : bytes
        }
    }
    return Object.keys(files).length > 0 ? zipSync(files, { mtime: OMNIBUS_ARCHIVE_MTIME }) : null
}

/**
 * Fetch + unzip + parse the context-mill archive, returning the filtered manifest
 * entries and the repacked omnibus skills. Does not touch the module-level
 * `cachedResources`; used by the hono runtime to push both into Redis-backed caches
 * without retaining the archive in process memory.
 */
export async function fetchAndExtractEntries(localUrl?: string): Promise<ContextMillArchiveContents> {
    const url = localUrl || CONTEXT_MILL_URL
    const bytes = await defaultArchiveLoader(url, Boolean(localUrl))
    const archive = unzipSync(bytes)
    const manifest = loadManifestFromArchive(archive)
    return {
        entries: filterValidEntries(manifest.resources, archive),
        omnibusSkillsArchive: buildOmnibusSkillsArchive(archive),
    }
}
