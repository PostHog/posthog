#!/usr/bin/env tsx
/**
 * Generates MCP tool handlers from YAML definitions + OpenAPI schema.
 *
 * YAML defines which operations to expose (operationId + MCP config).
 * OpenAPI provides paths, methods, param sources.
 * Orval-generated Zod schemas (in src/generated/api.ts) provide input validation.
 *
 * Reads:
 * - services/mcp/definitions/*.yaml — tool config (operationId, scopes, annotations, etc.)
 * - frontend/tmp/openapi.json — API structure (paths, params, types)
 *
 * Produces:
 * - src/tools/generated/<category>.ts — handlers composing Orval Zod schemas
 * - src/tools/generated/index.ts — barrel merging all categories
 * - schema/generated-tool-definitions.json — tool metadata
 */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { parse as parseYaml } from 'yaml'

const DEFINITIONS_DIR = path.resolve(__dirname, '../definitions')
const GENERATED_DIR = path.resolve(__dirname, '../src/tools/generated')
const DEFINITIONS_JSON_PATH = path.resolve(__dirname, '../schema/generated-tool-definitions.json')
const OPENAPI_PATH = path.resolve(__dirname, '../../../frontend/tmp/openapi.json')

// ------------------------------------------------------------------
// Types
// ------------------------------------------------------------------

interface ToolConfig {
    operation: string
    enabled: boolean
    scopes: string[]
    annotations: {
        readOnly: boolean
        destructive: boolean
        idempotent: boolean
    }
    enrich_url?: string
    list?: boolean
    title?: string
    description?: string
    exclude_params?: string[]
    include_params?: string[]
    param_overrides?: Record<string, { description?: string }>
}

interface CategoryConfig {
    category: string
    feature: string
    url_prefix: string
    tools: Record<string, ToolConfig>
}

interface OpenApiParam {
    in: 'path' | 'query' | 'header' | 'cookie'
    name: string
    required?: boolean
    description?: string
    schema: OpenApiSchema
}

interface OpenApiSchema {
    type?: string
    format?: string
    description?: string
    nullable?: boolean
    readOnly?: boolean
    writeOnly?: boolean
    items?: OpenApiSchema | { $ref: string }
    properties?: Record<string, OpenApiSchema>
    required?: string[]
    $ref?: string
    allOf?: Array<OpenApiSchema | { $ref: string }>
    enum?: string[]
    maxLength?: number
    default?: unknown
}

interface OpenApiOperation {
    operationId: string
    parameters?: OpenApiParam[]
    requestBody?: {
        content?: {
            'application/json'?: { schema: OpenApiSchema | { $ref: string } }
        }
    }
    responses?: Record<string, { content?: { 'application/json'?: { schema: OpenApiSchema | { $ref: string } } } }>
    summary?: string
    description?: string
}

interface OpenApiSpec {
    paths: Record<string, Record<string, OpenApiOperation>>
    components?: { schemas?: Record<string, OpenApiSchema> }
}

interface ResolvedOperation {
    method: string
    path: string
    operation: OpenApiOperation
}

// ------------------------------------------------------------------
// OpenAPI helpers
// ------------------------------------------------------------------

function loadOpenApi(): OpenApiSpec {
    if (!fs.existsSync(OPENAPI_PATH)) {
        console.error(`OpenAPI schema not found at ${OPENAPI_PATH}. Run \`hogli build:openapi-schema\` first.`)
        process.exit(1)
    }
    return JSON.parse(fs.readFileSync(OPENAPI_PATH, 'utf-8')) as OpenApiSpec
}

function findOperation(spec: OpenApiSpec, operationId: string): ResolvedOperation | undefined {
    for (const [urlPath, methods] of Object.entries(spec.paths)) {
        for (const [method, op] of Object.entries(methods)) {
            if (op?.operationId === operationId) {
                return { method: method.toUpperCase(), path: urlPath, operation: op }
            }
        }
    }
    return undefined
}

