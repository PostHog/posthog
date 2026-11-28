import fs from 'node:fs'
import path from 'node:path'

/**
 * Find an operation by operationId. When the same endpoint exists at both
 * /api/environments/ and /api/projects/, prefers /api/projects/.
 * Prefers an exact operationId match, then falls back to matching _N deduplicated
 * variants (e.g. issues_list matches issues_list_2) for backward compatibility.
 */
export function findOperation(spec, operationId) {
    const base = operationId.replace(/_\d+$/, '')
    let exactFallback
    let baseFallback
    let baseProject
    for (const [urlPath, methods] of Object.entries(spec.paths)) {
        for (const [method, operation] of Object.entries(methods)) {
            if (!operation?.operationId) {
                continue
            }
            const resolved = { method: method.toUpperCase(), path: urlPath, operation }
            if (operation.operationId === operationId) {
                if (urlPath.startsWith('/api/projects/')) {
                    return resolved
                }
                exactFallback ??= resolved
            } else if (operation.operationId.replace(/_\d+$/, '') === base) {
                if (urlPath.startsWith('/api/projects/')) {
                    baseProject ??= resolved
                } else {
                    baseFallback ??= resolved
                }
            }
        }
    }
    return exactFallback ?? baseProject ?? baseFallback
}

/**
 * Resolve a tool description from either an inline `description` string or a
 * `description_file` path (resolved relative to `yamlDir`). Returns the
 * fallback when neither is set.
 */
export function resolveDescription(config, yamlDir, fallback) {
    if (config.description_file) {
        const filePath = path.resolve(yamlDir, config.description_file)
        if (!fs.existsSync(filePath)) {
            throw new Error(`description_file not found: ${filePath}`)
        }
        return fs.readFileSync(filePath, 'utf8').trim()
    }
    return config.description?.trim() || fallback
}

export function resolveDocumentation(config, operation, yamlFile, repoRoot) {
    const original = operation.description?.trim() || operation.summary?.trim() || ''
    const description = resolveDescription(config, path.dirname(yamlFile), original)
    const layers = original
        ? [
              {
                  role: 'original',
                  text: original,
                  source: operation['x-documentation-source'] ?? {
                      kind: 'openapi',
                      file: 'openapi.json',
                      pointer: operation.operationId,
                  },
              },
          ]
        : []
    if (config.description || config.description_file) {
        layers.push({
            role: 'override',
            text: description,
            source: {
                kind: config.description_file ? 'description_file' : 'mcp_yaml',
                file: path.relative(
                    repoRoot,
                    config.description_file ? path.resolve(path.dirname(yamlFile), config.description_file) : yamlFile
                ),
            },
        })
    }
    return { description, layers }
}
