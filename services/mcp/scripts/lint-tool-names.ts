#!/usr/bin/env tsx
/**
 * Lint check: ensures all MCP tool names satisfy length and pattern constraints.
 *
 * Validates tool names from three sources:
 *   1. YAML definitions (products and services/mcp/definitions)
 *   2. Handwritten JSON definitions (tool-definitions.json, tool-definitions-v2.json)
 *   3. Generated JSON definitions (generated-tool-definitions.json)
 *
 * Length: tool names must be <= 52 chars because some MCP clients (notably Cursor)
 * enforce a 60-char combined server_name + tool_name limit ("posthog" is 7 chars).
 *
 * Pattern: tool names must be lowercase kebab-case ([a-z0-9-], no leading/trailing
 * hyphens) for cross-client compatibility.
 *
 * Usage:
 *   pnpm --filter=@posthog/mcp lint-tool-names
 */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { parse as parseYaml } from 'yaml'

import { discoverDefinitions } from './lib/definitions.mjs'
import {
    CategoryConfigSchema,
    MAX_TOOL_NAME_LENGTH,
    QueryWrappersConfigSchema,
    TOOL_NAME_PATTERN,
} from './yaml-config-schema'

const MCP_ROOT = path.resolve(__dirname, '..')
const REPO_ROOT = path.resolve(MCP_ROOT, '../..')
const DEFINITIONS_DIR = path.resolve(MCP_ROOT, 'definitions')
const PRODUCTS_DIR = path.resolve(REPO_ROOT, 'products')
const SCHEMA_DIR = path.resolve(MCP_ROOT, 'schema')

type Violation = { source: string; tool: string; reason: string }

function validateToolName(name: string, source: string, violations: Violation[]): void {
    if (name.length > MAX_TOOL_NAME_LENGTH) {
        violations.push({ source, tool: name, reason: `${name.length} chars (max ${MAX_TOOL_NAME_LENGTH})` })
    }
    if (!TOOL_NAME_PATTERN.test(name)) {
        violations.push({
            source,
            tool: name,
            reason: `invalid pattern (must be lowercase kebab-case: ${TOOL_NAME_PATTERN})`,
        })
    }
}

function validateYamlDefinitions(violations: Violation[]): boolean {
    const definitions = discoverDefinitions({ definitionsDir: DEFINITIONS_DIR, productsDir: PRODUCTS_DIR })
    let hasErrors = false

    for (const def of definitions) {
        const label = path.relative(REPO_ROOT, def.filePath)
        const content = fs.readFileSync(def.filePath, 'utf-8')
        const parsed = parseYaml(content)
        // Try query wrappers config first, then category config
        const isQueryWrappers =
            typeof parsed === 'object' && parsed !== null && 'wrappers' in parsed && !('tools' in parsed)
        const result = isQueryWrappers
            ? QueryWrappersConfigSchema.safeParse(parsed)
            : CategoryConfigSchema.safeParse(parsed)
        if (!result.success) {
            process.stderr.write(`Error: ${label} failed schema validation: ${result.error.message}\n`)
            hasErrors = true
            process.exitCode = 1
            continue
        }
        const tools = isQueryWrappers
            ? (result.data as { wrappers: Record<string, { enabled: boolean }> }).wrappers
            : (result.data as { tools: Record<string, { enabled: boolean }> }).tools
        for (const [name, config] of Object.entries(tools)) {
            if (!config.enabled) {
                continue
            }
            validateToolName(name, label, violations)
        }
    }

    return hasErrors
}

function validateJsonDefinitions(fileName: string, violations: Violation[]): boolean {
    const filePath = path.resolve(SCHEMA_DIR, fileName)
    if (!fs.existsSync(filePath)) {
        return false
    }
    const label = path.relative(REPO_ROOT, filePath)
    const content = JSON.parse(fs.readFileSync(filePath, 'utf-8')) as Record<string, unknown>

    for (const name of Object.keys(content)) {
        validateToolName(name, label, violations)
    }
    return false
}

function main(): void {
    const violations: Violation[] = []
    let hasErrors = false

    hasErrors = validateYamlDefinitions(violations) || hasErrors

    for (const jsonFile of ['tool-definitions.json', 'tool-definitions-v2.json', 'generated-tool-definitions.json']) {
        hasErrors = validateJsonDefinitions(jsonFile, violations) || hasErrors
    }

    if (violations.length === 0) {
        if (!hasErrors) {
            process.stdout.write(
                `All tool names pass validation (max ${MAX_TOOL_NAME_LENGTH} chars, pattern ${TOOL_NAME_PATTERN}).\n`
            )
        }
        return
    }

    process.stderr.write(`Found ${violations.length} tool name violation(s):\n\n`)
    for (const v of violations) {
        process.stderr.write(`  ${v.tool}: ${v.reason} (${v.source})\n`)
    }
    process.stderr.write(`\nTo fix: shorten or rename the tool name in the config.\n`)
    process.exitCode = 1
}

main()
