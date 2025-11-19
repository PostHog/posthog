import { type Unzipped, strFromU8 } from 'fflate'

import type { ResourceManifest } from './manifest-types'

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
