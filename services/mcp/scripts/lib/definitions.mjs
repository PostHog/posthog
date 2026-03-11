/**
 * MCP definition discovery and schema path resolution.
 *
 * Shared by generate-orval-schemas.mjs and generate-tools.ts.
 * MCP-specific: knows about services/mcp/definitions/ and products/*\/mcp/.
 */
import fs from 'node:fs'
import path from 'node:path'

const PRODUCT_DEFINITION_FILES = new Set(['tools.yaml', 'tools.yml'])
const PRODUCT_DEFINITION_FILE_DISPLAY = 'tools.yaml or tools.yml'

export function isYamlFile(fileName) {
    return fileName.endsWith('.yaml') || fileName.endsWith('.yml')
}

function formatProductDir(productName) {
    return `products/${productName}/mcp`
}

function validateProductDefinitionFiles(productName, files) {
    if (files.length === 0) {
        return
    }

    if (files.length > 1) {
        throw new Error(
            `Invalid MCP definitions in ${formatProductDir(productName)}: expected exactly one YAML file named ` +
                `"${PRODUCT_DEFINITION_FILE_DISPLAY}", found ${files.join(', ')}`
        )
    }

    const [file] = files
    if (!PRODUCT_DEFINITION_FILES.has(file)) {
        throw new Error(
            `Invalid MCP definition filename in ${formatProductDir(productName)}: expected ` +
                `"${PRODUCT_DEFINITION_FILE_DISPLAY}", found "${file}"`
        )
    }
}

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
 * - products/*\/mcp/tools.yaml or tools.yml — per-product tool configs
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
            if (!isYamlFile(file)) {
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
            const yamlFiles = fs.readdirSync(mcpDir).filter((file) => isYamlFile(file))
            validateProductDefinitionFiles(product.name, yamlFiles)

            if (yamlFiles.length === 1) {
                const [file] = yamlFiles
                sources.push({
                    moduleName: product.name,
                    filePath: path.join(mcpDir, file),
                })
            }
        }
    }

    return sources
}
