#!/usr/bin/env tsx
/**
 * Scaffolds YAML tool definitions from the OpenAPI schema.
 *
 * Discovers operations using x-explicit-tags (priority 1) and URL path
 * substring matching (fallback), same approach as generate-openapi-types.mjs.
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
import { spawnSync } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { parse as parseYaml, stringify as stringifyYaml } from 'yaml'

import { CategoryConfigSchema } from './yaml-config-schema'

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
    deprecated?: boolean
    'x-explicit-tags'?: string[]
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
    try {
        spawnSync('pnpm', ['exec', 'oxfmt', '--no-error-on-unmatched-pattern', ...filePaths], {
            stdio: 'pipe',
            cwd: REPO_ROOT,
        })
    } catch {
        // Not critical — oxfmt may not be available in all environments
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
 * Find operations by x-explicit-tags — same priority-1 approach as
 * frontend/bin/generate-openapi-types.mjs resolveTagToProduct().
 * Tags are set via @extend_schema(tags=[...]) or auto-derived from
 * the ViewSet module path (products/<name>/backend/ → tag "<name>").
 */
function findOperationsByTag(spec: OpenApiSpec, product: string): DiscoveredOperation[] {
    const ops: DiscoveredOperation[] = []
    const httpMethods = new Set(['get', 'post', 'put', 'patch', 'delete'])

    for (const [urlPath, methods] of Object.entries(spec.paths)) {
        for (const [method, op] of Object.entries(methods)) {
            if (!httpMethods.has(method) || !op?.operationId || op.deprecated) {
                continue
            }
            const tags = op['x-explicit-tags'] ?? []
            if (tags.includes(product)) {
                ops.push({
                    operationId: op.operationId,
                    method: method.toUpperCase(),
                    path: urlPath,
                    description: op.summary || op.description,
                })
            }
        }
    }

    return ops
}

/**
 * Find operations whose URL path contains /{product}/ — fallback when
 * x-explicit-tags doesn't match, same as generate-openapi-types.mjs
 * matchUrlToProduct().
 */
