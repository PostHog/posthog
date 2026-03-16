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
import { spawnSync } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse as parseYaml } from 'yaml'

import { discoverDefinitions } from './lib/definitions.mjs'
import {
    type CategoryConfig,
    CategoryConfigSchema,
    type EnabledToolConfig,
    type ToolConfig,
} from './yaml-config-schema'

const MCP_ROOT = path.resolve(__dirname, '..')
const REPO_ROOT = path.resolve(MCP_ROOT, '../..')
const DEFINITIONS_DIR = path.resolve(MCP_ROOT, 'definitions')
const PRODUCTS_DIR = path.resolve(REPO_ROOT, 'products')
const GENERATED_DIR = path.resolve(MCP_ROOT, 'src/tools/generated')
const DEFINITIONS_JSON_PATH = path.resolve(MCP_ROOT, 'schema/generated-tool-definitions.json')
const ALL_DEFINITIONS_JSON_PATH = path.resolve(MCP_ROOT, 'schema/tool-definitions-all.json')
const TOOL_DEFINITIONS_V1_PATH = path.resolve(MCP_ROOT, 'schema/tool-definitions.json')
const TOOL_DEFINITIONS_V2_PATH = path.resolve(MCP_ROOT, 'schema/tool-definitions-v2.json')
const OPENAPI_PATH = path.resolve(REPO_ROOT, 'frontend/tmp/openapi.json')

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
    responses?: Record<
        string,
        {
            content?: {
                'application/json'?: { schema: OpenApiSchema | { $ref: string } }
            }
        }
    >
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

/**
 * Collect schema type names from the OpenAPI spec's components.schemas.
 * Used to validate that a resolved response type actually exists before emitting it.
 */
function loadKnownSchemaTypes(spec: OpenApiSpec): Set<string> {
    return new Set(Object.keys(spec.components?.schemas ?? {}))
}

/**
 * Find an operation by operationId. When the same endpoint exists at both
 * /api/environments/ and /api/projects/, prefers /api/projects/.
 * Also matches _N deduplicated variants (e.g. issues_list matches issues_list_2).
 */
function findOperation(spec: OpenApiSpec, operationId: string): ResolvedOperation | undefined {
    const base = operationId.replace(/_\d+$/, '')
    let fallback: ResolvedOperation | undefined

    for (const [urlPath, methods] of Object.entries(spec.paths)) {
        for (const [method, op] of Object.entries(methods)) {
            if (!op?.operationId) {
                continue
            }
            const opBase = op.operationId.replace(/_\d+$/, '')
            if (opBase !== base) {
                continue
            }
            const resolved = {
                method: method.toUpperCase(),
                path: urlPath,
                operation: op,
            }
            if (urlPath.startsWith('/api/projects/')) {
                return resolved
            }
            if (!fallback) {
                fallback = resolved
            }
        }
    }
    return fallback
}

function resolveSchema(spec: OpenApiSpec, schemaOrRef: OpenApiSchema | { $ref: string }): OpenApiSchema | undefined {
    if ('$ref' in schemaOrRef && schemaOrRef.$ref) {
        const schemaName = schemaOrRef.$ref.replace('#/components/schemas/', '')
        return spec.components?.schemas?.[schemaName]
    }
    return schemaOrRef as OpenApiSchema
}

/**
 * Resolve the response type name from an operation's success response.
 * Returns the Schemas.* type name if the $ref maps to a type that exists
 * in generated.ts, undefined otherwise.
 */