function resolveSchema(spec: OpenApiSpec, schemaOrRef: OpenApiSchema | { $ref: string }): OpenApiSchema | undefined {
    if ('$ref' in schemaOrRef && schemaOrRef.$ref) {
        const schemaName = schemaOrRef.$ref.replace('#/components/schemas/', '')
        return spec.components?.schemas?.[schemaName]
    }
    return schemaOrRef as OpenApiSchema
}

// ------------------------------------------------------------------
// String helpers
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

/** Convert operationId (snake_case) to PascalCase for Orval schema names */
function operationIdToPascal(operationId: string): string {
    return operationId
        .split('_')
        .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
        .join('')
}

// ------------------------------------------------------------------
// Schema composition — determine Orval imports and build expressions
// ------------------------------------------------------------------

interface SchemaComposition {
    orvalImports: string[]
    schemaExpr: string
    pathParamNames: string[]
    queryParamNames: string[]
    bodyFieldNames: string[]
}

function composeToolSchema(config: ToolConfig, resolved: ResolvedOperation, spec: OpenApiSpec): SchemaComposition {
    const pascal = operationIdToPascal(config.operation)
    const orvalImports: string[] = []
    const schemaParts: string[] = []
    const pathParamNames: string[] = []
    const queryParamNames: string[] = []
    const bodyFieldNames: string[] = []

    const excludeSet = new Set(config.exclude_params ?? [])
    const includeSet = config.include_params ? new Set(config.include_params) : undefined

    // Path params (always omit project_id)
    const pathParams = (resolved.operation.parameters ?? []).filter((p) => p.in === 'path' && p.name !== 'project_id')
    if (pathParams.length > 0) {
        const importName = `${pascal}Params`
        orvalImports.push(importName)
        schemaParts.push(`${importName}.omit({ project_id: true })`)
        for (const p of pathParams) {
            pathParamNames.push(p.name)
        }
    }

    // Query params (always omit format)
    const queryParams = (resolved.operation.parameters ?? []).filter((p) => p.in === 'query' && p.name !== 'format')
    if (queryParams.length > 0) {
        // Filter by include/exclude
        const usefulQueryParams = queryParams.filter((p) => {
            if (excludeSet.has(p.name)) {
                return false
            }
            if (includeSet) {
                return includeSet.has(p.name)
            }
            return true
        })
        if (usefulQueryParams.length > 0) {
            const importName = `${pascal}QueryParams`
            orvalImports.push(importName)

            // Omit format + any excluded query params
            const omitKeys = ['format']
            for (const p of queryParams) {
                if (!usefulQueryParams.some((u) => u.name === p.name)) {
                    omitKeys.push(p.name)
                }
            }
            const omitObj = omitKeys.map((k) => `'${k}': true`).join(', ')
            schemaParts.push(`${importName}.omit({ ${omitObj} })`)
            for (const p of usefulQueryParams) {
                queryParamNames.push(p.name)
            }
        }
    }

    // Body (POST/PATCH/PUT)
    if (['POST', 'PATCH', 'PUT'].includes(resolved.method)) {
        const bodySchemaRef = resolved.operation.requestBody?.content?.['application/json']?.schema
        if (bodySchemaRef) {
            const importName = `${pascal}Body`
            orvalImports.push(importName)

            const bodyOmitFields = new Set<string>()
            const bodySchema = resolveSchema(spec, bodySchemaRef)

            if (bodySchema?.properties) {
                for (const [name, prop] of Object.entries(bodySchema.properties)) {
                    // Orval excludes readOnly fields from Body schemas — skip them
                    // so we don't try to .omit() keys that don't exist
                    if (prop.readOnly) {
                        continue
                    }

                    // Auto-exclude underscore-prefixed fields
                    if (name.startsWith('_')) {
                        bodyOmitFields.add(name)
                        continue
                    }
                    // Apply exclude_params / include_params
                    if (excludeSet.has(name)) {
                        bodyOmitFields.add(name)
                        continue
                    }
                    if (includeSet && !includeSet.has(name)) {
                        bodyOmitFields.add(name)
                        continue
                    }

                    bodyFieldNames.push(name)
                }
            }

            if (bodyOmitFields.size > 0) {
                const omitObj = [...bodyOmitFields].map((f) => `'${f}': true`).join(', ')
                schemaParts.push(`${importName}.omit({ ${omitObj} })`)
            } else {
                schemaParts.push(importName)
            }
        }
    }

    // Compose schema expression
    let schemaExpr: string
    if (schemaParts.length === 0) {
        schemaExpr = 'z.object({})'
    } else if (schemaParts.length === 1) {
        schemaExpr = schemaParts[0]!
    } else {
        schemaExpr = schemaParts[0]!
        for (let i = 1; i < schemaParts.length; i++) {
            schemaExpr += `.merge(${schemaParts[i]})`
        }
    }

    // param_overrides (description tweaks) are applied in the tool definitions JSON,
    // not in the Zod schema — Orval's OpenAPI-derived descriptions are used at runtime.

    return { orvalImports, schemaExpr, pathParamNames, queryParamNames, bodyFieldNames }
}

