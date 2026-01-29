import { type Unzipped, strFromU8 } from 'fflate'

import type { ResourceManifest, SkillsManifest } from './manifest-types'

const MANIFEST_FILENAME = 'manifest.json'

/**
 * Load and parse the manifest from the unzipped archive
 */
export function loadManifest(archive: Unzipped): ResourceManifest {
    const manifestData = archive[MANIFEST_FILENAME]

    if (!manifestData) {
        throw new Error(`Manifest file "${MANIFEST_FILENAME}" not found in archive`)
    }

    const manifestJson = strFromU8(manifestData)

    const manifest = JSON.parse(manifestJson) as ResourceManifest

    // Validate manifest version
    if (!manifest.version) {
        throw new Error('Manifest is missing required "version" field')
    }

    if (!manifest.resources || typeof manifest.resources !== 'object') {
        throw new Error('Manifest is missing required "resources" object')
    }

    if (!Array.isArray(manifest.resources.workflows)) {
        throw new Error('Manifest resources is missing "workflows" array')
    }

    if (!Array.isArray(manifest.resources.docs)) {
        throw new Error('Manifest resources is missing "docs" array')
    }

    if (!Array.isArray(manifest.resources.prompts)) {
        throw new Error('Manifest resources is missing "prompts" array')
    }

    return manifest
}

/**
 * Validate a skills manifest object
 */
export function loadSkillsManifest(manifest: unknown): SkillsManifest {
    if (!manifest || typeof manifest !== 'object') {
        throw new Error('Skills manifest must be an object')
    }

    const m = manifest as Record<string, unknown>

    if (!m.version || typeof m.version !== 'string') {
        throw new Error('Skills manifest is missing required "version" field')
    }

    if (!Array.isArray(m.skills)) {
        throw new Error('Skills manifest is missing "skills" array')
    }

    // Validate each skill has required fields
    for (const skill of m.skills) {
        if (!skill || typeof skill !== 'object') {
            throw new Error('Each skill must be an object')
        }

        const s = skill as Record<string, unknown>
        if (!s.id || typeof s.id !== 'string') {
            throw new Error('Skill is missing required "id" field')
        }
        if (!s.name || typeof s.name !== 'string') {
            throw new Error(`Skill "${s.id}" is missing required "name" field`)
        }
        if (!s.file || typeof s.file !== 'string') {
            throw new Error(`Skill "${s.id}" is missing required "file" field`)
        }
        if (!s.downloadUrl || typeof s.downloadUrl !== 'string') {
            throw new Error(`Skill "${s.id}" is missing required "downloadUrl" field`)
        }
    }

    return manifest as SkillsManifest
}
