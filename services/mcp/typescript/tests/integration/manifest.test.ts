import { strFromU8, unzipSync } from 'fflate'
import { describe, expect, it } from 'vitest'

import { SKILLS_RESOURCES_URL } from '@/resources/index'
import { loadSkillsManifest } from '@/resources/manifest-loader'

describe('Skills Manifest Integration', () => {
    it('should fetch, unzip, and validate the skills manifest from GitHub releases', async () => {
        // Fetch the skills ZIP
        const response = await fetch(SKILLS_RESOURCES_URL)
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
        const validatedManifest = loadSkillsManifest(manifest)

        // Verify expected structure
        expect(validatedManifest.version).toBe('1.0')
        expect(Array.isArray(validatedManifest.skills)).toBe(true)

        // Verify we have actual skills
        expect(validatedManifest.skills.length).toBeGreaterThan(0)

        // Verify each skill has required fields and its file exists in archive
        for (const skill of validatedManifest.skills) {
            expect(skill.id).toBeTruthy()
            expect(skill.name).toBeTruthy()
            expect(skill.file).toBeTruthy()
            expect(skill.downloadUrl).toBeTruthy()
            expect(archive[skill.file]).toBeTruthy()
        }
    }, 30000) // 30 second timeout for network request
})
