import { readFileSync } from 'fs'
import { join } from 'path'
import { describe, expect, it } from 'vitest'

import { loadContextMillManifest } from '@/resources/manifest-loader'

describe('Context-Mill Manifest', () => {
    it('should parse and validate the manifest from fixture', () => {
        const manifestJson = readFileSync(join(__dirname, '../fixtures/manifest.json'), 'utf-8')
        const manifest = JSON.parse(manifestJson)

        // Validate manifest structure using our loader (throws if invalid)
        const validatedManifest = loadContextMillManifest(manifest)

        // Verify expected structure
        expect(validatedManifest.version).toBe('1.0')
        expect(Array.isArray(validatedManifest.resources)).toBe(true)

        // Verify we have actual resources
        expect(validatedManifest.resources.length).toBeGreaterThan(0)

        // Verify each resource has required fields
        for (const entry of validatedManifest.resources) {
            expect(entry.id).toBeTruthy()
            expect(entry.name).toBeTruthy()
            expect(entry.resource).toBeTruthy()
            expect(entry.resource.mimeType).toBeTruthy()
            expect(entry.resource.text).toBeTruthy()
        }
    })

    it('should include resources with and without file references', () => {
        const manifestJson = readFileSync(join(__dirname, '../fixtures/manifest.json'), 'utf-8')
        const manifest = JSON.parse(manifestJson)
        const validatedManifest = loadContextMillManifest(manifest)

        const withFile = validatedManifest.resources.filter((r) => r.file)
        const withoutFile = validatedManifest.resources.filter((r) => !r.file)

        expect(withFile.length).toBeGreaterThan(0)
        expect(withoutFile.length).toBeGreaterThan(0)
    })
})