// ------------------------------------------------------------------
// Code generation for a single tool
// ------------------------------------------------------------------

function generateToolCode(
    toolName: string,
    config: ToolConfig,
    resolved: ResolvedOperation,
    category: CategoryConfig,
    spec: OpenApiSpec
): { code: string; orvalImports: string[] } {
    const schemaName = `${toPascalCase(toolName)}Schema`
    const factoryName = toCamelCase(toolName)
    const composition = composeToolSchema(config, resolved, spec)

    const schemaDecl = `const ${schemaName} = ${composition.schemaExpr}`

    // Build path interpolation
    let pathExpr = `\`${resolved.path.replace('{project_id}', '${projectId}')}\``
    for (const pn of composition.pathParamNames) {
        pathExpr = pathExpr.replace(`{${pn}}`, `\${params.${pn}}`)
    }

    // Build handler body
    let handlerBody = ''
    handlerBody += `        const projectId = await context.stateManager.getProjectId()\n`

    const hasBody = composition.bodyFieldNames.length > 0
    const hasQuery = composition.queryParamNames.length > 0

    if (hasBody) {
        handlerBody += `        const body: Record<string, unknown> = {}\n`
        for (const bf of composition.bodyFieldNames) {
            handlerBody += `        if (params.${bf} !== undefined) body['${bf}'] = params.${bf}\n`
        }
    }

    handlerBody += `        const result = await context.api.request({\n`
    handlerBody += `            method: '${resolved.method}',\n`
    handlerBody += `            path: ${pathExpr},\n`
    if (hasBody) {
        handlerBody += `            body,\n`
    }
    if (hasQuery) {
        const queryAssignments = composition.queryParamNames
            .map((qn) => `                ${qn}: params.${qn},`)
            .join('\n')
        handlerBody += `            query: {\n${queryAssignments}\n            },\n`
    }
    handlerBody += `        })\n`

    // Response enrichment
    if (config.list && config.enrich_url) {
        const field = config.enrich_url.replace(/[{}]/g, '')
        handlerBody += `        const items = (result as any).results ?? result\n`
        handlerBody += `        return (items as any[]).map((item: any) => ({\n`
        handlerBody += `            ...item,\n`
        handlerBody += `            url: \`\${context.api.getProjectBaseUrl(projectId)}${category.url_prefix}/\${item.${field}}\`,\n`
        handlerBody += `        }))\n`
    } else if (config.enrich_url) {
        const field = config.enrich_url.replace(/[{}]/g, '')
        handlerBody += `        return {\n`
        handlerBody += `            ...result as any,\n`
        handlerBody += `            url: \`\${context.api.getProjectBaseUrl(projectId)}${category.url_prefix}/\${(result as any).${field}}\`,\n`
        handlerBody += `        }\n`
    } else {
        handlerBody += `        return result\n`
    }

    const code = `
${schemaDecl}

const ${factoryName} = (): ToolBase<typeof ${schemaName}> => ({
    name: '${toolName}',
    schema: ${schemaName},
    handler: async (context: Context, params: z.infer<typeof ${schemaName}>) => {
${handlerBody}    },
})
`

    return { code, orvalImports: composition.orvalImports }
}

// ------------------------------------------------------------------
// Generate a full category file
// ------------------------------------------------------------------

