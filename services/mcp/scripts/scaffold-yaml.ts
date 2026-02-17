#!/usr/bin/env tsx
/**
 * Scaffolds YAML tool definitions from the OpenAPI schema.
 *
 * Discovers operations by matching URL paths containing /{product}/,
 * same approach as frontend/bin/generate-openapi-types.mjs.
 *
 * Idempotent: re-running on an existing file only adds newly discovered
 * operations and removes stale ones. All hand-authored config is preserved.
 *
 * Usage:
 *   pnpm scaffold-yaml --product actions
 *   pnpm scaffold-yaml --product error_tracking --output ../../products/error_tracking/mcp/tools.yaml
 *   pnpm scaffold-yaml --path /api/projects/{project_id}/actions/
 *   pnpm scaffold-yaml --sync-all
 */
import { execSync } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { parse as parseYaml, stringify as stringifyYaml } from 'yaml'

import { CategoryConfigSchema, type ToolConfig } from './yaml-config-schema'

const MCP_ROOT = path.resolve(__dirname, '..')
const REPO_ROOT = path.resolve(MCP_ROOT, '../..')
const PRODUCTS_DIR = path.resolve(REPO_ROOT, 'products')
const OPENAPI_PATH = path.resolve(REPO_ROOT, 'frontend/tmp/openapi.json')
const DEFINITIONS_DIR = path.resolve(MCP_ROOT, 'definitions')

// ------------------------------------------------------------------
// Types
// ------------------------------------------------------------------

interface OpenApiOperation {
    operationId: string
    parameters?: Array<{ in: string; name: string }>
    summary?: string
    description?: string
}

interface OpenApiSpec {
    paths: Record<string, Record<string, OpenApiOperation>>
}

interface DiscoveredOperation {
    operationId: string
    method: string
    path: string
    description?: string | undefined
}

const YAML_HEADER = `# MCP tool definition — tool entries are scaffolded from the OpenAPI schema.
# The tool list and operation IDs are kept in sync automatically:
#   pnpm --filter=@posthog/mcp run scaffold-yaml -- --sync-all
#
# To enable a tool, set enabled: true and add required scopes + annotations.
# All other fields (title, description, enrich_url, etc.) are yours to configure.
`

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function formatWithPrettier(filePaths: string[]): void {
    if (filePaths.length === 0) {
        return
    }
    const quoted = filePaths.map((f) => `"${f}"`).join(' ')
    try {
        execSync(`pnpm exec prettier --write ${quoted}`, { stdio: 'pipe', cwd: REPO_ROOT })
    } catch {
        // Not critical — prettier may not be available in all environments
    }
}

function loadOpenApi(): OpenApiSpec {
    if (!fs.existsSync(OPENAPI_PATH)) {
        console.error(`OpenAPI schema not found at ${OPENAPI_PATH}. Run \`hogli build:openapi-schema\` first.`)
        process.exit(1)
    }
    return JSON.parse(fs.readFileSync(OPENAPI_PATH, 'utf-8')) as OpenApiSpec
}

function operationIdToToolName(operationId: string): string {
    return operationId.replace(/_/g, '-')
}

/**
 * Find operations whose URL path contains /{product}/ — same approach
 * as frontend/bin/generate-openapi-types.mjs matchUrlToProduct().
 */
function findOperationsByProduct(spec: OpenApiSpec, product: string): DiscoveredOperation[] {
    const ops: DiscoveredOperation[] = []
    const httpMethods = new Set(['get', 'post', 'put', 'patch', 'delete'])
    const needle = `/${product}/`

    for (const [urlPath, methods] of Object.entries(spec.paths)) {
        if (!urlPath.toLowerCase().replace(/-/g, '_').includes(needle)) {
            continue
        }

        for (const [method, op] of Object.entries(methods)) {
            if (!httpMethods.has(method) || !op?.operationId) {
                continue
            }

            ops.push({
                operationId: op.operationId,
                method: method.toUpperCase(),
                path: urlPath,
                description: op.summary || op.description,
            })
        }
    }

    return ops
}

function findOperationsByPath(spec: OpenApiSpec, pathPrefix: string): DiscoveredOperation[] {
    const ops: DiscoveredOperation[] = []
    const httpMethods = new Set(['get', 'post', 'put', 'patch', 'delete'])

    for (const [urlPath, methods] of Object.entries(spec.paths)) {
        if (!urlPath.startsWith(pathPrefix)) {
            continue
        }

        for (const [method, op] of Object.entries(methods)) {
            if (!httpMethods.has(method) || !op?.operationId) {
                continue
            }

            ops.push({
                operationId: op.operationId,
                method: method.toUpperCase(),
                path: urlPath,
                description: op.summary || op.description,
            })
        }
    }

    return ops
}

