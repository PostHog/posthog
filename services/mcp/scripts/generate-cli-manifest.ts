/**
 * Generates the CLI manifest (cli-manifest.json) — a tool registry mapping
 * tool names to HTTP method + path + param locations + metadata.
 *
 * Consumed by the `ph` agent CLI (services/agent-cli) to execute PostHog API
 * tools without needing the full MCP schema overhead.
 */

import type { JsonSchemaRoot } from './lib/json-schema-to-zod'
import type { CategoryConfig, EnabledQueryWrapperToolConfig } from './lib/tool-config'

export interface CliParamSchema {
    name: string
    type: string
    required: boolean
    description?: string
}

interface CliTypeDefinition {
    properties: CliParamSchema[]
}

export interface CliToolManifest {
    method: string
    path: string
    title: string
    description: string
    category: string
    feature: string
    scopes: string[]
    annotations: {
        readOnly: boolean
        destructive: boolean
        idempotent: boolean
    }
    params: {
        path: string[]
        query: string[]
        body: string[]
    }
    soft_delete?: string | boolean | undefined
    query_kind?: string | undefined
    query_schema?: CliParamSchema[] | undefined
    types?: Record<string, CliTypeDefinition> | undefined
}

interface ToolConfig {
    title?: string
    description?: string
    description_file?: string
    scopes: string[]
    soft_delete?: string | boolean
    annotations: { readOnly: boolean; destructive: boolean; idempotent: boolean }
}

interface ResolvedOp {
    method: string
    path: string
    operation: { description?: string; summary?: string }
}

interface Composition {
    pathParamNames: string[]
    queryParamNames: string[]
    bodyFieldNames: string[]
}

// ---- Type resolution helpers ----

function resolveJsonSchemaType(
    prop: Record<string, unknown>,
    definitions: Record<string, Record<string, unknown>>
): string {
    if (prop['$ref']) {
        return (prop['$ref'] as string).split('/').pop()!
    }
    if (prop['const']) {
        return `"${prop['const']}"`
    }
    if (prop['enum']) {
        return (prop['enum'] as string[]).join(' | ')
    }
    if (prop['type'] === 'array' && prop['items']) {
        return `${resolveJsonSchemaType(prop['items'] as Record<string, unknown>, definitions)}[]`
    }
    if (prop['anyOf']) {
        return (prop['anyOf'] as Record<string, unknown>[])
            .map((a) => resolveJsonSchemaType(a, definitions))
            .join(' | ')
    }
    if (prop['allOf']) {
        return (prop['allOf'] as Record<string, unknown>[])
            .map((a) => resolveJsonSchemaType(a, definitions))
            .join(' & ')
    }
    if (prop['type']) {
        const t = prop['type']
        return Array.isArray(t) ? t.join(' | ') : (t as string)
    }
    return 'unknown'
}

export function resolveQuerySchemaParams(
    querySchema: JsonSchemaRoot,
    schemaRef: string,
    excludeProps: string[]
): CliParamSchema[] {
    const schema = querySchema.definitions[schemaRef]
    if (!schema?.properties) {
        return []
    }
    const required = new Set((schema.required as string[] | undefined) ?? [])
    const excludeSet = new Set([...excludeProps, 'kind', 'response'])

    return Object.entries(schema.properties as Record<string, Record<string, unknown>>)
        .filter(([name]) => !excludeSet.has(name))
        .map(([name, prop]) => ({
            name,
            type: resolveJsonSchemaType(prop, querySchema.definitions as Record<string, Record<string, unknown>>),
            required: required.has(name),
            ...(prop['description'] ? { description: (prop['description'] as string).slice(0, 200) } : {}),
        }))
}

