import { strToU8, zipSync } from 'fflate'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchAndExtractEntries } from '@/resources/internals'
import type { ContextMillResource } from '@/resources/manifest-types'

const ARCHIVE_URL = 'http://127.0.0.1/skills-mcp-resources.zip'

function manifestEntry(id: string, file?: string): ContextMillResource {
    return {
        id,
        name: `name-${id}`,
        uri: `posthog://skills/${id}`,
        ...(file ? { file } : {}),
        resource: { mimeType: 'text/markdown', description: `desc-${id}`, text: `# ${id}` },
    }
}

function stubArchiveResponse(files: Record<string, Uint8Array>): void {
    const bytes = new Uint8Array(zipSync(files))
    vi.stubGlobal(
        'fetch',
        vi.fn(async () => new Response(bytes, { status: 200 }))
    )
}

describe('fetchAndExtractEntries', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
        vi.restoreAllMocks()
    })

    it('serves the manifest entries whose backing file is in the archive', async () => {
        vi.spyOn(console, 'warn').mockImplementation(() => {})
        const manifest = {
            version: '1.0',
            resources: [
                manifestEntry('bundled', 'skills/bundled.md'),
                manifestEntry('inline'),
                manifestEntry('missing', 'skills/missing.md'),
            ],
        }
        stubArchiveResponse({
            'manifest.json': strToU8(JSON.stringify(manifest)),
            'skills/bundled.md': strToU8('# bundled'),
        })

        const entries = await fetchAndExtractEntries(ARCHIVE_URL)

        expect(entries.map((entry) => entry.id)).toEqual(['bundled', 'inline'])
    })

    it('rejects an archive without a manifest', async () => {
        stubArchiveResponse({ 'skills/bundled.md': strToU8('# bundled') })

        await expect(fetchAndExtractEntries(ARCHIVE_URL)).rejects.toThrow('manifest.json not found in archive')
    })
})
