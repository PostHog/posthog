import { type Unzipped, strFromU8, strToU8, unzipSync, zipSync } from 'fflate'

import {
    MAX_ARCHIVE_FILE_BYTES,
    MAX_ARCHIVE_FILES,
    MAX_ARCHIVE_UNCOMPRESSED_BYTES,
    parseFrontmatter,
} from '@/skills/skill-catalog'

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
    let fileCount = 0
    let totalUncompressedBytes = 0
    for (const [entryName, entryBytes] of Object.entries(archive)) {
        const match = OMNIBUS_ARCHIVE_PATTERN.exec(entryName)
        if (!match) {
            continue
        }
        const skillName = match[1]!
        // The catalog applies the same limits to the repacked archive, but only after this
        // inflate has already allocated; the filter stops a crafted release before that.
        const inner = unzipSync(entryBytes, {
            filter: (file) => {
                if (file.name.endsWith('/')) {
                    return false
                }
                fileCount += 1
                totalUncompressedBytes += file.originalSize
                if (
                    fileCount > MAX_ARCHIVE_FILES ||
                    file.originalSize > MAX_ARCHIVE_FILE_BYTES ||
                    totalUncompressedBytes > MAX_ARCHIVE_UNCOMPRESSED_BYTES
                ) {
                    throw new Error(`Omnibus archive "${entryName}" exceeds the extraction limit`)
                }
                return true
            },
        })
        const skillFile = inner['SKILL.md']
        const rewrittenSkillFile = skillFile ? strFromU8(skillFile).replace(/^(name:[ \t]*)omnibus-/m, '$1') : undefined
        if (!rewrittenSkillFile || declaredSkillName(rewrittenSkillFile, entryName) !== skillName) {
            // The served name comes from the filename, so a release cannot publish under another skill's name.
            console.warn(`[context-mill] skipping "${entryName}": SKILL.md does not declare the name "${skillName}"`)
            continue
        }
        for (const [path, bytes] of Object.entries(inner)) {
            files[`${skillName}/${path}`] = path === 'SKILL.md' ? strToU8(rewrittenSkillFile) : bytes
        }
    }
    // Level 1 keeps the writer pod's event loop short; the blob is read once per pod per release.
    return Object.keys(files).length > 0 ? zipSync(files, { level: 1, mtime: OMNIBUS_ARCHIVE_MTIME }) : null
}

// Reads the name the way the catalog will, so a decoy `name:` line outside the frontmatter cannot pass.
function declaredSkillName(skillFile: string, source: string): string | undefined {
    try {
        return parseFrontmatter(skillFile, source).name
    } catch {
        return undefined
    }
}

// A bad omnibus zip must not cost the manifest, which the resource list depends on.
function repackOmnibusSkills(archive: Unzipped): Uint8Array | null {
    try {
        return buildOmnibusSkillsArchive(archive)
    } catch (error) {
        console.error('[context-mill] omnibus skills could not be repacked; serving none:', error)
        return null
    }
}

/**
 * Fetch + unzip + parse the context-mill archive, returning the filtered manifest
 * entries and the repacked omnibus skills. Does not touch the module-level
 * `cachedResources`; used by the hono runtime to push both into Redis-backed caches
 * without retaining the archive in process memory.
 */
export async function fetchAndExtractEntries(
    localUrl?: string,
    includeOmnibusSkills = true
): Promise<ContextMillArchiveContents> {
    const url = localUrl || CONTEXT_MILL_URL
    const bytes = await defaultArchiveLoader(url, Boolean(localUrl))
    const archive = unzipSync(bytes)
    const manifest = loadManifestFromArchive(archive)
    return {
        entries: filterValidEntries(manifest.resources, archive),
        omnibusSkillsArchive: includeOmnibusSkills ? repackOmnibusSkills(archive) : null,
    }
}
