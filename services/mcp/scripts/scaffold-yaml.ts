#!/usr/bin/env tsx
/**
 * Scaffolds YAML tool definitions from the OpenAPI schema.
 *
 * Reads the OpenAPI spec and generates starter YAML files with
 * all discovered operations set to `enabled: false`. Idempotent:
 * re-running on an existing file only adds newly discovered operations.
 *
 * Usage:
 *   pnpm scaffold-yaml --tag actions
 *   pnpm scaffold-yaml --tag error_tracking --output ../../products/error_tracking/mcp/tools.yaml
 *   pnpm scaffold-yaml --path /api/projects/{project_id}/actions/
 */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { parse as parseYaml, stringify as stringifyYaml } from 'yaml'

const MCP_ROOT = path.resolve(__dirname, '..')
const REPO_ROOT = path.resolve(MCP_ROOT, '../..')
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
    tags?: string[]
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

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

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

function findOperationsByTag(spec: OpenApiSpec, tag: string): DiscoveredOperation[] {
    const ops: DiscoveredOperation[] = []
    const httpMethods = new Set(['get', 'post', 'put', 'patch', 'delete'])

    for (const [urlPath, methods] of Object.entries(spec.paths)) {
        for (const [method, op] of Object.entries(methods)) {
            if (!httpMethods.has(method) || !op?.operationId) {
                continue
            }

            const tags = op['x-explicit-tags'] ?? op.tags ?? []
            if (tags.some((t: string) => t.toLowerCase() === tag.toLowerCase())) {
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

    return stringifyYaml(yaml, { lineWidth: 120 })
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
    const existing = parseYaml(fs.readFileSync(existingPath, 'utf-8')) as Record<string, unknown>
    const existingTools = (existing.tools ?? {}) as Record<string, Record<string, unknown>>

    // Map base operationId → existing tool entry (name + config)
    // Uses base (strip _N suffix) so dedup changes don't lose existing config
    const byBaseOperationId = new Map<string, { name: string; config: Record<string, unknown> }>()
    for (const [name, config] of Object.entries(existingTools)) {
        if (config.operation) {
            const base = (config.operation as string).replace(/_\d+$/, '')
            byBaseOperationId.set(base, { name, config })
        }
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

    return { content: stringifyYaml(merged, { lineWidth: 120 }), added, removed }
}

// ------------------------------------------------------------------
// CLI
// ------------------------------------------------------------------

function main(): void {
    const args = process.argv.slice(2)
    let tag: string | undefined
    let pathPrefix: string | undefined
    let outputPath: string | undefined

    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--tag' && args[i + 1]) {
            tag = args[++i]
        } else if (args[i] === '--path' && args[i + 1]) {
            pathPrefix = args[++i]
        } else if (args[i] === '--output' && args[i + 1]) {
            outputPath = args[++i]
        }
    }

    if (!tag && !pathPrefix) {
        console.error('Usage: scaffold-yaml --tag <tag> [--output <file>]')
        console.error('       scaffold-yaml --path <prefix> [--output <file>]')

        const spec = loadOpenApi()
        const tagCounts = new Map<string, number>()
        for (const methods of Object.values(spec.paths)) {
            for (const op of Object.values(methods)) {
                if (!op?.operationId) {
                    continue
                }
                for (const t of (op['x-explicit-tags'] ?? op.tags ?? []) as string[]) {
                    tagCounts.set(t, (tagCounts.get(t) ?? 0) + 1)
                }
            }
        }

        console.error('\nAvailable tags:')
        const sorted = [...tagCounts.entries()].sort((a, b) => b[1] - a[1])
        for (const [t, count] of sorted.slice(0, 30)) {
            console.error(`  ${t} (${count} operations)`)
        }
        process.exit(1)
    }

    const spec = loadOpenApi()
    const rawOps = tag ? findOperationsByTag(spec, tag) : findOperationsByPath(spec, pathPrefix!)
    const ops = deduplicateOperations(rawOps)

    if (ops.length === 0) {
        console.error(`No operations found for ${tag ? `tag "${tag}"` : `path "${pathPrefix}"`}`)
        process.exit(1)
    }

    // Default output: services/mcp/definitions/<tag>.yaml
    const resolvedOutput = outputPath
        ? path.resolve(MCP_ROOT, outputPath)
        : path.join(DEFINITIONS_DIR, `${(tag ?? 'unknown').replace(/-/g, '_')}.yaml`)

    if (fs.existsSync(resolvedOutput)) {
        const { content, added, removed } = mergeWithExisting(resolvedOutput, ops, tag ?? 'unknown')
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
        fs.writeFileSync(resolvedOutput, generateFreshYaml(ops, tag ?? 'unknown'))
        process.stdout.write(`${ops.length} operation(s) — created ${resolvedOutput}\n`)
    }
}

main()
