#!/usr/bin/env tsx
/**
 * Lint check: ensures all MCP tool names satisfy length and pattern constraints,
 * and that descriptions/help texts only reference tools and skills that exist.
 *
 * Validates tool names from three sources:
 *   1. YAML definitions (products and services/mcp/definitions)
 *   2. Handwritten JSON definitions (tool-definitions.json)
 *   3. Generated JSON definitions (generated-tool-definitions.json)
 *
 * Length: tool names must be <= 52 chars because some MCP clients (notably Cursor)
 * enforce a 60-char combined server_name + tool_name limit ("posthog" is 7 chars).
 *
 * Pattern: tool names must be lowercase kebab-case ([a-z0-9-], no leading/trailing
 * hyphens) for cross-client compatibility.
 *
 * Cross-references: phrases like "use the X tool" or "load the X skill" in tool
 * descriptions (YAML) and field help texts (serializer help_text, surfaced via the
 * generated schema JSONs) must point at an existing tool/skill. This only covers
 * name-level staleness — it cannot validate documented schemas or tool behavior.
 *
 * Usage:
 *   pnpm --filter=@posthog/mcp lint-tool-names
 */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { parse as parseYaml } from 'yaml'

import { discoverDefinitions } from './lib/definitions.mjs'
import { checkReferencesInText, type Violation } from './lib/tool-references'
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

function validateYamlDefinitions(violations: Violation[], knownToolNames: Set<string>): boolean {
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
            knownToolNames.add(name)
            validateToolName(name, label, violations)
        }
    }

    return hasErrors
}

function validateJsonDefinitions(fileName: string, violations: Violation[], knownToolNames: Set<string>): boolean {
    const filePath = path.resolve(SCHEMA_DIR, fileName)
    if (!fs.existsSync(filePath)) {
        return false
    }
    const label = path.relative(REPO_ROOT, filePath)
    const content = JSON.parse(fs.readFileSync(filePath, 'utf-8')) as Record<string, unknown>

    for (const name of Object.keys(content)) {
        knownToolNames.add(name)
        validateToolName(name, label, violations)
    }
    return false
}

function discoverSkillNames(): Set<string> {
    const skillNames = new Set<string>()
    const skillRoots = [
        ...fs
            .readdirSync(PRODUCTS_DIR, { withFileTypes: true })
            .filter((e) => e.isDirectory())
            .map((e) => path.join(PRODUCTS_DIR, e.name, 'skills')),
        path.join(REPO_ROOT, '.agents', 'skills'),
    ]
    for (const root of skillRoots) {
        if (!fs.existsSync(root)) {
            continue
        }
        for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
            if (entry.isDirectory()) {
                skillNames.add(entry.name)
            } else if (entry.name.endsWith('.md') || entry.name.endsWith('.md.j2')) {
                skillNames.add(entry.name.replace(/\.md(\.j2)?$/, ''))
            }
        }
    }
    return skillNames
}

function validateToolReferences(violations: Violation[], toolNames: Set<string>): void {
    const skillNames = discoverSkillNames()
    const seen = new Set<string>()

    // YAML sources first so violations point at the editable file, not the generated JSON.
    const definitions = discoverDefinitions({ definitionsDir: DEFINITIONS_DIR, productsDir: PRODUCTS_DIR })
    for (const def of definitions) {
        const label = path.relative(REPO_ROOT, def.filePath)
        checkReferencesInText(fs.readFileSync(def.filePath, 'utf-8'), label, toolNames, skillNames, seen, violations)
    }

    if (fs.existsSync(SCHEMA_DIR)) {
        for (const file of fs.readdirSync(SCHEMA_DIR)) {
            if (!file.endsWith('.json')) {
                continue
            }
            const filePath = path.join(SCHEMA_DIR, file)
            checkReferencesInText(
                fs.readFileSync(filePath, 'utf-8'),
                path.relative(REPO_ROOT, filePath),
                toolNames,
                skillNames,
                seen,
                violations
            )
        }
    }

    // The tool-schema snapshots carry serializer help_text (via the OpenAPI spec); a hit here
    // means the fix belongs in a Django serializer, followed by regeneration.
    const snapshotsDir = path.resolve(MCP_ROOT, 'tests', 'unit', '__snapshots__', 'tool-schemas')
    if (fs.existsSync(snapshotsDir)) {
        for (const file of fs.readdirSync(snapshotsDir)) {
            if (!file.endsWith('.json')) {
                continue
            }
            const filePath = path.join(snapshotsDir, file)
            const label = `${path.relative(REPO_ROOT, filePath)} (fix the serializer help_text, then regenerate)`
            checkReferencesInText(fs.readFileSync(filePath, 'utf-8'), label, toolNames, skillNames, seen, violations)
        }
    }
}

function main(): void {
    const violations: Violation[] = []
    let hasErrors = false
    const knownToolNames = new Set<string>()

    hasErrors = validateYamlDefinitions(violations, knownToolNames) || hasErrors

    for (const jsonFile of ['tool-definitions.json', 'generated-tool-definitions.json']) {
        hasErrors = validateJsonDefinitions(jsonFile, violations, knownToolNames) || hasErrors
    }

    validateToolReferences(violations, knownToolNames)

    if (violations.length === 0) {
        if (!hasErrors) {
            process.stdout.write(
                `All tool names pass validation (max ${MAX_TOOL_NAME_LENGTH} chars, pattern ${TOOL_NAME_PATTERN}) and all tool/skill references resolve.\n`
            )
        }
        return
    }

    process.stderr.write(`Found ${violations.length} tool name / reference violation(s):\n\n`)
    for (const v of violations) {
        process.stderr.write(`  ${v.tool}: ${v.reason} (${v.source})\n`)
    }
    process.stderr.write(
        `\nTo fix: shorten/rename the tool name, or correct the stale reference in the description. False positive? Add it to REFERENCE_ALLOWLIST in scripts/lib/tool-references.ts.\n`
    )
    process.exitCode = 1
}

main()