function findOperationsByUrl(spec: OpenApiSpec, product: string): DiscoveredOperation[] {
    const ops: DiscoveredOperation[] = []
    const httpMethods = new Set(['get', 'post', 'put', 'patch', 'delete'])
    const needle = `/${product}/`

    for (const [urlPath, methods] of Object.entries(spec.paths)) {
        if (!urlPath.toLowerCase().replace(/-/g, '_').includes(needle)) {
            continue
        }

        for (const [method, op] of Object.entries(methods)) {
            if (!httpMethods.has(method) || !op?.operationId || op.deprecated) {
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
 * Find operations for a product. Uses the same priority as
 * frontend/bin/generate-openapi-types.mjs:
 * 1. x-explicit-tags match (covers ViewSets with @extend_schema(tags=[...])
 *    and ViewSets in products/<name>/backend/)
 * 2. URL path substring match (fallback for legacy endpoints)
 */
function findOperationsByProduct(spec: OpenApiSpec, product: string): DiscoveredOperation[] {
    const byTag = findOperationsByTag(spec, product)
    const byUrl = findOperationsByUrl(spec, product)

    // Merge, preferring tag-matched ops and deduping by operationId
    const seen = new Set(byTag.map((op) => op.operationId))
    const merged = [...byTag]
    for (const op of byUrl) {
        if (!seen.has(op.operationId)) {
            merged.push(op)
            seen.add(op.operationId)
        }
    }

    return merged
}

function findOperationsByPath(spec: OpenApiSpec, pathPrefix: string): DiscoveredOperation[] {
    const ops: DiscoveredOperation[] = []
    const httpMethods = new Set(['get', 'post', 'put', 'patch', 'delete'])

    for (const [urlPath, methods] of Object.entries(spec.paths)) {
        if (!urlPath.startsWith(pathPrefix)) {
            continue
        }

        for (const [method, op] of Object.entries(methods)) {
            if (!httpMethods.has(method) || !op?.operationId || op.deprecated) {
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
    tag: string,
    validOperationIds: Set<string>,
    subset = false
): { content: string; added: number; removed: number; updated: number; matched: number; unmatchedTools: string[] } {
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

    const openApiByBase = new Map(ops.map((op) => [op.operationId.replace(/_\d+$/, ''), op]))
    const mergedTools: Record<string, unknown> = {}
    let added = 0
    let removed = 0
    let updated = 0
    let matched = 0
    const unmatchedTools: string[] = []

    // Preserve existing tool order and hand-authored operation values
    for (const [name, config] of Object.entries(existingTools)) {
        const base = config.operation.replace(/_\d+$/, '')
        const op = openApiByBase.get(base)
        if (op) {
            // Keep the author's chosen operation variant if it still exists in
            // OpenAPI — they may have picked a specific _N suffix deliberately
            // (e.g. _2 for /api/projects/ path). Fall back to the deduped
            // operationId when their variant was renumbered or removed.
            const operation = validOperationIds.has(config.operation) ? config.operation : op.operationId
            mergedTools[name] = { ...config, operation }
            if (operation !== config.operation) {
                updated++
            }
            matched++
        } else if (subset) {
            // Subset files: keep unmatched tools (they may reference ops from a
            // different tag/URL space) but warn so missing tags get noticed
            mergedTools[name] = { ...config }
            unmatchedTools.push(`${name} (${config.operation})`)
        } else {
            unmatchedTools.push(`${name} (${config.operation})`)
            removed++
        }
    }

    // Append new operations (not yet in YAML) at the end — skip for subset files
    if (!subset) {
        const existingBaseIds = new Set(Object.values(existingTools).map((c) => c.operation.replace(/_\d+$/, '')))
        for (const op of ops) {
            const base = op.operationId.replace(/_\d+$/, '')
            if (!existingBaseIds.has(base)) {
                mergedTools[operationIdToToolName(op.operationId)] = {
                    operation: op.operationId,
                    enabled: false,
                }
                added++
            }
        }
    }

    const merged = {
        category: existing.category ?? tag.charAt(0).toUpperCase() + tag.slice(1),
        feature: existing.feature ?? tag.replace(/-/g, '_'),
        url_prefix: existing.url_prefix ?? `/${tag.replace(/_/g, '-')}`,
        tools: mergedTools,
    }

    return {
        content: YAML_HEADER + stringifyYaml(merged, { indent: 4, lineWidth: 120 }),
        added,
        removed,
        updated,
        matched,
        unmatchedTools,
    }
}

// ------------------------------------------------------------------
// CLI
// ------------------------------------------------------------------

/**
 * Re-scaffold all existing YAML definitions. Derives the product name
 * from the file/directory structure, finds matching OpenAPI operations
 * by URL path, and merges new/removed operations. Idempotent and
 * non-destructive. Runs oxfmt on written files so output matches
 * what lint-staged produces.
 */
function syncAll(spec: OpenApiSpec): void {
    interface SyncTarget {
        product: string
        filePath: string
        /** Subset files (filename != tools.yaml) only validate — no adds/removes */
        subset: boolean
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
                subset: false,
            })
        }
    }

    // Product definitions — product always from directory name.
    // Non-tools.yaml files are subset files that own a curated slice of the
    // product's operations (e.g. prompts.yaml inside llm_analytics/mcp/).
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
                const subset = file !== 'tools.yaml' && file !== 'tools.yml'
                targets.push({ product: entry.name, filePath: path.join(mcpDir, file), subset })
            }
        }
    }

    if (targets.length === 0) {
        process.stdout.write('No existing YAML definitions found.\n')
        return
    }

    const writtenFiles: string[] = []

    for (const { product, filePath, subset } of targets) {
        const rawOps = findOperationsByProduct(spec, product)
        const ops = deduplicateOperations(rawOps)
        if (ops.length === 0) {
            process.stdout.write(`${product}: no operations found in OpenAPI, skipping\n`)
            continue
        }
        const label = path.relative(REPO_ROOT, filePath)
        const validIds = new Set(rawOps.map((op) => op.operationId))
        const { content, added, removed, updated, matched, unmatchedTools } = mergeWithExisting(
            filePath,
            ops,
            product,
            validIds,
            subset
        )
        // Only write when there are semantic changes (avoids formatting-only rewrites)
        if (added > 0 || removed > 0 || updated > 0) {
            fs.writeFileSync(filePath, content)
            writtenFiles.push(filePath)
        }
        const total = matched + unmatchedTools.length
        const parts = [
            subset ? (total === 0 ? '0 tool(s)' : `${matched}/${total} tool(s) matched`) : `${ops.length} operation(s)`,
        ]
        if (added > 0) {
            parts.push(`${added} new`)
        }
        if (removed > 0) {
            parts.push(`${removed} removed`)
        }
        if (updated > 0) {
            parts.push(`${updated} operation ID(s) updated`)
        }
        if (added === 0 && removed === 0 && updated === 0 && unmatchedTools.length === 0) {
            parts.push('no changes')
        }
        process.stdout.write(`${label}: ${parts.join(', ')}\n`)
        if (unmatchedTools.length > 0) {
            process.stderr.write(
                `  ⚠ ${unmatchedTools.length} tool(s) not found in OpenAPI — add @extend_schema(tags=["${product}"]) to the ViewSet\n`
            )
            for (const tool of unmatchedTools) {
                process.stderr.write(`    - ${tool}\n`)
            }
        }
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
        console.error('--product discovers endpoints by x-explicit-tags first, then URL path fallback.')
        console.error('Uses the product folder name (underscores), e.g. error_tracking, workflows.')
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

    const validIds = new Set(rawOps.map((op) => op.operationId))

    if (fs.existsSync(resolvedOutput)) {
        const { content, added, removed } = mergeWithExisting(resolvedOutput, ops, name, validIds)
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
