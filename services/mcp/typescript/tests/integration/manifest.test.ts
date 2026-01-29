import { strFromU8, unzipSync } from 'fflate'
import { describe, expect, it } from 'vitest'

import { CONTEXT_MILL_URL } from '@/resources/index'
import { loadContextMillManifest } from '@/resources/manifest-loader'

describe('Context-Mill Manifest Integration', () => {
    it('should fetch, unzip, and validate the manifest from GitHub releases', async () => {
        // Fetch the resources ZIP
        const response = await fetch(CONTEXT_MILL_URL)
        expect(response.ok).toBe(true)

        // Unzip the archive
        const arrayBuffer = await response.arrayBuffer()
        const uint8Array = new Uint8Array(arrayBuffer)
        const archive = unzipSync(uint8Array)

        // Verify archive is not empty
        expect(Object.keys(archive).length).toBeGreaterThan(0)

        // Verify manifest.json exists
        const manifestData = archive['manifest.json']
        expect(manifestData).toBeTruthy()
        if (!manifestData) {
            throw new Error('manifest.json not found in archive')
        }

        // Verify manifest is valid JSON
        const manifestJson = strFromU8(manifestData)
        const manifest = JSON.parse(manifestJson)
        expect(manifest).toBeTruthy()

        // Validate manifest structure using our loader (throws if invalid)
        const validatedManifest = loadContextMillManifest(manifest)

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
    }, 30000) // 30 second timeout for network request
})
