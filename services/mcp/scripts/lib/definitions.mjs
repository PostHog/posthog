/**
 * MCP definition discovery and schema path resolution.
 *
 * Shared by generate-orval-schemas.mjs and generate-tools.ts.
 * MCP-specific: knows about services/mcp/definitions/ and products/*\/mcp/.
 */
import fs from 'node:fs'
import path from 'node:path'
import { parse as parseYaml } from 'yaml'

/**
 * Resolve the OpenAPI schema path, respecting OPENAPI_SCHEMA_PATH env override.
 *
 * @param {string} repoRoot - absolute path to the repository root
 * @returns {string} absolute path to the OpenAPI JSON schema file
 */
export function resolveSchemaPath(repoRoot) {
    const defaultPath = path.resolve(repoRoot, 'frontend', 'tmp', 'openapi.json')
    return process.env.OPENAPI_SCHEMA_PATH ? path.resolve(repoRoot, process.env.OPENAPI_SCHEMA_PATH) : defaultPath
}

/**
 * Discover all MCP YAML definition files.
 *
 * Scans:
 * - services/mcp/definitions/*.yaml — core MCP tool configs
 * - products/*\/mcp/*.yaml — per-product tool configs
 *
 * @param {object} opts
 * @param {string} opts.definitionsDir - absolute path to services/mcp/definitions/
 * @param {string} opts.productsDir - absolute path to the products/ directory
 * @returns {{ moduleName: string, filePath: string }[]}
 */
export function discoverDefinitions({ definitionsDir, productsDir }) {
    const sources = []

    if (fs.existsSync(definitionsDir)) {
        for (const file of fs.readdirSync(definitionsDir)) {
            if (!file.endsWith('.yaml') && !file.endsWith('.yml')) {
                continue
            }
            sources.push({
                moduleName: file.replace(/\.ya?ml$/, ''),
                filePath: path.join(definitionsDir, file),
            })
        }
    }

    if (fs.existsSync(productsDir)) {
        for (const product of fs.readdirSync(productsDir, { withFileTypes: true })) {
            if (!product.isDirectory() || product.name.startsWith('_')) {
                continue
            }
            const mcpDir = path.join(productsDir, product.name, 'mcp')
            if (!fs.existsSync(mcpDir)) {
                continue
            }
            for (const file of fs.readdirSync(mcpDir)) {
                if (!file.endsWith('.yaml') && !file.endsWith('.yml')) {
                    continue
                }
                const moduleName =
                    file === 'tools.yaml' || file === 'tools.yml' ? product.name : file.replace(/\.ya?ml$/, '')
                sources.push({
                    moduleName,
                    filePath: path.join(mcpDir, file),
                })
            }
        }
    }

    return sources.sort((a, b) => a.moduleName.localeCompare(b.moduleName))
}

/**
 * Returns true if the parsed YAML has the shape of a query wrapper config
 * (has `wrappers` key instead of `tools`).
 */
export function isQueryWrappersConfig(parsed) {
    return typeof parsed === 'object' && parsed !== null && 'wrappers' in parsed && !('tools' in parsed)
}

/**
 * Returns true if the parsed YAML has the shape of a category config
 * (has `tools` key instead of `wrappers`).
 */
export function isToolsConfig(parsed) {
    return typeof parsed === 'object' && parsed !== null && 'tools' in parsed
}

/**
 * Tools on one operation share one Orval body schema, so only exclusions that every enabled tool reading it shares may leave it.
 * An input_schema tool brings its own schema and never reads the Orval body.
 * @param {Iterable<{ enabled?: boolean, operation?: string, input_schema?: string, exclude_params?: string[] }>} tools
 * @returns {Map<string, string[]>}
 */
export function sharedSchemaExclusions(tools) {
    /** @type {Map<string, string[]>} */
    const shared = new Map()
    for (const tool of tools) {
        if (!tool?.enabled || !tool?.operation || tool.input_schema) {
            continue
        }
        const excluded = tool.exclude_params ?? []
        const previous = shared.get(tool.operation)
        shared.set(tool.operation, previous ? previous.filter((field) => excluded.includes(field)) : excluded)
    }
    for (const [operation, fields] of shared) {
        if (fields.length === 0) {
            shared.delete(operation)
        }
    }
    return shared
}

export function parseToolDefinition(filePath) {
    const tools = Object.values(parseYaml(fs.readFileSync(filePath, 'utf-8'))?.tools ?? {})
    const operationIds = new Set(tools.filter((tool) => tool?.enabled && tool?.operation).map((tool) => tool.operation))
    return { operationIds, schemaExclusions: sharedSchemaExclusions(tools) }
}
