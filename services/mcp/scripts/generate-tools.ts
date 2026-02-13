#!/usr/bin/env tsx
/**
 * Generates MCP tool handlers + definitions from YAML definitions.
 *
 * Reads services/mcp/definitions/*.yaml and produces:
 * - src/tools/generated/<category>.ts — Zod schemas + handlers + factory map
 * - src/tools/generated/index.ts — barrel merging all categories
 * - schema/generated-tool-definitions.json — tool metadata
 */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { parse as parseYaml } from 'yaml'

const DEFINITIONS_DIR = path.resolve(__dirname, '../definitions')
const GENERATED_DIR = path.resolve(__dirname, '../src/tools/generated')
const DEFINITIONS_JSON_PATH = path.resolve(__dirname, '../schema/generated-tool-definitions.json')

// ------------------------------------------------------------------
// Types for the YAML schema
// ------------------------------------------------------------------

interface FieldDef {
    type: string
    required?: boolean
    description?: string
    nullable?: boolean
    default?: unknown
    path_param?: boolean
    items?: ItemDef
    properties?: Record<string, FieldDef>
}

interface ItemDef {
    type: string
    properties?: Record<string, FieldDef>
}

interface ToolDef {
    method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
    path: string
    title: string
    description: string
    scopes: string[]
    annotations: {
        readOnly: boolean
        destructive: boolean
        idempotent: boolean
    }
    input?: Record<string, FieldDef>
    enrich_url?: string
    list?: boolean
}

interface CategoryDef {
    category: string
    feature: string
    url_prefix: string
    tools: Record<string, ToolDef>
}

// ------------------------------------------------------------------
// YAML → Zod schema string
// ------------------------------------------------------------------

function fieldToZod(_name: string, field: FieldDef): string {
    let base: string

    if (field.type === 'integer') {
        base = 'z.number().int()'
        if (field.required) {
            base += '.positive()'
        }
    } else if (field.type === 'string') {
        base = 'z.string()'
        if (field.required) {
            base += '.min(1)'
        }
    } else if (field.type === 'boolean') {
        base = 'z.boolean()'
    } else if (field.type === 'string[]') {
        base = 'z.array(z.string())'
    } else if (field.type === 'array' && field.items) {
        base = `z.array(${itemToZod(field.items)})`
        if (field.required) {
            base += '.min(1)'
        }
    } else if (field.type === 'any') {
        base = 'z.any()'
    } else {
        base = 'z.any()'
    }

    if (field.default !== undefined) {
        base += `.default(${JSON.stringify(field.default)})`
    }
    if (!field.required) {
        base += '.optional()'
    }
    if (field.nullable) {
        base += '.nullable()'
    }
    if (field.description) {
        base += `.describe(${JSON.stringify(field.description)})`
    }

    return base
}

function itemToZod(item: ItemDef): string {
    if (item.type === 'object' && item.properties) {
        const fields = Object.entries(item.properties)
            .map(([name, field]) => `        ${name}: ${fieldToZod(name, field)},`)
            .join('\n')
        return `z.object({\n${fields}\n    })`
    }
    if (item.type === 'string') {
        return 'z.string()'
    }
    return 'z.any()'
}

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function toPascalCase(str: string): string {
    return str
        .split('-')
        .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
        .join('')
}

function toCamelCase(str: string): string {
    const pascal = toPascalCase(str)
    return pascal.charAt(0).toLowerCase() + pascal.slice(1)
}

function snakeToCamel(str: string): string {
    return str.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase())
}

// Extract path params from URL template, e.g. /api/projects/{project_id}/actions/{action_id}/
function extractPathParams(urlPath: string): string[] {
    const matches = urlPath.matchAll(/\{([^}]+)\}/g)
    return Array.from(matches, (m) => m[1]!).filter((p) => p !== 'project_id')
}

// ------------------------------------------------------------------
// Code generation for a single tool
// ------------------------------------------------------------------

