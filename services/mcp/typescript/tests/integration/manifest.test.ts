import { strFromU8, unzipSync } from 'fflate'
import { describe, expect, it } from 'vitest'

import { loadManifest } from '@/resources/manifest-loader'

const EXAMPLES_MARKDOWN_URL = 'https://github.com/PostHog/examples/releases/latest/download/examples-mcp-resources.zip'

describe('Manifest Integration', () => {
    it('should fetch, unzip, and validate the manifest from GitHub releases', async () => {
        // Fetch the examples ZIP
        const response = await fetch(EXAMPLES_MARKDOWN_URL)
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
        const validatedManifest = loadManifest(archive)

        // Verify expected structure
        expect(validatedManifest.version).toBe('1.0')
        expect(Array.isArray(validatedManifest.resources.workflows)).toBe(true)
        expect(Array.isArray(validatedManifest.resources.docs)).toBe(true)
        expect(Array.isArray(validatedManifest.resources.prompts)).toBe(true)

        // Verify we have actual content
        expect(validatedManifest.resources.workflows.length).toBeGreaterThan(0)
        expect(validatedManifest.resources.prompts.length).toBeGreaterThan(0)

        // Verify templates if present
        if (validatedManifest.templates) {
            expect(Array.isArray(validatedManifest.templates)).toBe(true)
            expect(validatedManifest.templates.length).toBeGreaterThan(0)
        }

        // Verify workflow files exist in archive
        for (const workflow of validatedManifest.resources.workflows) {
            expect(archive[workflow.file]).toBeTruthy()
        }

        // Verify template files exist in archive (if templates use files)
        if (validatedManifest.templates) {
            for (const template of validatedManifest.templates) {
                for (const item of template.items) {
                    if (item.file) {
                        expect(archive[item.file]).toBeTruthy()
                    }
                }
            }
        }
    }, 30000) // 30 second timeout for network request
})
