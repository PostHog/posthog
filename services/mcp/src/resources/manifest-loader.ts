import type { ContextMillManifest } from './manifest-types'

/**
 * Validate a context-mill manifest object
 */
export function loadContextMillManifest(manifest: unknown): ContextMillManifest {
    if (!manifest || typeof manifest !== 'object') {
        throw new Error('Context-mill manifest must be an object')
    }

    const m = manifest as Record<string, unknown>

    if (!m.version || typeof m.version !== 'string') {
        throw new Error('Context-mill manifest is missing required "version" field')
    }

    if (!Array.isArray(m.resources)) {
        throw new Error('Context-mill manifest is missing "resources" array')
    }

    // Validate each resource has required fields
    for (const entry of m.resources) {
        if (!entry || typeof entry !== 'object') {
            throw new Error('Each resource must be an object')
        }

        const r = entry as Record<string, unknown>
        if (!r.id || typeof r.id !== 'string') {
            throw new Error('Resource is missing required "id" field')
        }
        if (!r.name || typeof r.name !== 'string') {
            throw new Error(`Resource "${r.id}" is missing required "name" field`)
        }
        if (!r.uri || typeof r.uri !== 'string') {
            throw new Error(`Resource "${r.id}" is missing required "uri" field`)
        }
        if (!r.resource || typeof r.resource !== 'object') {
            throw new Error(`Resource "${r.id}" is missing required "resource" field`)
        }
        const res = r.resource as Record<string, unknown>
        if (!res.mimeType || typeof res.mimeType !== 'string') {
            throw new Error(`Resource "${r.id}" resource is missing required "mimeType" field`)
        }
        if (!res.description || typeof res.description !== 'string') {
            throw new Error(`Resource "${r.id}" resource is missing required "description" field`)
        }
        if (!res.text || typeof res.text !== 'string') {
            throw new Error(`Resource "${r.id}" resource is missing required "text" field`)
        }
    }

    return manifest as ContextMillManifest
}