function generateCategoryFile(
    category: CategoryConfig,
    fileName: string,
    spec: OpenApiSpec
): { code: string; enabledTools: [string, ToolConfig, ResolvedOperation][] } {
    const enabledTools: [string, ToolConfig, ResolvedOperation][] = []

    for (const [name, config] of Object.entries(category.tools)) {
        if (!config.enabled) {
            continue
        }
        const resolved = findOperation(spec, config.operation)
        if (!resolved) {
            console.warn(
                `Warning: operationId "${config.operation}" not found in OpenAPI for tool "${name}" — skipping`
            )
            continue
        }
        enabledTools.push([name, config, resolved])
    }

    const allOrvalImports = new Set<string>()
    const toolCodes: string[] = []

    for (const [name, config, resolved] of enabledTools) {
        const { code, orvalImports } = generateToolCode(name, config, resolved, category, spec)
        toolCodes.push(code)
        for (const imp of orvalImports) {
            allOrvalImports.add(imp)
        }
    }

    const mapEntries = enabledTools.map(([name]) => `    '${name}': ${toCamelCase(name)},`).join('\n')

    const orvalImportLine =
        allOrvalImports.size > 0
            ? `\nimport { ${[...allOrvalImports].sort().join(', ')} } from '@/generated/api'\n`
            : ''

    const code = `// AUTO-GENERATED from definitions/${fileName} + OpenAPI — do not edit
import { z } from 'zod'

import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'
${orvalImportLine}${toolCodes.join('')}
export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
${mapEntries}
}
`

    return { code, enabledTools }
}

// ------------------------------------------------------------------
// Generate tool definitions JSON
// ------------------------------------------------------------------

function generateDefinitionsJson(
    categories: { config: CategoryConfig; enabledTools: [string, ToolConfig, ResolvedOperation][] }[]
): Record<string, unknown> {
    const definitions: Record<string, unknown> = {}
    for (const { config: category, enabledTools } of categories) {
        for (const [name, toolConfig, resolved] of enabledTools) {
            const opDescription = resolved.operation.description?.trim() || resolved.operation.summary?.trim() || ''
            definitions[name] = {
                description: toolConfig.description?.trim() || opDescription,
                category: category.category,
                feature: category.feature,
                summary: toolConfig.title || opDescription.split('.')[0] || name,
                title: toolConfig.title || resolved.operation.summary || name,
                required_scopes: toolConfig.scopes,
                new_mcp: true,
                annotations: {
                    destructiveHint: toolConfig.annotations.destructive,
                    idempotentHint: toolConfig.annotations.idempotent,
                    openWorldHint: true,
                    readOnlyHint: toolConfig.annotations.readOnly,
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
    const spec = loadOpenApi()

    const yamlFiles = fs.readdirSync(DEFINITIONS_DIR).filter((f) => f.endsWith('.yaml') || f.endsWith('.yml'))

    if (yamlFiles.length === 0) {
        console.error('No YAML definitions found in', DEFINITIONS_DIR)
        process.exit(1)
    }

    fs.mkdirSync(GENERATED_DIR, { recursive: true })

    const allCategories: { config: CategoryConfig; enabledTools: [string, ToolConfig, ResolvedOperation][] }[] = []
    const generatedModules: string[] = []

    for (const file of yamlFiles) {
        const content = fs.readFileSync(path.join(DEFINITIONS_DIR, file), 'utf-8')
        const config = parseYaml(content) as CategoryConfig

        const moduleName = file.replace(/\.ya?ml$/, '')
        const { code, enabledTools } = generateCategoryFile(config, file, spec)

        if (enabledTools.length > 0) {
            generatedModules.push(moduleName)
            allCategories.push({ config, enabledTools })
            fs.writeFileSync(path.join(GENERATED_DIR, `${moduleName}.ts`), code)
        }
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
    const definitions = generateDefinitionsJson(allCategories)
    fs.writeFileSync(DEFINITIONS_JSON_PATH, JSON.stringify(definitions, null, 4) + '\n')

    const totalTools = allCategories.reduce((sum, c) => sum + c.enabledTools.length, 0)
    process.stdout.write(`Generated ${totalTools} tool(s) from ${allCategories.length} category file(s)\n`)
}

main()
