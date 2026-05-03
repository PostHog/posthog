/**
 * Loads `services/mcp/definitions/*.yaml` and returns:
 *   - the set of enabled OpenAPI operations (with the YAML's curated description/title/summary)
 *   - the set of enabled query wrappers (with their description_file resolved + read)
 *
 * Why we don't import `services/mcp/scripts/yaml-config-schema.ts`:
 *   - keeps `@posthog/mcp-exec` independent (it doesn't depend on `@posthog/mcp` as a workspace package).
 *   - we only consume a small slice of the schema; the v2 codegen owns the strict zod validation.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { parse as parseYaml } from 'yaml'

export interface EnabledOp {
    /** kebab-case tool name from the YAML (e.g. "actions-create"). */
    toolName: string
    /** OpenAPI operationId — links back to the spec. */
    operationId: string
    title?: string
    description?: string
    summary?: string
}

export interface EnabledWrapper {
    /** kebab-case tool name from the YAML (e.g. "query-trends"). */
    toolName: string
    /** Definition name in frontend/src/queries/schema.json (e.g. "AssistantTrendsQuery"). */
    schemaRef: string
    title?: string
    description?: string
    /** One-line "when to use this" hint from the YAML. */
    systemPromptHint?: string
}

export interface YamlIndex {
    /** Keyed by OpenAPI operationId for fast lookup during op iteration. */
    enabled: Map<string, EnabledOp>
    wrappers: EnabledWrapper[]
}

interface RawToolConfig {
    operation: string
    enabled: boolean
    title?: string
    description?: string
    description_file?: string
    summary?: string
}

interface RawWrapperConfig {
    schema_ref: string
    enabled: boolean
    title?: string
    description?: string
    description_file?: string
    system_prompt_hint?: string
}

interface RawCategoryFile {
    category?: string
    feature?: string
    tools?: Record<string, RawToolConfig>
    wrappers?: Record<string, RawWrapperConfig>
}

export function loadYamlDefinitions(definitionsDir: string): YamlIndex {
    if (!fs.existsSync(definitionsDir)) {
        throw new Error(`MCP definitions directory not found: ${definitionsDir}`)
    }
    const files = fs.readdirSync(definitionsDir).filter((f) => f.endsWith('.yaml') || f.endsWith('.yml'))
    if (files.length === 0) {
        throw new Error(`No YAML files found in ${definitionsDir}`)
    }

    const enabled = new Map<string, EnabledOp>()
    const wrappers: EnabledWrapper[] = []

    for (const file of files) {
        const filePath = path.join(definitionsDir, file)
        const raw = fs.readFileSync(filePath, 'utf-8')
        const parsed = parseYaml(raw) as RawCategoryFile | null
        if (!parsed) {
            continue
        }
        const yamlDir = path.dirname(filePath)

        for (const [toolName, cfg] of Object.entries(parsed.tools ?? {})) {
            if (!cfg?.enabled) {
                continue
            }
            enabled.set(cfg.operation, {
                toolName,
                operationId: cfg.operation,
                title: cfg.title,
                description: resolveDescription(cfg, yamlDir),
                summary: cfg.summary,
            })
        }

        for (const [toolName, cfg] of Object.entries(parsed.wrappers ?? {})) {
            if (!cfg?.enabled) {
                continue
            }
            wrappers.push({
                toolName,
                schemaRef: cfg.schema_ref,
                title: cfg.title,
                description: resolveDescription(cfg, yamlDir),
                systemPromptHint: cfg.system_prompt_hint,
            })
        }
    }

    return { enabled, wrappers }
}

function resolveDescription(
    cfg: { description?: string; description_file?: string },
    yamlDir: string
): string | undefined {
    if (cfg.description_file) {
        const resolved = path.resolve(yamlDir, cfg.description_file)
        if (!fs.existsSync(resolved)) {
            throw new Error(`description_file not found: ${resolved}`)
        }
        return fs.readFileSync(resolved, 'utf-8').trim()
    }
    return cfg.description?.trim()
}