function generateToolCode(toolName: string, tool: ToolDef, category: CategoryDef): string {
    const schemaName = `${toPascalCase(toolName)}Schema`
    const factoryName = toCamelCase(toolName)
    const pathParams = extractPathParams(tool.path)
    const inputFields = tool.input ?? {}

    // Separate path params from body fields
    const bodyFields = Object.entries(inputFields).filter(([_, f]) => !f.path_param && !pathParams.includes(_))
    const allInputFields = Object.entries(inputFields)

    // Build Zod schema
    const schemaFields = allInputFields
        .map(([name, field]) => `    ${snakeToCamel(name)}: ${fieldToZod(name, field)},`)
        .join('\n')

    const hasBody = bodyFields.length > 0 && tool.method !== 'GET' && tool.method !== 'DELETE'
    const hasQueryParams = bodyFields.length > 0 && tool.method === 'GET'

    // Build path interpolation
    let pathExpr = `\`${tool.path.replace('{project_id}', '${projectId}')}\``
    for (const param of pathParams) {
        const camelParam = snakeToCamel(param)
        pathExpr = pathExpr.replace(`{${param}}`, `\${params.${camelParam}}`)
    }

    // Build handler body
    let handlerBody = ''
    handlerBody += `        const projectId = await context.stateManager.getProjectId()\n`

    if (hasBody) {
        handlerBody += `        const body: Record<string, unknown> = {}\n`
        for (const [name] of bodyFields) {
            const camel = snakeToCamel(name)
            handlerBody += `        if (params.${camel} !== undefined) { body['${name}'] = params.${camel} }\n`
        }
        handlerBody += `        const result = await context.api.request({\n`
        handlerBody += `            method: '${tool.method}',\n`
        handlerBody += `            path: ${pathExpr},\n`
        handlerBody += `            body,\n`
        handlerBody += `        })\n`
    } else if (hasQueryParams) {
        // GET with query params
        const queryAssignments = bodyFields
            .map(([name]) => {
                const camel = snakeToCamel(name)
                return `            ${name}: params.${camel},`
            })
            .join('\n')
        handlerBody += `        const result = await context.api.request({\n`
        handlerBody += `            method: 'GET',\n`
        handlerBody += `            path: ${pathExpr},\n`
        handlerBody += `            query: {\n${queryAssignments}\n            },\n`
        handlerBody += `        })\n`
    } else {
        handlerBody += `        const result = await context.api.request({\n`
        handlerBody += `            method: '${tool.method}',\n`
        handlerBody += `            path: ${pathExpr},\n`
        handlerBody += `        })\n`
    }

    // Handle response enrichment
    if (tool.list && tool.enrich_url) {
        handlerBody += `        const items = (result as any).results ?? result\n`
        handlerBody += `        return (items as any[]).map((item: any) => ({\n`
        handlerBody += `            ...item,\n`
        handlerBody += `            url: \`\${context.api.getProjectBaseUrl(projectId)}${category.url_prefix}/\${item.${tool.enrich_url.replace(/[{}]/g, '')}}\`,\n`
        handlerBody += `        }))\n`
    } else if (tool.enrich_url) {
        handlerBody += `        return {\n`
        handlerBody += `            ...result as any,\n`
        handlerBody += `            url: \`\${context.api.getProjectBaseUrl(projectId)}${category.url_prefix}/\${(result as any).${tool.enrich_url.replace(/[{}]/g, '')}}\`,\n`
        handlerBody += `        }\n`
    } else {
        handlerBody += `        return result\n`
    }

    return `
const ${schemaName} = z.object({
${schemaFields}
})

const ${factoryName} = (): ToolBase<typeof ${schemaName}> => ({
    name: '${toolName}',
    schema: ${schemaName},
    handler: async (context: Context, params: z.infer<typeof ${schemaName}>) => {
${handlerBody}    },
})
`
}

// ------------------------------------------------------------------
// Generate a full category file
// ------------------------------------------------------------------

function generateCategoryFile(category: CategoryDef, fileName: string): string {
    const toolEntries = Object.entries(category.tools)
    const toolCode = toolEntries.map(([name, tool]) => generateToolCode(name, tool, category)).join('')

    const mapEntries = toolEntries.map(([name]) => `    '${name}': ${toCamelCase(name)},`).join('\n')

    return `// AUTO-GENERATED from definitions/${fileName} — do not edit
import { z } from 'zod'

import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'
${toolCode}
export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
${mapEntries}
}
`
}

// ------------------------------------------------------------------
// Generate tool definitions JSON
// ------------------------------------------------------------------

function generateDefinitionsJson(categories: CategoryDef[]): Record<string, unknown> {
    const definitions: Record<string, unknown> = {}
    for (const category of categories) {
        for (const [name, tool] of Object.entries(category.tools)) {
            definitions[name] = {
                description: tool.description.trim(),
                category: category.category,
                feature: category.feature,
                summary: tool.description.trim(),
                title: tool.title,
                required_scopes: tool.scopes,
                new_mcp: true,
                annotations: {
                    destructiveHint: tool.annotations.destructive,
                    idempotentHint: tool.annotations.idempotent,
                    openWorldHint: true,
                    readOnlyHint: tool.annotations.readOnly,
                },
            }
        }
    }
    return definitions
}

// ------------------------------------------------------------------
// Main
// ------------------------------------------------------------------

function main(): void {
    const yamlFiles = fs.readdirSync(DEFINITIONS_DIR).filter((f) => f.endsWith('.yaml') || f.endsWith('.yml'))

    if (yamlFiles.length === 0) {
        console.error('No YAML definitions found in', DEFINITIONS_DIR)
        process.exit(1)
    }

    fs.mkdirSync(GENERATED_DIR, { recursive: true })

    const categories: CategoryDef[] = []
    const generatedModules: string[] = []

    for (const file of yamlFiles) {
        const content = fs.readFileSync(path.join(DEFINITIONS_DIR, file), 'utf-8')
        const category = parseYaml(content) as CategoryDef
        categories.push(category)

        const moduleName = file.replace(/\.ya?ml$/, '')
        generatedModules.push(moduleName)

        const code = generateCategoryFile(category, file)
        const outPath = path.join(GENERATED_DIR, `${moduleName}.ts`)
        fs.writeFileSync(outPath, code)
    }

    // Barrel index
    const imports = generatedModules
        .map((m) => `import { GENERATED_TOOLS as ${toCamelCase(m)} } from './${m}'`)
        .join('\n')
    const spreads = generatedModules.map((m) => `    ...${toCamelCase(m)},`).join('\n')
    const barrelCode = `// AUTO-GENERATED — do not edit
${imports}

import type { ToolBase, ZodObjectAny } from '@/tools/types'

export const GENERATED_TOOL_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
${spreads}
}
`
    fs.writeFileSync(path.join(GENERATED_DIR, 'index.ts'), barrelCode)

    // Tool definitions JSON
    const definitions = generateDefinitionsJson(categories)
    fs.writeFileSync(DEFINITIONS_JSON_PATH, JSON.stringify(definitions, null, 4) + '\n')

    const totalTools = categories.reduce((sum, c) => sum + Object.keys(c.tools).length, 0)
}

main()
