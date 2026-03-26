/**
 * MCP definition discovery and schema path resolution.
 *
 * Shared by generate-orval-schemas.mjs and generate-tools.ts.
 * MCP-specific: knows about services/mcp/definitions/ and products/*\/mcp/.
 */
import fs from 'node:fs'
import path from 'node:path'

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
