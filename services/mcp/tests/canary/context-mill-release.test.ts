import { describe, expect, it } from 'vitest'

import { fetchContextMillResources, filterValidEntries, loadManifestFromArchive } from '@/resources/internals'

/**
 * Canary against the live context-mill GitHub release.
 *
 * The integration suite serves a pinned fixture archive instead of this
 * release (see `tests/fixtures/context-mill-archive.ts`), so it is
 * deterministic but blind to an upstream release that the MCP server can no
 * longer read. This canary is the safety net: it downloads the current asset
 * and checks that the server can still unzip it, validate its manifest, and
 * serve entries from it.
 *
 * Opt in with `CONTEXT_MILL_LIVE_TEST=1`, so a GitHub outage or a rate limit
 * never fails a PR. `.github/workflows/ci-context-mill-canary.yml` runs it on
 * master and on a schedule.
 */
describe.skipIf(!process.env.CONTEXT_MILL_LIVE_TEST)('live context-mill release', () => {
    it('unzips, validates, and serves entries from the published archive', async () => {
        const archive = await fetchContextMillResources()
        expect(Object.keys(archive).length).toBeGreaterThan(0)

        const manifest = loadManifestFromArchive(archive)
        expect(manifest.version).toBe('1.0')
        expect(manifest.resources.length).toBeGreaterThan(0)

        // The MCP server serves entries via filterValidEntries, which drops any
        // entry whose backing file is missing from the archive. Validate the
        // resources as actually served rather than asserting every manifest
        // file is bundled.
        const servedEntries = filterValidEntries(manifest.resources, archive)
        expect(servedEntries.length).toBeGreaterThan(0)

        for (const entry of servedEntries) {
            expect(entry.id).toBeTruthy()
            expect(entry.name).toBeTruthy()
            expect(entry.resource.mimeType).toBeTruthy()
            expect(entry.resource.text).toBeTruthy()
        }
    }, 30000)
})
