import { describe, expect, it } from 'vitest'

import { getManifest } from '@/resources/kv-store'

describe('Context-Mill Manifest Integration', () => {
    it('should fetch and validate the manifest from GitHub releases', async () => {
        // No KV binding in this test — getManifest falls back to the origin fetch.
        const manifest = await getManifest({ MCP_KV: undefined })

        expect(manifest.version).toBeTruthy()
        expect(Array.isArray(manifest.resources)).toBe(true)
        expect(manifest.resources.length).toBeGreaterThan(0)

        for (const entry of manifest.resources) {
            expect(entry.id).toBeTruthy()
            expect(entry.name).toBeTruthy()
            expect(entry.uri).toBeTruthy()
            expect(entry.resource).toBeTruthy()
            expect(entry.resource.mimeType).toBeTruthy()
            // `text` is required by the manifest validator — for URL-shaped
            // entries the value is the download URL, which our `getResourceText`
            // helper detects and follows on read.
            expect(entry.resource.text).toBeTruthy()
        }
    }, 30000)
})
