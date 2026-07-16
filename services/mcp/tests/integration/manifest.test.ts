import { describe, expect, it } from 'vitest'

import { fetchContextMillResources, loadManifestFromArchive } from '@/resources/internals'

describe('Context-Mill Manifest Integration', () => {
    it('should fetch, unzip, and validate the manifest from GitHub releases', async () => {
        const archive = await fetchContextMillResources()

        // Verify archive is not empty
        expect(Object.keys(archive).length).toBeGreaterThan(0)

        // Verify manifest.json exists and validates
        const validatedManifest = loadManifestFromArchive(archive)

        // Verify expected structure
        expect(validatedManifest.version).toBe('1.0')
        expect(Array.isArray(validatedManifest.resources)).toBe(true)

        // Context-mill may list resources distributed separately from the aggregate archive.
        const availableResources = validatedManifest.resources.filter((entry) => !entry.file || archive[entry.file])

        // Verify the archive contains actual resources
        expect(availableResources.length).toBeGreaterThan(0)

        // Verify each available resource has required fields
        for (const entry of availableResources) {
            expect(entry.id).toBeTruthy()
            expect(entry.name).toBeTruthy()
            expect(entry.resource).toBeTruthy()
            expect(entry.resource.mimeType).toBeTruthy()
            expect(entry.resource.text).toBeTruthy()
        }
    }, 30000)
})
