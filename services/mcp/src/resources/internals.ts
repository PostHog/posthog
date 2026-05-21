import { type Unzipped, strFromU8, unzipSync } from 'fflate'

import type { ContextMillManifest, ContextMillResource } from './manifest-types'
import { loadContextMillManifest } from './manifest-loader'

const CONTEXT_MILL_URL = 'https://github.com/PostHog/context-mill/releases/latest/download/skills-mcp-resources.zip'

let cachedResources: Unzipped | null = null

export async function fetchContextMillResources(localUrl?: string): Promise<Unzipped> {
    const url = localUrl || CONTEXT_MILL_URL

    if (cachedResources && !localUrl) {
        return cachedResources
    }

    const response = await fetch(url, localUrl ? { cache: 'no-store' } : {})
    if (!response.ok) {
        throw new Error(`Failed to fetch context-mill resources from ${url}: ${response.statusText}`)
    }

    const arrayBuffer = await response.arrayBuffer()
    const uint8Array = new Uint8Array(arrayBuffer)
    const unzipped = unzipSync(uint8Array)

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