/**
 * Deduplicate operations mounted at both /api/environments/ and /api/projects/.
 * Prefers /api/projects/ paths. Uses the clean base operationId (strips _N suffix).
 */
function deduplicateOperations(ops: DiscoveredOperation[]): DiscoveredOperation[] {
    const groups = new Map<string, DiscoveredOperation[]>()
    for (const op of ops) {
        const base = op.operationId.replace(/_\d+$/, '')
        const group = groups.get(base) ?? []
        group.push(op)
        groups.set(base, group)
    }

    const result: DiscoveredOperation[] = []
    for (const [base, group] of groups) {
        if (group.length === 1) {
            result.push(group[0]!)
            continue
        }
        // Prefer /api/projects/ over /api/environments/
        const preferred = group.find((op) => op.path.startsWith('/api/projects/')) ?? group[0]!
        // Use clean base operationId for the tool name
        result.push({ ...preferred, operationId: base })
    }

    return result
}

function generateFreshYaml(ops: DiscoveredOperation[], tag: string): string {
    const tools: Record<string, unknown> = {}

    for (const op of ops) {
        const toolName = operationIdToToolName(op.operationId)
        tools[toolName] = {
            operation: op.operationId,
            enabled: false,
        }
    }

    const yaml: Record<string, unknown> = {
        category: tag.charAt(0).toUpperCase() + tag.slice(1),
        feature: tag.replace(/-/g, '_'),
        url_prefix: `/${tag.replace(/_/g, '-')}`,
        tools,
    }

    return YAML_HEADER + stringifyYaml(yaml, { indent: 4, lineWidth: 120 })
}

/**
 * Merge OpenAPI operations into existing YAML. Preserves all MCP-specific
 * config (enabled, scopes, annotations, descriptions, enrich_url, etc.)
 * for operations already in the file. Adds new operations with enabled: false.
 * Removes operations no longer in OpenAPI.
 */
function mergeWithExisting(
    existingPath: string,
    ops: DiscoveredOperation[],
    tag: string
): { content: string; added: number; removed: number } {
    const parsed = parseYaml(fs.readFileSync(existingPath, 'utf-8'))
    const result = CategoryConfigSchema.safeParse(parsed)
    if (!result.success) {
        console.error(`Invalid existing YAML config in ${existingPath}:`)
        for (const issue of result.error.issues) {
            console.error(`  ${issue.path.join('.')}: ${issue.message}`)
        }
        process.exit(1)
    }
    const existing = result.data
    const existingTools = existing.tools

    // Map base operationId → existing tool entry (name + config)
    // Uses base (strip _N suffix) so dedup changes don't lose existing config
    const byBaseOperationId = new Map<string, { name: string; config: ToolConfig }>()
    for (const [name, config] of Object.entries(existingTools)) {
        const base = config.operation.replace(/_\d+$/, '')
        byBaseOperationId.set(base, { name, config })
    }

    const openApiBaseIds = new Set(ops.map((op) => op.operationId.replace(/_\d+$/, '')))
    const mergedTools: Record<string, unknown> = {}
    let added = 0

    // Add operations in OpenAPI order
    for (const op of ops) {
        const base = op.operationId.replace(/_\d+$/, '')
        const existing = byBaseOperationId.get(base)
        if (existing) {
            // Preserve MCP-specific config, update operationId to the deduplicated one
            mergedTools[existing.name] = { ...existing.config, operation: op.operationId }
        } else {
            mergedTools[operationIdToToolName(op.operationId)] = {
                operation: op.operationId,
                enabled: false,
            }
            added++
        }
    }

    // Count removed (in old YAML but not in OpenAPI anymore)
    const removed = [...byBaseOperationId.keys()].filter((id) => !openApiBaseIds.has(id)).length

    const merged = {
        category: existing.category ?? tag.charAt(0).toUpperCase() + tag.slice(1),
        feature: existing.feature ?? tag.replace(/-/g, '_'),
        url_prefix: existing.url_prefix ?? `/${tag.replace(/_/g, '-')}`,
        tools: mergedTools,
    }

    return { content: YAML_HEADER + stringifyYaml(merged, { indent: 4, lineWidth: 120 }), added, removed }
}

// ------------------------------------------------------------------
// CLI
// ------------------------------------------------------------------

/**
 * Re-scaffold all existing YAML definitions. Derives the product name
 * from the file/directory structure, finds matching OpenAPI operations
 * by URL path, and merges new/removed operations. Idempotent and
 * non-destructive. Runs prettier on written files so output matches
 * what lint-staged produces.
 */
