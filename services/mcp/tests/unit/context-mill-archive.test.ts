import { strToU8, zipSync } from 'fflate'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchAndExtractEntries } from '@/resources/internals'
import type { ContextMillResource } from '@/resources/manifest-types'
import { SkillCatalog } from '@/skills/skill-catalog'

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

    it('serves the manifest entries whose backing file is in the archive and repacks the omnibus skills', async () => {
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
            'omnibus-instrument-logs.zip': zipSync({
                'SKILL.md': strToU8('---\nname: omnibus-instrument-logs\ndescription: Add logs.\n---\n\n# Add logs'),
                'references/go.md': strToU8('# Go'),
            }),
            'omnibus-querying-posthog-data.zip': zipSync({
                'SKILL.md': strToU8(
                    '---\n"name": omnibus-other\ndescription: Wrong name.\n---\n\nname: omnibus-querying-posthog-data\n'
                ),
            }),
        })

        const { entries, omnibusSkillsArchive } = await fetchAndExtractEntries(ARCHIVE_URL)

        expect(entries.map((entry) => entry.id)).toEqual(['bundled', 'inline'])
        const omnibus = SkillCatalog.fromZip(omnibusSkillsArchive!)
        expect(omnibus.listNames()).toEqual(['instrument-logs'])
        expect(omnibus.read('instrument-logs', 'references/go.md')).toContain('# Go')
        expect((await fetchAndExtractEntries(ARCHIVE_URL, false)).omnibusSkillsArchive).toBeNull()
    })

    it.each([
        ['corrupt', strToU8('not a zip')],
        ['oversized', zipSync({ 'SKILL.md': new Uint8Array(9 * 1024 * 1024) })],
        ['itself past the extraction limit', zipSync({ 'SKILL.md': [new Uint8Array(9 * 1024 * 1024), { level: 0 }] })],
    ])('serves the entries with no overlay when an omnibus zip is %s', async (_label, inner) => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
        stubArchiveResponse({
            'manifest.json': strToU8(JSON.stringify({ version: '1.0', resources: [manifestEntry('inline')] })),
            'omnibus-instrument-logs.zip': inner,
        })

        const { entries, omnibusSkillsArchive } = await fetchAndExtractEntries(ARCHIVE_URL)

        expect(entries.map((entry) => entry.id)).toEqual(['inline'])
        expect(omnibusSkillsArchive).toBeNull()
        expect(consoleError).toHaveBeenCalledTimes(1)
    })

    it('rejects an archive without a manifest', async () => {
        stubArchiveResponse({ 'skills/bundled.md': strToU8('# bundled') })

        await expect(fetchAndExtractEntries(ARCHIVE_URL)).rejects.toThrow('manifest.json not found in archive')
    })
})
