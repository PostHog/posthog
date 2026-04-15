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

import { discoverDefinitions, isQueryWrappersConfig } from './lib/definitions.mjs'
import { type JsonSchemaRoot, generateZodFromSchemaRef, getEntryVarName } from './lib/json-schema-to-zod'
import {
    type CategoryConfig,
    CategoryConfigSchema,
    type EnabledToolConfig,
    type EnabledQueryWrapperToolConfig,
    type QueryWrappersConfig,
    QueryWrappersConfigSchema,
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
const SCHEMA_JSON_PATH = path.resolve(REPO_ROOT, 'frontend/src/queries/schema.json')

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
 * Prefers an exact operationId match, then falls back to matching _N deduplicated
 * variants (e.g. issues_list matches issues_list_2) for backward compatibility.
 */
function findOperation(spec: OpenApiSpec, operationId: string): ResolvedOperation | undefined {
    const base = operationId.replace(/_\d+$/, '')
    let exactFallback: ResolvedOperation | undefined
    let baseFallback: ResolvedOperation | undefined
    let baseProject: ResolvedOperation | undefined

    for (const [urlPath, methods] of Object.entries(spec.paths)) {
        for (const [method, op] of Object.entries(methods)) {
            if (!op?.operationId) {
                continue
            }
            const resolved = {
                method: method.toUpperCase(),
                path: urlPath,
                operation: op,
            }

            if (op.operationId === operationId) {
                if (urlPath.startsWith('/api/projects/')) {
                    return resolved
                }
                if (!exactFallback) {
                    exactFallback = resolved
                }
                continue
            }

            const opBase = op.operationId.replace(/_\d+$/, '')
            if (opBase !== base) {
                continue
            }
            if (urlPath.startsWith('/api/projects/')) {
                if (!baseProject) {
                    baseProject = resolved
                }
                continue
            }
            if (!baseFallback) {
                baseFallback = resolved
            }
        }
    }
    return exactFallback ?? baseProject ?? baseFallback
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
                return `Schemas.${schemaName}[]`
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
 * Parse enrich_url template into prefix, field, and source.
 * '{id}' → { prefix: '', field: 'id', source: 'result' }
 * 'hog-{id}' → { prefix: 'hog-', field: 'id', source: 'result' }
 * '{params.id}' → { prefix: '', field: 'id', source: 'params' }
 *
 * Use '{params.x}' when the response has no usable identifier (e.g. action endpoints
 * that return {results: [...]} with no top-level id) — the URL is built from the
 * request params instead of the response body.
 */
function parseEnrichUrl(enrichUrl: string): { prefix: string; field: string; source: 'result' | 'params' } {
    const match = enrichUrl.match(/^(.*?)\{(?:(params)\.)?(\w+)\}$/)
    if (!match) {
        throw new Error(`Invalid enrich_url format: ${enrichUrl}`)
    }
    return { prefix: match[1]!, field: match[3]!, source: match[2] === 'params' ? 'params' : 'result' }
}

/** Convert operationId (snake_case) to PascalCase for Orval schema names */
function operationIdToPascal(operationId: string): string {
    return operationId
        .split(/[_.]/)
        .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
        .join('')
}

// ------------------------------------------------------------------
// Schema composition — determine Orval imports and build expressions
// ------------------------------------------------------------------

interface SchemaComposition {
    orvalImports: string[]
    toolInputsImports: string[]
    /** Inline Zod declarations generated from schema_ref (emitted before the schema declaration) */
    schemaRefBlocks: string[]
    schemaExpr: string
    pathParamNames: string[]
    queryParamNames: string[]
    bodyFieldNames: string[]
    /** Maps alias → original field name for renamed params */
    renamedFields: Record<string, string>
}

function composeToolSchema(
    config: ToolConfig,
    resolved: ResolvedOperation,
    spec: OpenApiSpec,
    getQuerySchema: () => JsonSchemaRoot
): SchemaComposition {
    const pascal = operationIdToPascal(config.operation)
    const orvalImports: string[] = []
    const schemaParts: string[] = []
    const pathParamNames: string[] = []
    const queryParamNames: string[] = []
    const bodyFieldNames: string[] = []

    const excludeSet = new Set(config.exclude_params ?? [])
    const includeSet = config.include_params ? new Set(config.include_params) : undefined
    // original → alias mapping from rename_params config
    const renameMap = new Map(Object.entries(config.rename_params ?? {}))

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

                    // If this field is renamed, store the alias instead so the
                    // handler references params.<alias>. The original→alias
                    // mapping is tracked in renamedFields for body-building.
                    const alias = renameMap.get(name)
                    bodyFieldNames.push(alias ?? name)
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

    // param_overrides:
    //   - input_schema  → replace the field with a named import from @/schema/tool-inputs
    //   - schema_ref    → generate inline Zod from schema.json and use that
    //   - description   → wrap the existing Orval-derived field with .describe(...)
    const toolInputsImports: string[] = []
    const schemaRefBlocks: string[] = []
    // Fields added via param_overrides (input_schema/schema_ref) need to participate in
    // the body builder for write ops — otherwise the override is in the schema but
    // the handler never forwards the value to the API. On PATCH (partial update) the
    // field defaults to optional, mirroring the original Orval body schema.
    const isWriteOp = ['POST', 'PATCH', 'PUT'].includes(resolved.method)
    const isPartialUpdate = resolved.method === 'PATCH'
    const optionalSuffix = isPartialUpdate ? '.optional()' : ''
    if (config.param_overrides) {
        const schemaOverrides: string[] = []
        for (const [paramName, override] of Object.entries(config.param_overrides)) {
            if (override.input_schema) {
                toolInputsImports.push(override.input_schema)
                schemaOverrides.push(`${paramName}: ${override.input_schema}${optionalSuffix}`)
                if (isWriteOp && !bodyFieldNames.includes(paramName)) {
                    bodyFieldNames.push(paramName)
                }
            } else if (override.schema_ref) {
                const excludeProps = override.exclude_properties ?? []
                const zodCode = generateZodFromSchemaRef(getQuerySchema(), override.schema_ref, excludeProps)
                schemaRefBlocks.push(zodCode)
                const varName = getEntryVarName(override.schema_ref)
                schemaOverrides.push(`${paramName}: ${varName}${optionalSuffix}`)
                if (isWriteOp && !bodyFieldNames.includes(paramName)) {
                    bodyFieldNames.push(paramName)
                }
            } else if (override.description) {
                // Locate the Orval source schema this param came from, so we can reference
                // its original field type via .shape and wrap it with .describe(...).
                let sourceImport: string | null = null
                if (bodyFieldNames.includes(paramName)) {
                    sourceImport = `${pascal}Body`
                } else if (queryParamNames.includes(paramName)) {
                    sourceImport = `${pascal}QueryParams`
                } else if (pathParamNames.includes(paramName)) {
                    sourceImport = `${pascal}Params`
                }
                if (sourceImport) {
                    const escaped = override.description
                        .trim()
                        .replace(/\\/g, '\\\\')
                        .replace(/'/g, "\\'")
                        .replace(/\n\s*/g, ' ')
                    schemaOverrides.push(`${paramName}: ${sourceImport}.shape['${paramName}'].describe('${escaped}')`)
                }
            }
        }
        if (schemaOverrides.length > 0) {
            schemaExpr = `(${schemaExpr}).extend({ ${schemaOverrides.join(', ')} })`
        }
    }

    // rename_params: swap original field names for MCP-safe aliases in the schema.
    // The handler maps back to the original name when building the request body.
    const renamedFields: Record<string, string> = {}
    if (renameMap.size > 0) {
        // We need the Body import to reference .shape['original'] for the alias type
        const bodyImport = `${pascal}Body`
        for (const [original, alias] of renameMap) {
            renamedFields[alias] = original
            schemaExpr += `\n    .omit({ '${original}': true })`
            schemaExpr += `\n    .extend({ ${alias}: ${bodyImport}.shape['${original}'] })`
        }
    }

    return {
        orvalImports,
        toolInputsImports,
        schemaRefBlocks,
        schemaExpr,
        pathParamNames,
        queryParamNames,
        bodyFieldNames,
        renamedFields,
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
// Response filtering templates
// ------------------------------------------------------------------

function buildResponseFilter(config: ToolConfig): {
    code: string
    helperImport: 'pickResponseFields' | 'omitResponseFields' | null
} {
    if (config.response?.include?.length) {
        const paths = config.response?.include.map((f) => `'${f}'`).join(', ')
        if (config.list) {
            return {
                code: `        const filtered = { ...result, results: (result.results ?? []).map((item: any) => pickResponseFields(item, [${paths}])) } as typeof result\n`,
                helperImport: 'pickResponseFields',
            }
        }
        return {
            code: `        const filtered = pickResponseFields(result, [${paths}]) as typeof result\n`,
            helperImport: 'pickResponseFields',
        }
    }
    if (config.response?.exclude?.length) {
        const paths = config.response?.exclude.map((f) => `'${f}'`).join(', ')
        if (config.list) {
            return {
                code: `        const filtered = { ...result, results: (result.results ?? []).map((item: any) => omitResponseFields(item, [${paths}])) } as typeof result\n`,
                helperImport: 'omitResponseFields',
            }
        }
        return {
            code: `        const filtered = omitResponseFields(result, [${paths}]) as typeof result\n`,
            helperImport: 'omitResponseFields',
        }
    }
    return { code: '', helperImport: null }
}

// ------------------------------------------------------------------
// Response enrichment templates
// ------------------------------------------------------------------

function buildEnrichment(config: ToolConfig, category: CategoryConfig, resultVar = 'result'): string {
    const baseUrl = category.url_prefix

    if (config.list && config.enrich_url) {
        const { prefix, field, source } = parseEnrichUrl(config.enrich_url)
        // For list endpoints, 'params.x' is not meaningful (items come from the response
        // array, not request params), so force 'result' source here.
        if (source === 'params') {
            throw new Error(
                `enrich_url '{params.${field}}' is not supported on list tools — list items are enriched from the response array`
            )
        }
        return [
            `        return await withPostHogUrl(context, {`,
            `            ...${resultVar},`,
            `            results: await Promise.all((${resultVar}.results ?? []).map((item) => withPostHogUrl(context, item, \`${baseUrl}/${prefix}\${item.${field}}\`))),`,
            `        }, '${baseUrl}')`,
            ``,
        ].join('\n')
    }

    if (config.list) {
        return `        return await withPostHogUrl(context, ${resultVar}, '${baseUrl}')\n`
    }

    if (config.enrich_url) {
        const { prefix, field, source } = parseEnrichUrl(config.enrich_url)
        const sourceExpr = source === 'params' ? `params.${field}` : `${resultVar}.${field}`

        return `        return await withPostHogUrl(context, ${resultVar}, \`${baseUrl}/${prefix}\${${sourceExpr}}\`)\n`
    }

    return `        return ${resultVar}\n`
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
    knownTypes: Set<string>,
    getQuerySchema: () => JsonSchemaRoot
): {
    code: string
    orvalImports: string[]
    toolInputsImports: string[]
    schemaRefBlocks: string[]
    responseType: string | undefined
    needsWithPostHogUrl: boolean
    hasEnrichment: boolean
    responseFilterImport: 'pickResponseFields' | 'omitResponseFields' | null
} {
    const schemaName = `${toPascalCase(toolName)}Schema`
    const factoryName = toCamelCase(toolName)

    // When input_schema is set, use the named export from tool-inputs instead of Orval
    if (config.input_schema) {
        return generateCustomSchemaToolCode(toolName, config, resolved, category, schemaName, factoryName, knownTypes)
    }

    const composition = composeToolSchema(config, resolved, spec, getQuerySchema)
    let responseType = config.response_type ?? resolveResponseType(resolved.operation, knownTypes)

    // Soft-delete overrides the HTTP method: use PATCH instead of DELETE.
    // `true` sends { deleted: true }, a string value specifies the field name (e.g. "archived").
    const isSoftDelete = config.soft_delete !== undefined && config.soft_delete !== false

    // For soft-delete tools the original operation is DELETE (typically 204 no-content),
    // but the actual request is a PATCH to the same URL. Resolve the response type from
    // the PATCH operation so the generated code gets a real type instead of `unknown`.
    if (!responseType && isSoftDelete) {
        const patchOp = (spec.paths[resolved.path] as Record<string, OpenApiOperation> | undefined)?.['patch']
        if (patchOp) {
            responseType = resolveResponseType(patchOp, knownTypes)
        }
    }

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
    const softDeleteField = typeof config.soft_delete === 'string' ? config.soft_delete : 'deleted'

    const hasBody = !isSoftDelete && composition.bodyFieldNames.length > 0
    const hasQuery = composition.queryParamNames.length > 0

    if (hasBody) {
        handlerBody += `        const body: Record<string, unknown> = {}\n`
        for (const bf of composition.bodyFieldNames) {
            // If the field was renamed, bf is the alias (used for params access)
            // and bodyKey is the original name (used as the HTTP body key).
            const bodyKey = composition.renamedFields[bf] ?? bf
            handlerBody += `        if (params.${bf} !== undefined) body['${bodyKey}'] = params.${bf}\n`
        }
    }

    const httpMethod = isSoftDelete ? 'PATCH' : resolved.method
    handlerBody += `        const result = await context.api.request<${responseType ?? 'unknown'}>({\n`
    handlerBody += `            method: '${httpMethod}',\n`
    handlerBody += `            path: ${pathExpr},\n`
    if (isSoftDelete) {
        handlerBody += `            body: { ${softDeleteField}: true },\n`
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

    // Response filtering — pick/omit fields before enrichment
    const responseFilter = buildResponseFilter(config)
    if (responseFilter.code) {
        // Warn if filtering might break enrich_url
        if (config.enrich_url) {
            const { field } = parseEnrichUrl(config.enrich_url)
            if (config.response?.exclude?.includes(field)) {
                console.warn(`Warning: tool "${toolName}" excludes response field "${field}" used by enrich_url`)
            }
            if (config.response?.include?.length && !config.response?.include.includes(field)) {
                console.warn(
                    `Warning: tool "${toolName}" uses response_include without "${field}" needed by enrich_url`
                )
            }
        }
    }
    handlerBody += responseFilter.code

    // Response enrichment — adds _posthogUrl for "View in PostHog" links
    const enrichmentVar = responseFilter.code ? 'filtered' : 'result'
    handlerBody += buildEnrichment(config, category, enrichmentVar)

    // Compute the result type for the ToolBase generic parameter
    let resultType: string
    let needsWithPostHogUrl = false
    const hasEnrichment = !!(config.list || config.enrich_url)
    if (config.list && config.enrich_url) {
        needsWithPostHogUrl = !!responseType
        resultType = responseType ? `WithPostHogUrl<${responseType}>` : 'unknown'
    } else if (config.enrich_url) {
        needsWithPostHogUrl = !!responseType
        resultType = responseType ? `WithPostHogUrl<${responseType}>` : 'unknown'
    } else if (config.list) {
        needsWithPostHogUrl = !!responseType
        resultType = responseType ? `WithPostHogUrl<${responseType}>` : 'unknown'
    } else {
        resultType = responseType ?? 'unknown'
    }

    const appKey = config.ui_app ?? null

    const enrichUsesParams = !!config.enrich_url && parseEnrichUrl(config.enrich_url).source === 'params'
    const paramsUsed = hasBody || hasQuery || composition.pathParamNames.length > 0 || enrichUsesParams
    const unusedParamsComment = paramsUsed ? '' : '// eslint-disable-next-line no-unused-vars\n'

    const mcpVersionLine = config.mcp_version !== undefined ? `\n    mcpVersion: ${config.mcp_version},` : ''

    const toolBody = `{
    name: '${toolName}',
    schema: ${schemaName},${mcpVersionLine}
    ${unusedParamsComment}handler: async (context: Context, params: z.infer<typeof ${schemaName}>) => {
${handlerBody}    },
}`

    const factoryBody = appKey ? `withUiApp('${appKey}', ${toolBody})` : `(${toolBody})`

    const code = `
${schemaDecl}

const ${factoryName} = (): ToolBase<typeof ${schemaName}, ${resultType}> => ${factoryBody}
`

    return {
        code,
        orvalImports: composition.orvalImports,
        toolInputsImports: composition.toolInputsImports,
        schemaRefBlocks: composition.schemaRefBlocks,
        responseType,
        needsWithPostHogUrl,
        hasEnrichment,
        responseFilterImport: responseFilter.helperImport,
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
): {
    code: string
    orvalImports: string[]
    toolInputsImports: string[]
    schemaRefBlocks: string[]
    responseType: string | undefined
    needsWithPostHogUrl: boolean
    hasEnrichment: boolean
    responseFilterImport: 'pickResponseFields' | 'omitResponseFields' | null
} {
    const pathParamNames = extractPathParams(resolved.path)

    const pathExpr = buildPathExpr(resolved.path, pathParamNames)

    const useBody = ['POST', 'PATCH', 'PUT'].includes(resolved.method)
    const responseType = config.response_type ?? resolveResponseType(resolved.operation, knownTypes)

    const needsProjectId = resolved.path.includes('{project_id}')
    const needsOrgId = resolved.path.includes('{organization_id}')

    let handlerBody = ''
    if (needsOrgId) {
        handlerBody += `        const orgId = await context.stateManager.getOrgID()\n`
    }
    if (needsProjectId) {
        handlerBody += `        const projectId = await context.stateManager.getProjectId()\n`
    }

    handlerBody += `        const parsedParams = ${schemaName}.parse(params)\n`

    if (pathParamNames.length > 0) {
        const destructured = pathParamNames.map((p) => `${p}, `).join('')
        if (useBody) {
            handlerBody += `        const { ${destructured}...body } = parsedParams\n`
        } else {
            handlerBody += `        const { ${destructured}...query } = parsedParams\n`
        }
    }

    handlerBody += `        const result = await context.api.request<${responseType ?? 'unknown'}>({\n`
    handlerBody += `            method: '${resolved.method}',\n`
    handlerBody += `            path: ${pathExpr},\n`
    if (pathParamNames.length > 0) {
        if (useBody) {
            handlerBody += `            body,\n`
        } else {
            handlerBody += `            query,\n`
        }
    } else if (useBody) {
        handlerBody += `            body: parsedParams,\n`
    } else {
        handlerBody += `            query: parsedParams,\n`
    }
    handlerBody += `        })\n`

    // Response filtering — pick/omit fields before enrichment
    const responseFilter = buildResponseFilter(config)
    handlerBody += responseFilter.code

    const enrichmentVar = responseFilter.code ? 'filtered' : 'result'
    handlerBody += buildEnrichment(config, category, enrichmentVar)

    const mcpVersionLine = config.mcp_version !== undefined ? `\n    mcpVersion: ${config.mcp_version},` : ''

    const code = `
const ${schemaName} = ${config.input_schema}

const ${factoryName} = (): ToolBase<typeof ${schemaName}, ${responseType ?? 'unknown'}> => ({
    name: '${toolName}',
    schema: ${schemaName},${mcpVersionLine}
    handler: async (context: Context, params: z.infer<typeof ${schemaName}>) => {
${handlerBody}    },
})
`

    return {
        code,
        orvalImports: [],
        toolInputsImports: config.input_schema ? [config.input_schema] : [],
        schemaRefBlocks: [],
        responseType,
        needsWithPostHogUrl: false,
        hasEnrichment: false,
        responseFilterImport: responseFilter.helperImport,
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
    knownTypes: Set<string>,
    getQuerySchema: () => JsonSchemaRoot
): {
    code: string
    enabledTools: [string, EnabledToolConfig, ResolvedOperation][]
    enabledWrappers: [string, EnabledQueryWrapperToolConfig][]
} {
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

    // Collect enabled query wrappers from the optional wrappers section
    const enabledWrappers: [string, EnabledQueryWrapperToolConfig][] = []
    if (category.wrappers) {
        const querySchema = getQuerySchema()
        for (const [name, wrapperConfig] of Object.entries(category.wrappers)) {
            if (!wrapperConfig.enabled) {
                continue
            }
            if (!wrapperConfig.scopes?.length) {
                console.error(`Enabled query wrapper "${name}" is missing required "scopes"`)
                process.exit(1)
            }
            if (!wrapperConfig.annotations) {
                console.error(`Enabled query wrapper "${name}" is missing required "annotations"`)
                process.exit(1)
            }
            if (!querySchema.definitions[wrapperConfig.schema_ref]) {
                console.error(
                    `Query wrapper "${name}": schema_ref "${wrapperConfig.schema_ref}" not found in schema.json`
                )
                process.exit(1)
            }
            enabledWrappers.push([name, wrapperConfig as EnabledQueryWrapperToolConfig])
        }
    }

    const allOrvalImports = new Set<string>()
    const allToolInputsImports = new Set<string>()
    const allSchemaRefBlocks: string[] = []
    const emittedSchemaRefDefs = new Set<string>()
    const toolCodes: string[] = []
    let hasResponseType = false
    let hasWithPostHogUrl = false

    let hasEnrichment = false

    const responseFilterImports = new Set<string>()

    for (const [name, config, resolved] of enabledTools) {
        const result = generateToolCode(name, config, resolved, category, spec, knownTypes, getQuerySchema)
        toolCodes.push(result.code)
        for (const imp of result.orvalImports) {
            allOrvalImports.add(imp)
        }
        for (const imp of result.toolInputsImports) {
            allToolInputsImports.add(imp)
        }
        // Collect schema_ref blocks, deduplicating by const name
        for (const block of result.schemaRefBlocks) {
            for (const decl of block.split('\n\nconst ')) {
                const line = decl.startsWith('const ') ? decl : `const ${decl}`
                const match = line.match(/^const (\w+) =/)
                if (match && !emittedSchemaRefDefs.has(match[1]!)) {
                    emittedSchemaRefDefs.add(match[1]!)
                    allSchemaRefBlocks.push(line)
                }
            }
        }
        if (result.responseType) {
            hasResponseType = true
        }
        if (result.needsWithPostHogUrl) {
            hasWithPostHogUrl = true
        }
        if (result.hasEnrichment) {
            hasEnrichment = true
        }
        if (result.responseFilterImport) {
            responseFilterImports.add(result.responseFilterImport)
        }
    }

    // Generate query wrapper Zod schemas and registrations if wrappers are present
    let wrapperSchemasCode = ''
    let wrapperMapEntries = ''
    if (enabledWrappers.length > 0) {
        const querySchema = getQuerySchema()
        const allZodBlocks: string[] = []
        const emittedDefs = new Set<string>()

        // Track which properties each base schema actually has after deduplication,
        // so per-tool .omit() calls only reference properties that exist.
        const baseSchemaProps = new Map<string, Set<string>>()

        for (const [, wrapperConfig] of enabledWrappers) {
            const excludeProps = [...(wrapperConfig.exclude_properties ?? [])]
            const zodCode = generateZodFromSchemaRef(querySchema, wrapperConfig.schema_ref, excludeProps)
            const lines = zodCode.split('\n\nconst ')
            for (let i = 0; i < lines.length; i++) {
                const block = i === 0 ? lines[i]! : `const ${lines[i]}`
                const match = block.match(/^const (\w+) =/)
                if (match && !emittedDefs.has(match[1]!)) {
                    emittedDefs.add(match[1]!)
                    allZodBlocks.push(block)
                    // Record properties of the emitted base schema
                    const entryVarName = getEntryVarName(wrapperConfig.schema_ref)
                    if (match[1] === entryVarName) {
                        const propNames = new Set<string>()
                        for (const propMatch of block.matchAll(/^\s{4}(\w+):/gm)) {
                            propNames.add(propMatch[1]!)
                        }
                        baseSchemaProps.set(entryVarName, propNames)
                    }
                }
            }
        }

        // Generate per-tool schemas when the tool needs to customize the base schema
        // via property_defaults or omitting exclude_properties that survived deduplication.
        const perToolSchemaNames = new Map<string, string>()
        for (const [name, wrapperConfig] of enabledWrappers) {
            const hasDefaults =
                wrapperConfig.property_defaults && Object.keys(wrapperConfig.property_defaults).length > 0
            const baseVarName = getEntryVarName(wrapperConfig.schema_ref)
            const baseProps = baseSchemaProps.get(baseVarName) ?? new Set()
            const keysToOmit = new Set<string>()
            for (const k of wrapperConfig.exclude_properties ?? []) {
                if (baseProps.has(k)) {
                    keysToOmit.add(k)
                }
            }
            const hasOmits = keysToOmit.size > 0
            if (!hasDefaults && !hasOmits) {
                continue
            }
            const toolSchemaName = `${toPascalCase(name)}Schema`
            const omitExpr = hasOmits ? `.omit({ ${[...keysToOmit].map((k) => `${k}: true`).join(', ')} })` : ''
            const overrides: string[] = []
            for (const [prop, defaultValue] of Object.entries(wrapperConfig.property_defaults ?? {})) {
                overrides.push(
                    `    ${prop}: ${baseVarName}.shape.${prop}.default(${JSON.stringify(defaultValue)}).optional(),`
                )
            }
            const extendExpr = overrides.length > 0 ? `.extend({\n${overrides.join('\n')}\n})` : ''
            allZodBlocks.push(`const ${toolSchemaName} = ${baseVarName}${omitExpr}${extendExpr}`)
            perToolSchemaNames.set(name, toolSchemaName)
        }

        wrapperSchemasCode =
            '\n// --- Query wrapper schemas from schema.json ---\n\n' + allZodBlocks.join('\n\n') + '\n'

        wrapperMapEntries = enabledWrappers
            .map(([name, wrapperConfig]) => {
                const schemaVarName = perToolSchemaNames.get(name) ?? getEntryVarName(wrapperConfig.schema_ref)
                const kind = extractKindFromSchemaRef(querySchema, wrapperConfig.schema_ref)
                const configParts = [`name: '${name}'`, `schema: ${schemaVarName}`, `kind: '${kind}'`]
                if (wrapperConfig.ui_resource_uri) {
                    configParts.push(`uiResourceUri: '${wrapperConfig.ui_resource_uri}'`)
                }
                if (wrapperConfig.url_prefix) {
                    configParts.push(`urlPrefix: '${wrapperConfig.url_prefix}'`)
                }
                if (wrapperConfig.mcp_version !== undefined) {
                    configParts.push(`mcpVersion: ${wrapperConfig.mcp_version}`)
                }
                return `    '${name}': createQueryWrapper({ ${configParts.join(', ')} }),`
            })
            .join('\n')
    }

    const restMapEntries = enabledTools.map(([name]) => `    '${name}': ${toCamelCase(name)},`).join('\n')
    const mapEntries = [restMapEntries, wrapperMapEntries].filter(Boolean).join('\n')

    const orvalImportLine =
        allOrvalImports.size > 0
            ? `\nimport { ${[...allOrvalImports].sort().join(', ')} } from '@/generated/${moduleName}/api'\n`
            : ''

    const schemasImportLine = hasResponseType ? `\nimport type { Schemas } from '@/api/generated'\n` : ''

    const hasUiMeta = enabledTools.some(([, config]) => config.ui_app)
    const withUiAppImportLine = hasUiMeta ? `import { withUiApp } from '@/resources/ui-apps'\n` : ''

    const toolInputsImportLine =
        allToolInputsImports.size > 0
            ? `import { ${[...allToolInputsImports].sort().join(', ')} } from '@/schema/tool-inputs'\n`
            : ''

    // Build tool-utils import (WithPostHogUrl type + withPostHogUrl runtime helper)
    const toolUtilsTypeImports: string[] = []
    const toolUtilsValueImports: string[] = []
    if (hasWithPostHogUrl) {
        toolUtilsTypeImports.push('WithPostHogUrl')
    }
    if (hasEnrichment) {
        toolUtilsValueImports.push('withPostHogUrl')
    }
    for (const imp of responseFilterImports) {
        toolUtilsValueImports.push(imp)
    }
    let toolUtilsImportLine = ''
    if (toolUtilsValueImports.length > 0 && toolUtilsTypeImports.length > 0) {
        toolUtilsImportLine = `import { ${toolUtilsValueImports.join(', ')}, type ${toolUtilsTypeImports.join(', type ')} } from '@/tools/tool-utils'\n`
    } else if (toolUtilsValueImports.length > 0) {
        toolUtilsImportLine = `import { ${toolUtilsValueImports.join(', ')} } from '@/tools/tool-utils'\n`
    } else if (toolUtilsTypeImports.length > 0) {
        toolUtilsImportLine = `import type { ${toolUtilsTypeImports.join(', ')} } from '@/tools/tool-utils'\n`
    }

    const wrapperImportLine =
        enabledWrappers.length > 0 ? `import { createQueryWrapper } from '@/tools/query-wrapper-factory'\n` : ''

    const schemaRefCode = allSchemaRefBlocks.length > 0 ? '\n' + allSchemaRefBlocks.join('\n\n') + '\n' : ''

    const code = `// AUTO-GENERATED from ${fileName} + OpenAPI — do not edit
import { z } from 'zod'

import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'
${toolUtilsImportLine ? `${toolUtilsImportLine}` : ''}${schemasImportLine}${withUiAppImportLine}${toolInputsImportLine}${wrapperImportLine}${orvalImportLine}${schemaRefCode}${toolCodes.join('')}${wrapperSchemasCode}
export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
${mapEntries}
}
`

    return { code, enabledTools, enabledWrappers }
}

// ------------------------------------------------------------------
// Generate tool definitions JSON
// ------------------------------------------------------------------

/**
 * Resolve a tool description from either an inline `description` string or a
 * `description_file` path (resolved relative to `yamlDir`). Returns the
 * fallback when neither is set.
 */
function resolveDescription(
    config: { description?: string | undefined; description_file?: string | undefined },
    yamlDir: string,
    fallback: string
): string {
    if (config.description_file) {
        const filePath = path.resolve(yamlDir, config.description_file)
        if (!fs.existsSync(filePath)) {
            console.error(`description_file not found: ${filePath}`)
            process.exit(1)
        }
        return fs.readFileSync(filePath, 'utf-8').trim()
    }
    return config.description?.trim() || fallback
}

function generateDefinitionsJson(
    categories: {
        config: CategoryConfig
        enabledTools: [string, EnabledToolConfig, ResolvedOperation][]
        enabledWrappers: [string, EnabledQueryWrapperToolConfig][]
        yamlDir: string
    }[]
): Record<string, unknown> {
    const definitions: Record<string, unknown> = {}
    for (const { config: category, enabledTools, enabledWrappers, yamlDir } of categories) {
        for (const [name, toolConfig, resolved] of enabledTools) {
            const opDescription = resolved.operation.description?.trim() || resolved.operation.summary?.trim() || ''
            definitions[name] = {
                description: resolveDescription(toolConfig, yamlDir, opDescription),
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
                ...(toolConfig.requires_ai_consent ? { requires_ai_consent: true } : {}),
            }
        }
        // Include query wrappers defined in the same category file
        for (const [name, wrapperConfig] of enabledWrappers) {
            definitions[name] = {
                description: resolveDescription(wrapperConfig, yamlDir, ''),
                category: category.category,
                feature: category.feature,
                summary: wrapperConfig.title || name,
                title: wrapperConfig.title || name,
                required_scopes: wrapperConfig.scopes,
                new_mcp: wrapperConfig.mcp_version !== undefined ? wrapperConfig.mcp_version >= 2 : true,
                annotations: {
                    destructiveHint: wrapperConfig.annotations.destructive,
                    idempotentHint: wrapperConfig.annotations.idempotent,
                    openWorldHint: true,
                    readOnlyHint: wrapperConfig.annotations.readOnly,
                },
            }
        }
    }
    return definitions
}

// ------------------------------------------------------------------
// Query wrapper generation — tools backed by schema.json definitions
// ------------------------------------------------------------------

function loadQuerySchema(): JsonSchemaRoot {
    if (!fs.existsSync(SCHEMA_JSON_PATH)) {
        console.error(`Query schema not found at ${SCHEMA_JSON_PATH}. Run schema:build:json first.`)
        process.exit(1)
    }
    return JSON.parse(fs.readFileSync(SCHEMA_JSON_PATH, 'utf-8')) as JsonSchemaRoot
}

function generateQueryWrapperFile(
    config: QueryWrappersConfig,
    fileName: string,
    querySchema: JsonSchemaRoot
): {
    code: string
    enabledWrappers: [string, EnabledQueryWrapperToolConfig][]
} {
    const enabledWrappers: [string, EnabledQueryWrapperToolConfig][] = []

    for (const [name, toolConfig] of Object.entries(config.wrappers)) {
        if (!toolConfig.enabled) {
            continue
        }
        if (!toolConfig.scopes?.length) {
            console.error(`Enabled query wrapper "${name}" is missing required "scopes"`)
            process.exit(1)
        }
        if (!toolConfig.annotations) {
            console.error(`Enabled query wrapper "${name}" is missing required "annotations"`)
            process.exit(1)
        }
        if (!querySchema.definitions[toolConfig.schema_ref]) {
            console.error(`Query wrapper "${name}": schema_ref "${toolConfig.schema_ref}" not found in schema.json`)
            process.exit(1)
        }
        enabledWrappers.push([name, toolConfig as EnabledQueryWrapperToolConfig])
    }

    // Generate all Zod schemas first, collecting them to deduplicate shared definitions
    const allZodBlocks: string[] = []
    const emittedDefs = new Set<string>()

    for (const [, toolConfig] of enabledWrappers) {
        const excludeProps = [...(toolConfig.exclude_properties ?? [])]
        const zodCode = generateZodFromSchemaRef(querySchema, toolConfig.schema_ref, excludeProps)
        // Split into individual const declarations and only emit new ones
        const lines = zodCode.split('\n\nconst ')
        for (let i = 0; i < lines.length; i++) {
            const block = i === 0 ? lines[i]! : `const ${lines[i]}`
            const match = block.match(/^const (\w+) =/)
            if (match && !emittedDefs.has(match[1]!)) {
                emittedDefs.add(match[1]!)
                allZodBlocks.push(block)
            }
        }
    }

    // Generate per-tool schemas when the tool needs to customize the base schema.
    const perToolSchemaNames = new Map<string, string>()
    for (const [name, toolConfig] of enabledWrappers) {
        const hasDefaults = toolConfig.property_defaults && Object.keys(toolConfig.property_defaults).length > 0
        if (!hasDefaults) {
            continue
        }
        const baseVarName = getEntryVarName(toolConfig.schema_ref)
        const toolSchemaName = `${toPascalCase(name)}Schema`
        const overrides: string[] = []
        for (const [prop, defaultValue] of Object.entries(toolConfig.property_defaults ?? {})) {
            overrides.push(
                `    ${prop}: ${baseVarName}.shape.${prop}.default(${JSON.stringify(defaultValue)}).optional(),`
            )
        }
        const extendExpr = `.extend({\n${overrides.join('\n')}\n})`
        allZodBlocks.push(`const ${toolSchemaName} = ${baseVarName}${extendExpr}`)
        perToolSchemaNames.set(name, toolSchemaName)
    }

    const schemasCode = allZodBlocks.join('\n\n')

    // Generate tool registrations using the factory
    const mapEntries = enabledWrappers
        .map(([name, toolConfig]) => {
            const schemaVarName = perToolSchemaNames.get(name) ?? getEntryVarName(toolConfig.schema_ref)
            const kind = extractKindFromSchemaRef(querySchema, toolConfig.schema_ref)
            const configParts = [`name: '${name}'`, `schema: ${schemaVarName}`, `kind: '${kind}'`]
            if (toolConfig.ui_resource_uri) {
                configParts.push(`uiResourceUri: '${toolConfig.ui_resource_uri}'`)
            }
            if (toolConfig.response_format) {
                configParts.push(`responseFormat: '${toolConfig.response_format}'`)
            }

            if (toolConfig.url_prefix) {
                configParts.push(`urlPrefix: '${toolConfig.url_prefix}'`)
            }
            if (toolConfig.mcp_version !== undefined) {
                configParts.push(`mcpVersion: ${toolConfig.mcp_version}`)
            }
            return `    '${name}': createQueryWrapper({ ${configParts.join(', ')} }),`
        })
        .join('\n')

    const code = `// AUTO-GENERATED from ${fileName} + schema.json — do not edit
import { z } from 'zod'

import type { ZodObjectAny } from '@/tools/types'
import { createQueryWrapper } from '@/tools/query-wrapper-factory'

// --- Shared Zod schemas generated from schema.json ---

${schemasCode}

// --- Tool registrations ---

export const GENERATED_TOOLS: Record<string, ReturnType<typeof createQueryWrapper<ZodObjectAny>>> = {
${mapEntries}
}
`

    return { code, enabledWrappers }
}

/** Extract the `kind` const value from a schema.json definition */
function extractKindFromSchemaRef(querySchema: JsonSchemaRoot, schemaRef: string): string {
    const schema = querySchema.definitions[schemaRef]
    if (schema?.properties?.kind?.const) {
        return schema.properties.kind.const as string
    }
    // Fallback: derive from the schema ref name (e.g. AssistantTrendsQuery → TrendsQuery)
    return schemaRef.replace(/^Assistant/, '')
}

function generateQueryWrapperDefinitionsJson(
    config: QueryWrappersConfig,
    enabledWrappers: [string, EnabledQueryWrapperToolConfig][],
    yamlDir: string
): Record<string, unknown> {
    const definitions: Record<string, unknown> = {}
    for (const [name, toolConfig] of enabledWrappers) {
        definitions[name] = {
            description: resolveDescription(toolConfig, yamlDir, `Run a ${toolConfig.schema_ref} query`),
            category: config.category,
            feature: config.feature,
            summary: toolConfig.title || name,
            title: toolConfig.title || name,
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
        enabledWrappers: [string, EnabledQueryWrapperToolConfig][]
        yamlDir: string
    }[] = []
    const generatedModules: string[] = []

    // Accumulate query wrapper definitions separately
    const queryWrapperDefinitions: Record<string, unknown> = {}
    let querySchema: JsonSchemaRoot | undefined

    for (const def of definitionSources) {
        const content = fs.readFileSync(def.filePath, 'utf-8')
        const parsed = parseYaml(content)

        // Check if this is a query wrapper config
        if (isQueryWrappersConfig(parsed)) {
            const result = QueryWrappersConfigSchema.safeParse(parsed)
            if (!result.success) {
                console.error(`Invalid query wrappers YAML in ${def.filePath}:`)
                for (const issue of result.error.issues) {
                    console.error(`  ${issue.path.join('.')}: ${issue.message}`)
                }
                process.exit(1)
            }

            // Lazy-load query schema only when needed
            if (!querySchema) {
                querySchema = loadQuerySchema()
            }

            const config = result.data
            const label = path.relative(REPO_ROOT, def.filePath)
            const { code, enabledWrappers } = generateQueryWrapperFile(config, label, querySchema)

            if (enabledWrappers.length > 0) {
                generatedModules.push(def.moduleName)
                fs.writeFileSync(path.join(GENERATED_DIR, `${def.moduleName}.ts`), code)
                Object.assign(
                    queryWrapperDefinitions,
                    generateQueryWrapperDefinitionsJson(config, enabledWrappers, path.dirname(def.filePath))
                )
                process.stdout.write(`Generated ${enabledWrappers.length} query wrapper(s) from ${label}\n`)
            }
            continue
        }

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
        const getQuerySchemaLazy = (): JsonSchemaRoot => {
            if (!querySchema) {
                querySchema = loadQuerySchema()
            }
            return querySchema
        }
        const { code, enabledTools, enabledWrappers } = generateCategoryFile(
            config,
            label,
            def.moduleName,
            spec,
            knownTypes,
            getQuerySchemaLazy
        )

        if (enabledTools.length > 0 || enabledWrappers.length > 0) {
            generatedModules.push(def.moduleName)
            allCategories.push({ config, enabledTools, enabledWrappers, yamlDir: path.dirname(def.filePath) })
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

    // Tool definitions JSON (merge OpenAPI-based + query wrapper definitions)
    const definitions = { ...generateDefinitionsJson(allCategories), ...queryWrapperDefinitions }
    fs.writeFileSync(DEFINITIONS_JSON_PATH, JSON.stringify(definitions, null, 4) + '\n')

    // Combined tool definitions for external consumers (docs site)
    const v1Definitions = JSON.parse(fs.readFileSync(TOOL_DEFINITIONS_V1_PATH, 'utf-8'))
    const v2Definitions = JSON.parse(fs.readFileSync(TOOL_DEFINITIONS_V2_PATH, 'utf-8'))
    const allDefinitions = { ...v1Definitions, ...v2Definitions, ...definitions }
    fs.writeFileSync(ALL_DEFINITIONS_JSON_PATH, JSON.stringify(allDefinitions, null, 4) + '\n')

    const totalTools = allCategories.reduce((sum, c) => sum + c.enabledTools.length, 0)
    const totalQueryWrappers = Object.keys(queryWrapperDefinitions).length
    const totalAllTools = Object.keys(allDefinitions).length
    process.stdout.write(`Generated ${totalTools} tool(s) from ${allCategories.length} category file(s)\n`)
    if (totalQueryWrappers > 0) {
        process.stdout.write(`Generated ${totalQueryWrappers} query wrapper tool(s)\n`)
    }
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
export {
    buildResponseFilter,
    composeToolSchema,
    extractPathParams,
    generateCategoryFile,
    generateCustomSchemaToolCode,
    generateQueryWrapperFile,
    generateToolCode,
}
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
