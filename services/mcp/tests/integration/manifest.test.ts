import { strFromU8, unzipSync, zipSync } from 'fflate'
import { describe, expect, it } from 'vitest'

import { loadContextMillManifest } from '@/resources/manifest-loader'

/**
 * Minimal valid context-mill manifest fixture.
 * Mirrors the structure served by the real GitHub releases ZIP
 * without requiring a live network call.
 */
const MANIFEST_FIXTURE = {
    version: '1.0',
    resources: [
        {
            id: 'test-resource',
            name: 'Test Resource',
            uri: 'posthog://resources/test-resource',
            file: 'test-resource.md',
            resource: {
                mimeType: 'text/markdown',
                description: 'A test resource',
                text: '# Test Resource\n\nThis is a test resource.',
            },
        },
        {
            id: 'inline-resource',
            name: 'Inline Resource',
            uri: 'posthog://resources/inline-resource',
            resource: {
                mimeType: 'text/plain',
                description: 'An inline resource without a file',
                text: 'Inline content here.',
            },
        },
    ],
}

/**
 * Build a ZIP archive in memory containing the manifest and resource files.
 */
function buildFixtureArchive(): Uint8Array {
    const encoder = new TextEncoder()
    const files: Record<string, Uint8Array> = {
        'manifest.json': encoder.encode(JSON.stringify(MANIFEST_FIXTURE)),
    }

    // Add files referenced by resources
    for (const entry of MANIFEST_FIXTURE.resources) {
        if (entry.file) {
            files[entry.file] = encoder.encode(entry.resource.text)
        }
    }

    return zipSync(files)
}

describe('Context-Mill Manifest Integration', () => {
    it('should unzip and validate the manifest from a ZIP archive', () => {
        const zipData = buildFixtureArchive()

        // Unzip the archive
        const archive = unzipSync(zipData)

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
    })
})