function resolveResponseType(operation: OpenApiOperation, knownTypes: Set<string>): string | undefined {
    for (const status of ['200', '201']) {
        const responseContent = operation.responses?.[status]?.content?.['application/json']
        if (!responseContent?.schema) {
            continue
        }
        const schema = responseContent.schema as Record<string, unknown>
        if ('$ref' in schema && schema.$ref) {
            const schemaName = (schema.$ref as string).replace('#/components/schemas/', '')
            if (knownTypes.has(schemaName)) {
                return `Schemas.${schemaName}`
            }
        }
        // Handle array responses (e.g. list endpoints with pagination_class = None)
        const items = schema.items as Record<string, unknown> | undefined
        if (schema.type === 'array' && items && '$ref' in items && items.$ref) {
            const schemaName = (items.$ref as string).replace('#/components/schemas/', '')
            if (knownTypes.has(schemaName)) {
                return `Schemas.${schemaName}`
            }
        }
    }
    return undefined
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

/**
 * Parse enrich_url template into prefix and field.
 * '{id}' → { prefix: '', field: 'id' }
 * 'hog-{id}' → { prefix: 'hog-', field: 'id' }
 */
function parseEnrichUrl(enrichUrl: string): { prefix: string; field: string } {
    const match = enrichUrl.match(/^(.*?)\{(\w+)\}$/)
    if (!match) {
        throw new Error(`Invalid enrich_url format: ${enrichUrl}`)
    }
    return { prefix: match[1]!, field: match[2]! }
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
    toolInputsImports: string[]
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

    // Path params (omit project_id and organization_id — these are auto-resolved)
    const allPathParams = (resolved.operation.parameters ?? []).filter((p) => p.in === 'path')
    const autoResolvedParams = ['project_id', 'organization_id']
    const pathParams = allPathParams.filter((p) => !autoResolvedParams.includes(p.name))
    if (pathParams.length > 0) {
        const importName = `${pascal}Params`
        orvalImports.push(importName)
        const omitKeys = autoResolvedParams.filter((k) => allPathParams.some((p) => p.name === k))
        if (omitKeys.length > 0) {
            const omitObj = omitKeys.map((k) => `${k}: true`).join(', ')
            schemaParts.push(`${importName}.omit({ ${omitObj} })`)
        } else {
            schemaParts.push(importName)
        }
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

            // Build omit set: format (if present) + any excluded query params
            const omitKeys: string[] = []
            const allQueryParamNames = new Set(
                (resolved.operation.parameters ?? []).filter((p) => p.in === 'query').map((p) => p.name)
            )
            if (allQueryParamNames.has('format')) {
                omitKeys.push('format')
            }
            for (const p of queryParams) {
                if (!usefulQueryParams.some((u) => u.name === p.name)) {
                    omitKeys.push(p.name)
                }
            }
            if (omitKeys.length > 0) {
                const omitObj = omitKeys.map((k) => `'${k}': true`).join(', ')
                schemaParts.push(`${importName}.omit({ ${omitObj} })`)
            } else {
                schemaParts.push(importName)
            }
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

                    // exclude_params are removed at the Orval schema level by
                    // applyNestedExclusions in generate-orval-schemas.mjs, so
                    // they won't exist in the Zod schema. Skip them here to
                    // avoid generating .omit() calls for nonexistent fields.
                    if (excludeSet.has(name)) {
                        continue
                    }

                    // Auto-exclude underscore-prefixed fields
                    if (name.startsWith('_')) {
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
            schemaExpr += `.extend(${schemaParts[i]}.shape)`
        }
    }

    // param_overrides with description tweaks are applied in the tool definitions JSON.
    // param_overrides with input_schema replace individual fields in the Zod schema.
    const toolInputsImports: string[] = []
    if (config.param_overrides) {
        const schemaOverrides: string[] = []
        for (const [paramName, override] of Object.entries(config.param_overrides)) {
            if (override.input_schema) {
                toolInputsImports.push(override.input_schema)
                schemaOverrides.push(`${paramName}: ${override.input_schema}`)
            }
        }
        if (schemaOverrides.length > 0) {
            schemaExpr = `(${schemaExpr}).extend({ ${schemaOverrides.join(', ')} })`
        }
    }

    return {
        orvalImports,
        toolInputsImports,
        schemaExpr,
        pathParamNames,
        queryParamNames,
        bodyFieldNames,
    }
}

// ------------------------------------------------------------------
// Code generation helpers
// ------------------------------------------------------------------

/** Extract path parameter names from a URL pattern (e.g., {id} from /api/projects/{project_id}/actions/{id}/) */
function extractPathParams(urlPattern: string): string[] {
    const autoResolved = new Set(['project_id', 'organization_id'])
    const matches = urlPattern.match(/\{(\w+)\}/g) ?? []
    return matches.map((m) => m.slice(1, -1)).filter((name) => !autoResolved.has(name))
}

/** Build a template literal expression for the API path, interpolating auto-resolved IDs and path params */
function buildPathExpr(urlPath: string, pathParamNames: string[], paramAccessPrefix = ''): string {
    let pathExpr = `\`${urlPath.replace('{project_id}', '${projectId}').replace('{organization_id}', '${orgId}')}\``
    for (const pn of pathParamNames) {
        pathExpr = pathExpr.replace(`{${pn}}`, `\${${paramAccessPrefix}${pn}}`)
    }
    return pathExpr
}

// ------------------------------------------------------------------
// Response enrichment templates
// ------------------------------------------------------------------

function buildEnrichment(config: ToolConfig, category: CategoryConfig, needsProjectId: boolean): string {
    const projectIdExpr = needsProjectId ? 'projectId' : `'@current'`
    const baseUrl = `\${context.api.getProjectBaseUrl(${projectIdExpr})}${category.url_prefix}`

    if (config.list && config.enrich_url) {
        const { prefix, field } = parseEnrichUrl(config.enrich_url)
        return [
            `        const items = (result as any).results ?? result`,
            `        return {`,
            `            ...(result as any),`,
            `            results: (items as any[]).map((item: any) => ({`,
            `                ...item,`,
            `                _posthogUrl: \`${baseUrl}/${prefix}\${item.${field}}\`,`,
            `            })),`,
            `            _posthogUrl: \`${baseUrl}\`,`,
            `        }`,
            ``,
        ].join('\n')
    }

    if (config.list) {
        return [
            `        return {`,
            `            ...(result as any),`,
            `            _posthogUrl: \`${baseUrl}\`,`,
            `        }`,
            ``,
        ].join('\n')
    }

    if (config.enrich_url) {
        const { prefix, field } = parseEnrichUrl(config.enrich_url)
        return [
            `        return {`,
            `            ...result as any,`,
            `            _posthogUrl: \`${baseUrl}/${prefix}\${(result as any).${field}}\`,`,
            `        }`,
            ``,
        ].join('\n')
    }

    return `        return result\n`
}

// ------------------------------------------------------------------
// Code generation for a single tool
// ------------------------------------------------------------------

function generateToolCode(
    toolName: string,
    config: ToolConfig,
    resolved: ResolvedOperation,
    category: CategoryConfig,
    spec: OpenApiSpec,
    knownTypes: Set<string>
): { code: string; orvalImports: string[]; toolInputsImports: string[]; responseType: string | undefined } {
    const schemaName = `${toPascalCase(toolName)}Schema`
    const factoryName = toCamelCase(toolName)

    // When input_schema is set, use the named export from tool-inputs instead of Orval
    if (config.input_schema) {
        return generateCustomSchemaToolCode(toolName, config, resolved, category, schemaName, factoryName, knownTypes)
    }

    const composition = composeToolSchema(config, resolved, spec)
    const responseType = resolveResponseType(resolved.operation, knownTypes)

    const schemaDecl = `const ${schemaName} = ${composition.schemaExpr}`

    const pathExpr = buildPathExpr(resolved.path, composition.pathParamNames, 'params.')

    // Determine which auto-resolved IDs this operation needs
    const needsProjectId = resolved.path.includes('{project_id}')
    const needsOrgId = resolved.path.includes('{organization_id}')

    // Build handler body
    let handlerBody = ''
    if (needsOrgId) {
        handlerBody += `        const orgId = await context.stateManager.getOrgID()\n`
    }
    if (needsProjectId) {
        handlerBody += `        const projectId = await context.stateManager.getProjectId()\n`
    }

    // Soft-delete overrides the HTTP method: use PATCH { deleted: true } instead of DELETE.
    // This is necessary for endpoints backed by ForbidDestroyModel (e.g. actions).
    const isSoftDelete = config.soft_delete === true

    const hasBody = !isSoftDelete && composition.bodyFieldNames.length > 0
    const hasQuery = composition.queryParamNames.length > 0

    if (hasBody) {
        handlerBody += `        const body: Record<string, unknown> = {}\n`
        for (const bf of composition.bodyFieldNames) {
            handlerBody += `        if (params.${bf} !== undefined) body['${bf}'] = params.${bf}\n`
        }
    }

    const httpMethod = isSoftDelete ? 'PATCH' : resolved.method
    handlerBody += `        const result = await context.api.request<${responseType ?? 'unknown'}>({\n`
    handlerBody += `            method: '${httpMethod}',\n`
    handlerBody += `            path: ${pathExpr},\n`
    if (isSoftDelete) {
        handlerBody += `            body: { deleted: true },\n`
    } else if (hasBody) {
        handlerBody += `            body,\n`
    }
    if (hasQuery) {
        const queryAssignments = composition.queryParamNames
            .map((qn) => `                ${qn}: params.${qn},`)
            .join('\n')
        handlerBody += `            query: {\n${queryAssignments}\n            },\n`
    }
    handlerBody += `        })\n`

    // Response enrichment — adds _posthogUrl for "View in PostHog" links
    handlerBody += buildEnrichment(config, category, needsProjectId)

    // Compute the result type for the ToolBase generic parameter
    let resultType: string
    if (config.list && config.enrich_url) {
        // List items are mapped/transformed, so the shape is no longer the raw response type
        resultType = 'unknown'
    } else if (config.enrich_url) {
        resultType = responseType ? `${responseType} & { _posthogUrl: string }` : 'unknown'
    } else if (config.list) {
        resultType = responseType ? `${responseType} & { _posthogUrl: string }` : 'unknown'
    } else {
        resultType = responseType ?? 'unknown'
    }

    // Build optional _meta block for UI app visualization
    let metaBlock = ''
    if (config.ui_resource_uri) {
        metaBlock = `    _meta: {\n        ui: {\n            resourceUri: '${config.ui_resource_uri}',\n        },\n    },\n`
    }

    const paramsUsed = hasBody || hasQuery || composition.pathParamNames.length > 0
    const unusedParamsComment = paramsUsed ? '' : '// eslint-disable-next-line no-unused-vars\n'

    const code = `
${schemaDecl}

const ${factoryName} = (): ToolBase<typeof ${schemaName}, ${resultType}> => ({
    name: '${toolName}',
    schema: ${schemaName},
    ${unusedParamsComment}handler: async (context: Context, params: z.infer<typeof ${schemaName}>) => {
${handlerBody}    },
${metaBlock}})
`

    return {
        code,
        orvalImports: composition.orvalImports,
        toolInputsImports: composition.toolInputsImports,
        responseType,
    }
}

function generateCustomSchemaToolCode(
    toolName: string,
    config: ToolConfig,
    resolved: ResolvedOperation,
    category: CategoryConfig,
    schemaName: string,
    factoryName: string,
    knownTypes: Set<string>
): { code: string; orvalImports: string[]; toolInputsImports: string[]; responseType: string | undefined } {
    const pathParamNames = extractPathParams(resolved.path)

    const pathExpr = buildPathExpr(resolved.path, pathParamNames)

    const useBody = ['POST', 'PATCH', 'PUT'].includes(resolved.method)
    const responseType = resolveResponseType(resolved.operation, knownTypes)

    const needsProjectId = resolved.path.includes('{project_id}')
    const needsOrgId = resolved.path.includes('{organization_id}')

    let handlerBody = ''
    if (needsOrgId) {
        handlerBody += `        const orgId = await context.stateManager.getOrgID()\n`
    }
    if (needsProjectId) {
        handlerBody += `        const projectId = await context.stateManager.getProjectId()\n`
    }

    if (pathParamNames.length > 0) {
        const destructured = pathParamNames.map((p) => `${p}, `).join('')
        if (useBody) {
            handlerBody += `        const { ${destructured}...body } = params\n`
        } else {
            handlerBody += `        const { ${destructured}...query } = params\n`
        }
    }

    handlerBody += `        const result = await context.api.request({\n`
    handlerBody += `            method: '${resolved.method}',\n`
    handlerBody += `            path: ${pathExpr},\n`
    if (pathParamNames.length > 0) {
        if (useBody) {
            handlerBody += `            body,\n`
        } else {
            handlerBody += `            query,\n`
        }
    } else if (useBody) {
        handlerBody += `            body: params,\n`
    } else {
        handlerBody += `            query: params,\n`
    }
    handlerBody += `        })\n`

    handlerBody += buildEnrichment(config, category, needsProjectId)

    const code = `
const ${schemaName} = ${config.input_schema}

const ${factoryName} = (): ToolBase<typeof ${schemaName}> => ({
    name: '${toolName}',
    schema: ${schemaName},
    handler: async (context: Context, params: z.infer<typeof ${schemaName}>) => {
${handlerBody}    },
})
`

    return {
        code,
        orvalImports: [],
        toolInputsImports: config.input_schema ? [config.input_schema] : [],
        responseType,
    }
}

// ------------------------------------------------------------------
// Generate a full category file
// ------------------------------------------------------------------

function generateCategoryFile(
    category: CategoryConfig,
    fileName: string,
    moduleName: string,
    spec: OpenApiSpec,
    knownTypes: Set<string>
): { code: string; enabledTools: [string, EnabledToolConfig, ResolvedOperation][] } {
    const enabledTools: [string, EnabledToolConfig, ResolvedOperation][] = []

    for (const [name, config] of Object.entries(category.tools)) {
        if (!config.enabled) {
            continue
        }
        if (!config.scopes?.length) {
            console.error(`Enabled tool "${name}" is missing required "scopes"`)
            process.exit(1)
        }
        if (!config.annotations) {
            console.error(`Enabled tool "${name}" is missing required "annotations"`)
            process.exit(1)
        }
        const resolved = findOperation(spec, config.operation)
        if (!resolved) {
            console.warn(
                `Warning: operationId "${config.operation}" not found in OpenAPI for tool "${name}" — skipping`
            )
            continue
        }
        enabledTools.push([name, config as EnabledToolConfig, resolved])
    }

    const allOrvalImports = new Set<string>()
    const allToolInputsImports = new Set<string>()
    const toolCodes: string[] = []
    let hasResponseType = false

    for (const [name, config, resolved] of enabledTools) {
        const { code, orvalImports, toolInputsImports, responseType } = generateToolCode(
            name,
            config,
            resolved,
            category,
            spec,
            knownTypes
        )
        toolCodes.push(code)
        for (const imp of orvalImports) {
            allOrvalImports.add(imp)
        }
        for (const imp of toolInputsImports) {
            allToolInputsImports.add(imp)
        }
        if (responseType) {
            hasResponseType = true
        }
    }

    const mapEntries = enabledTools.map(([name]) => `    '${name}': ${toCamelCase(name)},`).join('\n')

    const orvalImportLine =
        allOrvalImports.size > 0
            ? `\nimport { ${[...allOrvalImports].sort().join(', ')} } from '@/generated/${moduleName}/api'\n`
            : ''

    const schemasImportLine = hasResponseType ? `\nimport type { Schemas } from '@/api/generated'\n` : ''

    const toolInputsImportLine =
        allToolInputsImports.size > 0
            ? `import { ${[...allToolInputsImports].sort().join(', ')} } from '@/schema/tool-inputs'\n`
            : ''

    const code = `// AUTO-GENERATED from ${fileName} + OpenAPI — do not edit
import { z } from 'zod'

import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'
${schemasImportLine}${toolInputsImportLine}${orvalImportLine}${toolCodes.join('')}
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
    categories: {
        config: CategoryConfig
        enabledTools: [string, EnabledToolConfig, ResolvedOperation][]
    }[]
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
                new_mcp: toolConfig.mcp_version !== undefined ? toolConfig.mcp_version >= 2 : true,
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
    const knownTypes = loadKnownSchemaTypes(spec)

    const definitionSources = discoverDefinitions({ definitionsDir: DEFINITIONS_DIR, productsDir: PRODUCTS_DIR })

    if (definitionSources.length === 0) {
        console.error('No YAML definitions found in definitions/ or products/*/mcp/')
        process.exit(1)
    }

    fs.mkdirSync(GENERATED_DIR, { recursive: true })

    const allCategories: {
        config: CategoryConfig
        enabledTools: [string, EnabledToolConfig, ResolvedOperation][]
    }[] = []
    const generatedModules: string[] = []

    for (const def of definitionSources) {
        const content = fs.readFileSync(def.filePath, 'utf-8')
        const parsed = parseYaml(content)
        const result = CategoryConfigSchema.safeParse(parsed)
        if (!result.success) {
            console.error(`Invalid YAML config in ${def.filePath}:`)
            for (const issue of result.error.issues) {
                console.error(`  ${issue.path.join('.')}: ${issue.message}`)
            }
            process.exit(1)
        }
        const config = result.data

        const label = path.relative(REPO_ROOT, def.filePath)
        const { code, enabledTools } = generateCategoryFile(config, label, def.moduleName, spec, knownTypes)

        if (enabledTools.length > 0) {
            generatedModules.push(def.moduleName)
            allCategories.push({ config, enabledTools })
            fs.writeFileSync(path.join(GENERATED_DIR, `${def.moduleName}.ts`), code)
        }
    }

    // Barrel index
    const sortedModules = [...generatedModules].sort()
    const imports = sortedModules.map((m) => `import { GENERATED_TOOLS as ${toCamelCase(m)} } from './${m}'`).join('\n')
    const spreads = sortedModules.map((m) => `    ...${toCamelCase(m)},`).join('\n')
    const barrelCode = `// AUTO-GENERATED — do not edit
import type { ToolBase, ZodObjectAny } from '@/tools/types'

${imports}

export const GENERATED_TOOL_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
${spreads}
}
`
    fs.writeFileSync(path.join(GENERATED_DIR, 'index.ts'), barrelCode)

    // Tool definitions JSON
    const definitions = generateDefinitionsJson(allCategories)
    fs.writeFileSync(DEFINITIONS_JSON_PATH, JSON.stringify(definitions, null, 4) + '\n')

    // Combined tool definitions for external consumers (docs site)
    const v1Definitions = JSON.parse(fs.readFileSync(TOOL_DEFINITIONS_V1_PATH, 'utf-8'))
    const v2Definitions = JSON.parse(fs.readFileSync(TOOL_DEFINITIONS_V2_PATH, 'utf-8'))
    const allDefinitions = { ...v1Definitions, ...v2Definitions, ...definitions }
    fs.writeFileSync(ALL_DEFINITIONS_JSON_PATH, JSON.stringify(allDefinitions, null, 4) + '\n')

    const totalTools = allCategories.reduce((sum, c) => sum + c.enabledTools.length, 0)
    const totalAllTools = Object.keys(allDefinitions).length
    process.stdout.write(`Generated ${totalTools} tool(s) from ${allCategories.length} category file(s)\n`)
    process.stdout.write(`Combined ${totalAllTools} total tool(s) into tool-definitions-all.json\n`)

    const generatedTsFiles = [
        ...generatedModules.map((m) => path.join(GENERATED_DIR, `${m}.ts`)),
        path.join(GENERATED_DIR, 'index.ts'),
    ]
    spawnSync(path.join(REPO_ROOT, 'bin/hogli'), ['format:js', ...generatedTsFiles], { stdio: 'pipe', cwd: REPO_ROOT })
    spawnSync(path.join(REPO_ROOT, 'bin/hogli'), ['format:yaml', DEFINITIONS_JSON_PATH, ALL_DEFINITIONS_JSON_PATH], {
        stdio: 'pipe',
        cwd: REPO_ROOT,
    })
}

// Export for testing
export { composeToolSchema, extractPathParams, generateCategoryFile, generateCustomSchemaToolCode, generateToolCode }
export type { OpenApiSpec, ResolvedOperation }

// Run main when executed directly
function stripExt(filePath: string): string {
    return filePath.replace(/\.[jt]s$/, '')
}

const isDirectRun =
    typeof process !== 'undefined' &&
    process.argv[1] &&
    stripExt(path.resolve(process.argv[1])) === stripExt(fileURLToPath(import.meta.url))

if (isDirectRun) {
    main()
}
