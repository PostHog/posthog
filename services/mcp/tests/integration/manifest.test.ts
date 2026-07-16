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

        // Verify we have actual resources
        expect(validatedManifest.resources.length).toBeGreaterThan(0)

        // Verify each resource has required fields and its file exists in archive
        for (const entry of validatedManifest.resources) {
            expect(entry.id).toBeTruthy()
            expect(entry.name).toBeTruthy()
            expect(entry.resource).toBeTruthy()
            expect(entry.resource.mimeType).toBeTruthy()
            expect(entry.resource.text).toBeTruthy()
            if (entry.file) {
                expect(archive[entry.file]).toBeTruthy()
            }
        }
    }, 30000)
})