function syncAll(spec: OpenApiSpec): void {
    interface SyncTarget {
        product: string
        filePath: string
    }

    const targets: SyncTarget[] = []

    // Core definitions — product derived from filename (e.g. actions.yaml → "actions")
    if (fs.existsSync(DEFINITIONS_DIR)) {
        for (const file of fs.readdirSync(DEFINITIONS_DIR)) {
            if (!file.endsWith('.yaml') && !file.endsWith('.yml')) {
                continue
            }
            targets.push({
                product: file.replace(/\.ya?ml$/, ''),
                filePath: path.join(DEFINITIONS_DIR, file),
            })
        }
    }

    // Product definitions — product derived from directory name
    if (fs.existsSync(PRODUCTS_DIR)) {
        for (const entry of fs.readdirSync(PRODUCTS_DIR, { withFileTypes: true })) {
            if (!entry.isDirectory() || entry.name.startsWith('_')) {
                continue
            }
            const mcpDir = path.join(PRODUCTS_DIR, entry.name, 'mcp')
            if (!fs.existsSync(mcpDir)) {
                continue
            }
            for (const file of fs.readdirSync(mcpDir)) {
                if (!file.endsWith('.yaml') && !file.endsWith('.yml')) {
                    continue
                }
                const product =
                    file === 'tools.yaml' || file === 'tools.yml' ? entry.name : file.replace(/\.ya?ml$/, '')
                targets.push({ product, filePath: path.join(mcpDir, file) })
            }
        }
    }

    if (targets.length === 0) {
        process.stdout.write('No existing YAML definitions found.\n')
        return
    }

    const writtenFiles: string[] = []

    for (const { product, filePath } of targets) {
        const rawOps = findOperationsByProduct(spec, product)
        const ops = deduplicateOperations(rawOps)
        if (ops.length === 0) {
            process.stdout.write(`${product}: no operations found in OpenAPI, skipping\n`)
            continue
        }
        const { content, added, removed } = mergeWithExisting(filePath, ops, product)
        fs.writeFileSync(filePath, content)
        writtenFiles.push(filePath)
        const parts = [`${ops.length} operation(s)`]
        if (added > 0) {
            parts.push(`${added} new`)
        }
        if (removed > 0) {
            parts.push(`${removed} removed`)
        }
        if (added === 0 && removed === 0) {
            parts.push('no changes')
        }
        process.stdout.write(`${product}: ${parts.join(', ')}\n`)
    }

    formatWithPrettier(writtenFiles)
}

function main(): void {
    const args = process.argv.slice(2)
    let product: string | undefined
    let pathPrefix: string | undefined
    let outputPath: string | undefined

    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--product' && args[i + 1]) {
            product = args[++i]
        } else if (args[i] === '--path' && args[i + 1]) {
            pathPrefix = args[++i]
        } else if (args[i] === '--output' && args[i + 1]) {
            outputPath = args[++i]
        }
    }

    if (args.includes('--sync-all')) {
        const spec = loadOpenApi()
        syncAll(spec)
        return
    }

    if (!product && !pathPrefix) {
        console.error('Usage: scaffold-yaml --product <name> [--output <file>]')
        console.error('       scaffold-yaml --path <prefix> [--output <file>]')
        console.error('       scaffold-yaml --sync-all')
        console.error('')
        console.error('Products are matched by URL path containing /<name>/.')
        process.exit(1)
    }

    const spec = loadOpenApi()
    const rawOps = product ? findOperationsByProduct(spec, product) : findOperationsByPath(spec, pathPrefix!)
    const ops = deduplicateOperations(rawOps)

    if (ops.length === 0) {
        console.error(`No operations found for ${product ? `product "${product}"` : `path "${pathPrefix}"`}`)
        process.exit(1)
    }

    const name = product ?? 'unknown'
    const resolvedOutput = outputPath
        ? path.resolve(MCP_ROOT, outputPath)
        : path.join(DEFINITIONS_DIR, `${name.replace(/-/g, '_')}.yaml`)

    if (fs.existsSync(resolvedOutput)) {
        const { content, added, removed } = mergeWithExisting(resolvedOutput, ops, name)
        fs.writeFileSync(resolvedOutput, content)
        const parts = [`${ops.length} operation(s)`]
        if (added > 0) {
            parts.push(`${added} new`)
        }
        if (removed > 0) {
            parts.push(`${removed} removed`)
        }
        if (added === 0 && removed === 0) {
            parts.push('no changes')
        }
        process.stdout.write(`${parts.join(', ')} — ${resolvedOutput}\n`)
    } else {
        fs.mkdirSync(path.dirname(resolvedOutput), { recursive: true })
        fs.writeFileSync(resolvedOutput, generateFreshYaml(ops, name))
        process.stdout.write(`${ops.length} operation(s) — created ${resolvedOutput}\n`)
    }

    formatWithPrettier([resolvedOutput])
}

main()