export function resolveReferencedTypes(
    querySchema: JsonSchemaRoot,
    params: CliParamSchema[]
): Record<string, CliTypeDefinition> | undefined {
    const types: Record<string, CliTypeDefinition> = {}
    const primitives = new Set(['string', 'number', 'boolean', 'integer', 'null', 'unknown', 'object'])

    const referencedNames = new Set<string>()
    for (const p of params) {
        for (const segment of p.type.split('|').map((s) => s.trim().replace('[]', ''))) {
            if (segment && !primitives.has(segment) && !segment.startsWith('"')) {
                referencedNames.add(segment)
            }
        }
    }

    for (const typeName of referencedNames) {
        const def = querySchema.definitions[typeName]
        if (!def?.properties) {
            continue
        }
        const required = new Set((def.required as string[] | undefined) ?? [])
        const props: CliParamSchema[] = Object.entries(def.properties as Record<string, Record<string, unknown>>).map(
            ([name, prop]) => ({
                name,
                type: resolveJsonSchemaType(prop, querySchema.definitions as Record<string, Record<string, unknown>>),
                required: required.has(name),
                ...(prop['description'] ? { description: (prop['description'] as string).slice(0, 200) } : {}),
            })
        )
        types[typeName] = { properties: props }
    }

    return Object.keys(types).length > 0 ? types : undefined
}

// ---- Main generator ----

export function generateCliManifest(
    categories: {
        config: CategoryConfig
        enabledTools: [string, ToolConfig, ResolvedOp][]
        enabledWrappers: [string, EnabledQueryWrapperToolConfig][]
        yamlDir: string
    }[],
    querySchema: JsonSchemaRoot,
    helpers: {
        composeToolSchema: (config: ToolConfig, resolved: ResolvedOp) => Composition
        resolveDescription: (
            config: { description?: string; description_file?: string },
            yamlDir: string,
            fallback: string
        ) => string
        extractKindFromSchemaRef: (querySchema: JsonSchemaRoot, schemaRef: string) => string
    }
): Record<string, CliToolManifest> {
    const manifest: Record<string, CliToolManifest> = {}
    const { composeToolSchema, resolveDescription, extractKindFromSchemaRef } = helpers

    for (const { config: category, enabledTools, enabledWrappers, yamlDir } of categories) {
        for (const [name, toolConfig, resolved] of enabledTools) {
            const composition = composeToolSchema(toolConfig, resolved)
            const opDescription = resolved.operation.description?.trim() || resolved.operation.summary?.trim() || ''

            const isSoftDelete = toolConfig.soft_delete !== undefined && toolConfig.soft_delete !== false
            const httpMethod = isSoftDelete ? 'PATCH' : resolved.method

            manifest[name] = {
                method: httpMethod,
                path: resolved.path,
                title: toolConfig.title || resolved.operation.summary || name,
                description: resolveDescription(toolConfig, yamlDir, opDescription),
                category: category.category,
                feature: category.feature,
                scopes: toolConfig.scopes,
                annotations: {
                    readOnly: toolConfig.annotations.readOnly,
                    destructive: toolConfig.annotations.destructive,
                    idempotent: toolConfig.annotations.idempotent,
                },
                params: {
                    path: composition.pathParamNames,
                    query: composition.queryParamNames,
                    body: composition.bodyFieldNames,
                },
                ...(isSoftDelete ? { soft_delete: toolConfig.soft_delete } : {}),
            }
        }

        for (const [name, wrapperConfig] of enabledWrappers) {
            const kind = extractKindFromSchemaRef(querySchema, wrapperConfig.schema_ref)
            const excludeProps = wrapperConfig.exclude_properties ?? []
            const querySchemaParams = resolveQuerySchemaParams(querySchema, wrapperConfig.schema_ref, excludeProps)

            manifest[name] = {
                method: 'POST',
                path: '/api/environments/{project_id}/query/',
                title: wrapperConfig.title || name,
                description: resolveDescription(wrapperConfig, yamlDir, ''),
                category: category.category,
                feature: category.feature,
                scopes: wrapperConfig.scopes,
                annotations: {
                    readOnly: wrapperConfig.annotations.readOnly,
                    destructive: wrapperConfig.annotations.destructive,
                    idempotent: wrapperConfig.annotations.idempotent,
                },
                params: { path: [], query: [], body: [] },
                query_kind: kind,
                query_schema: querySchemaParams,
                types: resolveReferencedTypes(querySchema, querySchemaParams),
            }
        }
    }
    return manifest
}
