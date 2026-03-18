#!/usr/bin/env tsx
/**
 * Lint check: ensures MCP tool names don't exceed the length limit.
 *
 * Some MCP clients (notably Cursor) enforce a 60-character combined limit on
 * server_name + tool_name. With server name "posthog" (7 chars), tool names
 * must be <= 52 chars.
 *
 * Usage:
 *   pnpm --filter=@posthog/mcp lint-tool-names
 */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { parse as parseYaml } from 'yaml'

import { discoverDefinitions } from './lib/definitions.mjs'
import { CategoryConfigSchema, MAX_TOOL_NAME_LENGTH } from './yaml-config-schema'

const MCP_ROOT = path.resolve(__dirname, '..')
const REPO_ROOT = path.resolve(MCP_ROOT, '../..')
const DEFINITIONS_DIR = path.resolve(MCP_ROOT, 'definitions')
const PRODUCTS_DIR = path.resolve(REPO_ROOT, 'products')

/** Pre-existing tools that exceed the limit. Remove entries as they get renamed. */
const PREEXISTING_EXCEPTIONS: Set<string> = new Set(['warehouse-saved-queries-revert-materialization-create'])

function main(): void {
    const definitions = discoverDefinitions({ definitionsDir: DEFINITIONS_DIR, productsDir: PRODUCTS_DIR })
    const violations: { file: string; tool: string; length: number }[] = []
    let hasErrors = false

    for (const def of definitions) {
        const label = path.relative(REPO_ROOT, def.filePath)
        const content = fs.readFileSync(def.filePath, 'utf-8')
        const parsed = parseYaml(content)
        const result = CategoryConfigSchema.safeParse(parsed)
        if (!result.success) {
            process.stderr.write(`Error: ${label} failed schema validation: ${result.error.message}\n`)
            hasErrors = true
            process.exitCode = 1
            continue
        }
        for (const [name, config] of Object.entries(result.data.tools)) {
            if (!config.enabled) {
                continue
            }
            if (name.length > MAX_TOOL_NAME_LENGTH && !PREEXISTING_EXCEPTIONS.has(name)) {
                violations.push({ file: label, tool: name, length: name.length })
            }
        }
    }

    if (violations.length === 0) {
        if (!hasErrors) {
            process.stdout.write(`All enabled tool names are within the ${MAX_TOOL_NAME_LENGTH}-char limit.\n`)
        }
        return
    }

    process.stderr.write(
        `Found ${violations.length} tool name(s) exceeding ${MAX_TOOL_NAME_LENGTH}-char limit ` +
            `(Cursor enforces a 60-char combined server+tool name limit, "posthog" is 7 chars):\n\n`
    )
    for (const v of violations) {
        process.stderr.write(`  ${v.tool} (${v.length} chars) in ${v.file}\n`)
    }
    process.stderr.write(`\nTo fix: shorten the tool name in the YAML config.\n`)
    process.exitCode = 1
}

main()
