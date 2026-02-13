#!/usr/bin/env tsx
/**
 * Scaffolds YAML tool definitions from the OpenAPI schema.
 *
 * Reads the OpenAPI spec and generates starter YAML files with
 * all discovered operations set to `enabled: false`. Developers
 * then enable the ones they want and add MCP-specific config.
 *
 * Usage:
 *   pnpm scaffold-yaml --tag actions
 *   pnpm scaffold-yaml --path /api/projects/{project_id}/actions/
 *   pnpm scaffold-yaml --tag actions --update definitions/actions.yaml
 */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { parse as parseYaml, stringify as stringifyYaml } from 'yaml'

const OPENAPI_PATH = path.resolve(__dirname, '../../../frontend/tmp/openapi.json')
const DEFINITIONS_DIR = path.resolve(__dirname, '../definitions')

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

interface ExistingTool {
    operation: string
    enabled: boolean
    [key: string]: unknown
}

interface ExistingYaml {
    category?: string
    feature?: string
    url_prefix?: string
    tools?: Record<string, ExistingTool>
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
    // actions_list → actions-list, actions_retrieve → actions-retrieve
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

function generateYaml(ops: DiscoveredOperation[], tag: string): string {
    const tools: Record<string, unknown> = {}

    for (const op of ops) {
        const toolName = operationIdToToolName(op.operationId)
        tools[toolName] = {
            operation: op.operationId,
            enabled: false,
            // title: '',
            // description: '',
            // scopes: [],
            // annotations: { readOnly: true, destructive: false, idempotent: true },
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

function updateYaml(existingPath: string, ops: DiscoveredOperation[]): string {
    const existingContent = fs.readFileSync(existingPath, 'utf-8')
    const existing = parseYaml(existingContent) as ExistingYaml
    const existingTools = existing.tools ?? {}
    const existingOperations = new Set(Object.values(existingTools).map((t) => t.operation))

    const newOps = ops.filter((op) => !existingOperations.has(op.operationId))

    if (newOps.length === 0) {
        return existingContent
    }

    // Append new operations as YAML comments (enabled: false)
    let updated = existingContent.trimEnd() + '\n\n    # New operations discovered by scaffold:\n'
    for (const op of newOps) {
        const toolName = operationIdToToolName(op.operationId)
        updated += `    # ${toolName}:\n`
        updated += `    #     operation: ${op.operationId}\n`
        updated += `    #     enabled: false\n`
        if (op.description) {
            updated += `    #     # ${op.description}\n`
        }
        updated += `\n`
    }

    return updated
}

// ------------------------------------------------------------------
// CLI
// ------------------------------------------------------------------

function main(): void {
    const args = process.argv.slice(2)
    let tag: string | undefined
    let pathPrefix: string | undefined
    let updatePath: string | undefined

    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--tag' && args[i + 1]) {
            tag = args[++i]
        } else if (args[i] === '--path' && args[i + 1]) {
            pathPrefix = args[++i]
        } else if (args[i] === '--update' && args[i + 1]) {
            updatePath = args[++i]
        }
    }

    if (!tag && !pathPrefix) {
        console.error('Usage: scaffold-yaml --tag <tag> [--update <file>]')
        console.error('       scaffold-yaml --path <prefix> [--update <file>]')

        // List available tags
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

    const ops = tag ? findOperationsByTag(spec, tag) : findOperationsByPath(spec, pathPrefix!)

    if (ops.length === 0) {
        console.error(`No operations found for ${tag ? `tag "${tag}"` : `path "${pathPrefix}"`}`)
        process.exit(1)
    }

    process.stdout.write(`Found ${ops.length} operation(s)\n`)

    if (updatePath) {
        const fullPath = path.resolve(DEFINITIONS_DIR, updatePath)
        if (!fs.existsSync(fullPath)) {
            console.error(`File not found: ${fullPath}`)
            process.exit(1)
        }
        const result = updateYaml(fullPath, ops)
        fs.writeFileSync(fullPath, result)
        process.stdout.write(`Updated ${fullPath}\n`)
    } else {
        process.stdout.write(generateYaml(ops, tag ?? 'unknown') + '\n')
    }
}

main()
