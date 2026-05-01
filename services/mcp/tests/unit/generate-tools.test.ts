import { describe, expect, it } from 'vitest'

import {
    buildResponseFilter,
    composeToolSchema,
    extractPathParams,
    generateDefinitionsJson,
    generateQueryWrapperDefinitionsJson,
    generateQueryWrapperFile,
    generateToolCode,
} from '../../scripts/generate-tools'
import type { OpenApiSpec, ResolvedOperation } from '../../scripts/generate-tools'
import { QueryWrapperToolConfigSchema, ToolConfigSchema } from '../../scripts/yaml-config-schema'
import type { EnabledQueryWrapperToolConfig, EnabledToolConfig, ToolConfig } from '../../scripts/yaml-config-schema'

function makeSpec(overrides: Partial<OpenApiSpec> = {}): OpenApiSpec {
    return {
        paths: {},
        components: { schemas: {} },
        ...overrides,
    }
}

function makeResolved(overrides: Partial<ResolvedOperation> = {}): ResolvedOperation {
    return {
        method: 'GET',
        path: '/api/projects/{project_id}/things/',
        operation: {
            operationId: 'things_list',
            parameters: [],
        },
        ...overrides,
    }
}

const defaultCategory = {
    category: 'Things',
    feature: 'things',
    url_prefix: '/things',
    tools: {},
}

// Tests don't exercise schema_ref param_overrides, so return an empty JsonSchemaRoot stub.
const stubGetQuerySchema = (): { definitions: Record<string, never> } => ({ definitions: {} })

describe('extractPathParams', () => {
    const cases = [
        {
            name: 'returns empty for path without params',
            url: '/api/projects/things/',
            expected: [],
        },
        {
            name: 'excludes project_id',
            url: '/api/projects/{project_id}/things/',
            expected: [],
        },
        {
            name: 'extracts non-project_id params',
            url: '/api/projects/{project_id}/things/{id}/',
            expected: ['id'],
        },
        {
            name: 'extracts multiple params',
            url: '/api/projects/{project_id}/things/{thing_id}/sub/{sub_id}/',
            expected: ['thing_id', 'sub_id'],
        },
    ]

    it.each(cases)('$name', ({ url, expected }) => {
        expect(extractPathParams(url)).toEqual(expected)
    })
})

describe('composeToolSchema', () => {
    it('returns empty toolInputsImports when no param_overrides have input_schema', () => {
        const config: ToolConfig = {
            operation: 'things_list',
            enabled: true,
        }
        const resolved = makeResolved()
        const result = composeToolSchema(config, resolved, makeSpec(), stubGetQuerySchema)

        expect(result.toolInputsImports).toEqual([])
    })

    it('returns empty toolInputsImports when param_overrides only have descriptions', () => {
        const config: ToolConfig = {
            operation: 'things_list',
            enabled: true,
            param_overrides: {
                name: { description: 'A custom description' },
            },
        }
        const resolved = makeResolved()
        const result = composeToolSchema(config, resolved, makeSpec(), stubGetQuerySchema)

        expect(result.toolInputsImports).toEqual([])
    })

    it('collects toolInputsImports from param_overrides with input_schema', () => {
        const config: ToolConfig = {
            operation: 'things_create',
            enabled: true,
            param_overrides: {
                steps: { input_schema: 'StepsSchema' },
                filters: { input_schema: 'FiltersSchema' },
                name: { description: 'Just a description' },
            },
        }
        const resolved = makeResolved({
            method: 'POST',
            operation: {
                operationId: 'things_create',
                parameters: [],
                requestBody: {
                    content: {
                        'application/json': {
                            schema: {
                                properties: {
                                    steps: { type: 'object' },
                                    filters: { type: 'object' },
                                    name: { type: 'string' },
                                },
                            },
                        },
                    },
                },
            },
        })

        const result = composeToolSchema(config, resolved, makeSpec(), stubGetQuerySchema)

        expect(result.toolInputsImports).toContain('StepsSchema')
        expect(result.toolInputsImports).toContain('FiltersSchema')
        expect(result.toolInputsImports).toHaveLength(2)
    })

    it('applies .extend() for param_overrides with input_schema', () => {
        const config: ToolConfig = {
            operation: 'things_create',
            enabled: true,
            param_overrides: {
                steps: { input_schema: 'StepsSchema' },
            },
        }
        const resolved = makeResolved({
            method: 'POST',
            operation: {
                operationId: 'things_create',
                parameters: [],
                requestBody: {
                    content: {
                        'application/json': {
                            schema: {
                                properties: {
                                    steps: { type: 'object' },
                                    name: { type: 'string' },
                                },
                            },
                        },
                    },
                },
            },
        })

        const result = composeToolSchema(config, resolved, makeSpec(), stubGetQuerySchema)

        expect(result.schemaExpr).toContain('.extend({ steps: StepsSchema })')
    })
})

describe('generateToolCode with input_schema', () => {
    it('uses custom schema import when input_schema is set', () => {
        const config: ToolConfig = {
            operation: 'things_create',
            enabled: true,
            input_schema: 'ThingCreateSchema',
            scopes: ['thing:write'],
            annotations: { readOnly: false, destructive: false, idempotent: false },
        }
        const resolved = makeResolved({ method: 'POST' })

        const result = generateToolCode(
            'things-create',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.toolInputsImports).toEqual(['ThingCreateSchema'])
        expect(result.orvalImports).toEqual([])
        expect(result.code).toMatchSnapshot()
    })

    it('generates body forwarding for POST with input_schema', () => {
        const config: ToolConfig = {
            operation: 'things_create',
            enabled: true,
            input_schema: 'ThingCreateSchema',
        }
        const resolved = makeResolved({ method: 'POST' })

        const result = generateToolCode(
            'things-create',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.code).toContain('const parsedParams = ThingsCreateSchema.parse(params)')
        expect(result.code).toContain('body: parsedParams')
    })

    it('generates query forwarding for GET with input_schema', () => {
        const config: ToolConfig = {
            operation: 'things_list',
            enabled: true,
            input_schema: 'ThingListSchema',
        }
        const resolved = makeResolved({ method: 'GET' })

        const result = generateToolCode(
            'things-list',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.code).toContain('const parsedParams = ThingsListSchema.parse(params)')
        expect(result.code).toContain('query: parsedParams')
    })

    it('uses response_type override for custom input schema tools', () => {
        const config: ToolConfig = {
            operation: 'things_list',
            enabled: true,
            input_schema: 'ThingListSchema',
            response_type: "Omit<Schemas.ThingList, 'results'> & { results: unknown[] }",
        }
        const resolved = makeResolved({ method: 'GET' })

        const result = generateToolCode(
            'things-list',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.code).toContain(
            "const thingsList = (): ToolBase<typeof ThingsListSchema, Omit<Schemas.ThingList, 'results'> & { results: unknown[] }>"
        )
        expect(result.code).toContain(
            "const result = await context.api.request<Omit<Schemas.ThingList, 'results'> & { results: unknown[] }>({"
        )
    })

    it('destructures path params for input_schema with path params', () => {
        const config: ToolConfig = {
            operation: 'things_update',
            enabled: true,
            input_schema: 'ThingUpdateSchema',
        }
        const resolved = makeResolved({
            method: 'PATCH',
            path: '/api/projects/{project_id}/things/{id}/',
        })

        const result = generateToolCode(
            'things-update',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.code).toContain('id, ...body')
        expect(result.code).toContain('${encodeURIComponent(String(id))}')
    })

    it('destructures path params into query for GET with path params', () => {
        const config: ToolConfig = {
            operation: 'things_retrieve',
            enabled: true,
            input_schema: 'ThingGetSchema',
        }
        const resolved = makeResolved({
            method: 'GET',
            path: '/api/projects/{project_id}/things/{id}/',
        })

        const result = generateToolCode(
            'things-retrieve',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.code).toContain('id, ...query')
    })

    it('applies enrich_url with input_schema', () => {
        const config: ToolConfig = {
            operation: 'things_create',
            enabled: true,
            input_schema: 'ThingCreateSchema',
            enrich_url: '{id}',
        }
        const resolved = makeResolved({ method: 'POST' })

        const result = generateToolCode(
            'things-create',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.code).toMatchSnapshot()
    })

    it('applies list enrichment with input_schema', () => {
        const config: ToolConfig = {
            operation: 'things_list',
            enabled: true,
            input_schema: 'ThingListSchema',
            list: true,
            enrich_url: '{id}',
        }
        const resolved = makeResolved({ method: 'GET' })

        const result = generateToolCode(
            'things-list',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )
        expect(result.code).toMatchSnapshot()
    })
})

describe('generateToolCode without input_schema', () => {
    it('returns orvalImports and no toolInputsImports', () => {
        const config: ToolConfig = {
            operation: 'things_list',
            enabled: true,
        }
        const resolved = makeResolved({
            operation: {
                operationId: 'things_list',
                parameters: [
                    {
                        in: 'path',
                        name: 'project_id',
                        required: true,
                        schema: { type: 'string' },
                    },
                ],
            },
        })

        const result = generateToolCode(
            'things-list',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.toolInputsImports).toEqual([])
    })

    it('collects toolInputsImports from param_overrides', () => {
        const config: ToolConfig = {
            operation: 'things_create',
            enabled: true,
            param_overrides: {
                steps: { input_schema: 'StepsSchema' },
            },
        }
        const resolved = makeResolved({
            method: 'POST',
            operation: {
                operationId: 'things_create',
                parameters: [],
                requestBody: {
                    content: {
                        'application/json': {
                            schema: {
                                properties: {
                                    steps: { type: 'object' },
                                    name: { type: 'string' },
                                },
                            },
                        },
                    },
                },
            },
        })

        const result = generateToolCode(
            'things-create',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.toolInputsImports).toContain('StepsSchema')
        expect(result.code).toContain('.extend({ steps: StepsSchema })')
    })
})

describe('rename_params', () => {
    it('swaps field names in schema expression and tracks renames', () => {
        const config: ToolConfig = {
            operation: 'things_create',
            enabled: true,
            rename_params: { $unset: 'property_key' },
        }
        const resolved = makeResolved({
            method: 'POST',
            operation: {
                operationId: 'things_create',
                parameters: [],
                requestBody: {
                    content: {
                        'application/json': {
                            schema: {
                                properties: {
                                    $unset: { type: 'string' },
                                },
                            },
                        },
                    },
                },
            },
        })

        const result = composeToolSchema(config, resolved, makeSpec(), stubGetQuerySchema)

        expect(result.schemaExpr).toContain(".omit({ '$unset': true })")
        expect(result.schemaExpr).toContain(".extend({ property_key: ThingsCreateBody.shape['$unset'] })")
        expect(result.bodyFieldNames).toContain('property_key')
        expect(result.bodyFieldNames).not.toContain('$unset')
        expect(result.renamedFields).toEqual({ property_key: '$unset' })
    })

    it('generates handler that maps alias to original body key', () => {
        const config: ToolConfig = {
            operation: 'things_create',
            enabled: true,
            rename_params: { $unset: 'property_key' },
        }
        const resolved = makeResolved({
            method: 'POST',
            operation: {
                operationId: 'things_create',
                parameters: [],
                requestBody: {
                    content: {
                        'application/json': {
                            schema: {
                                properties: {
                                    $unset: { type: 'string' },
                                },
                            },
                        },
                    },
                },
            },
        })

        const result = generateToolCode(
            'things-create',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.code).toContain('params.property_key !== undefined')
        expect(result.code).toContain("body['$unset'] = params.property_key")
        expect(result.code).not.toContain('params.$unset')
    })
})

describe('QueryWrapperToolConfigSchema validation', () => {
    it.each([true, false] as const)('accepts use_optimized_output: %s', (value) => {
        const result = QueryWrapperToolConfigSchema.safeParse({
            schema_ref: 'AssistantTrendsQuery',
            enabled: true,
            scopes: ['query:read'],
            annotations: { readOnly: true, destructive: false, idempotent: true },
            use_optimized_output: value,
        })
        expect(result.success).toBe(true)
    })

    it('rejects non-boolean use_optimized_output values', () => {
        const result = QueryWrapperToolConfigSchema.safeParse({
            schema_ref: 'AssistantTrendsQuery',
            enabled: true,
            use_optimized_output: 'optimized',
        })
        expect(result.success).toBe(false)
    })

    it('accepts system_prompt_hint on query wrappers', () => {
        const result = QueryWrapperToolConfigSchema.safeParse({
            schema_ref: 'AssistantTrendsQuery',
            enabled: true,
            scopes: ['query:read'],
            annotations: { readOnly: true, destructive: false, idempotent: true },
            system_prompt_hint: 'Time series, aggregations, formulas',
        })
        expect(result.success).toBe(true)
    })

    it('accepts system_prompt_hint on standard tools', () => {
        const result = ToolConfigSchema.safeParse({
            operation: 'logs_query_create',
            enabled: true,
            system_prompt_hint: 'Log filtering by severity/service/attribute',
        })
        expect(result.success).toBe(true)
    })
})

describe('system_prompt_hint flows into tool definitions', () => {
    it('propagates system_prompt_hint from wrapper YAML into the generated definition', () => {
        const wrapperConfig: EnabledQueryWrapperToolConfig = {
            schema_ref: 'AssistantTrendsQuery',
            enabled: true,
            scopes: ['query:read'],
            annotations: { readOnly: true, destructive: false, idempotent: true },
            system_prompt_hint: 'Time series, aggregations, formulas',
        }
        const definitions = generateQueryWrapperDefinitionsJson(
            { category: 'Query wrappers', feature: 'insights', wrappers: {} },
            [['query-trends', wrapperConfig]],
            '/tmp'
        ) as Record<string, { system_prompt_hint?: string }>
        expect(definitions['query-trends']?.system_prompt_hint).toBe('Time series, aggregations, formulas')
    })

    it('omits system_prompt_hint from the wrapper definition when not set', () => {
        const wrapperConfig: EnabledQueryWrapperToolConfig = {
            schema_ref: 'AssistantTrendsQuery',
            enabled: true,
            scopes: ['query:read'],
            annotations: { readOnly: true, destructive: false, idempotent: true },
        }
        const definitions = generateQueryWrapperDefinitionsJson(
            { category: 'Query wrappers', feature: 'insights', wrappers: {} },
            [['query-trends', wrapperConfig]],
            '/tmp'
        )
        expect((definitions['query-trends'] as Record<string, unknown>).system_prompt_hint).toBeUndefined()
    })

    it('propagates system_prompt_hint from standard tool YAML into the generated definition', () => {
        const toolConfig: EnabledToolConfig = {
            operation: 'logs_query_create',
            enabled: true,
            scopes: ['logs:read'],
            annotations: { readOnly: true, destructive: false, idempotent: true },
            system_prompt_hint: 'Log filtering by severity/service/attribute',
        }
        const resolved: ResolvedOperation = {
            method: 'POST',
            path: '/api/projects/{project_id}/logs/query/',
            operation: { operationId: 'logs_query_create', description: 'Query logs' },
        }
        const definitions = generateDefinitionsJson([
            {
                config: { category: 'Logs', feature: 'logs', url_prefix: '/logs', tools: {} },
                enabledTools: [['query-logs', toolConfig, resolved]],
                enabledWrappers: [],
                yamlDir: '/tmp',
            },
        ]) as Record<string, { system_prompt_hint?: string }>
        expect(definitions['query-logs']?.system_prompt_hint).toBe('Log filtering by severity/service/attribute')
    })
})

describe('generateQueryWrapperFile with use_optimized_output', () => {
    const minimalQuerySchema = {
        definitions: {
            AssistantTestQuery: {
                type: 'object' as const,
                properties: {
                    kind: { const: 'TestQuery', type: 'string' as const },
                },
                required: ['kind'],
            },
        },
    }

    it('emits outputFormat: optimized when use_optimized_output is true', () => {
        const { code } = generateQueryWrapperFile(
            {
                category: 'Test',
                feature: 'test',
                wrappers: {
                    'query-test': {
                        schema_ref: 'AssistantTestQuery',
                        enabled: true,
                        scopes: ['query:read'],
                        annotations: { readOnly: true, destructive: false, idempotent: true },
                        use_optimized_output: true,
                    },
                },
            },
            'test.yaml',
            minimalQuerySchema
        )

        expect(code).toContain("outputFormat: 'optimized'")
    })

    it.each([false, undefined] as const)('emits outputFormat: json when use_optimized_output is %s', (value) => {
        const { code } = generateQueryWrapperFile(
            {
                category: 'Test',
                feature: 'test',
                wrappers: {
                    'query-test': {
                        schema_ref: 'AssistantTestQuery',
                        enabled: true,
                        scopes: ['query:read'],
                        annotations: { readOnly: true, destructive: false, idempotent: true },
                        ...(value === undefined ? {} : { use_optimized_output: value }),
                    },
                },
            },
            'test.yaml',
            minimalQuerySchema
        )

        expect(code).toContain("outputFormat: 'json'")
    })

    it('extends the wrapper schema with an output_format input when use_optimized_output is true', () => {
        const { code } = generateQueryWrapperFile(
            {
                category: 'Test',
                feature: 'test',
                wrappers: {
                    'query-test': {
                        schema_ref: 'AssistantTestQuery',
                        enabled: true,
                        scopes: ['query:read'],
                        annotations: { readOnly: true, destructive: false, idempotent: true },
                        use_optimized_output: true,
                    },
                },
            },
            'test.yaml',
            minimalQuerySchema
        )

        expect(code).toContain('QueryTestSchema = AssistantTestQuery.extend({')
        expect(code).toContain('output_format: z')
        expect(code).toContain(".enum(['optimized', 'json'])")
        expect(code).toContain(".default('optimized')")
    })

    it('does not expose an output_format input when use_optimized_output is false', () => {
        const { code } = generateQueryWrapperFile(
            {
                category: 'Test',
                feature: 'test',
                wrappers: {
                    'query-test': {
                        schema_ref: 'AssistantTestQuery',
                        enabled: true,
                        scopes: ['query:read'],
                        annotations: { readOnly: true, destructive: false, idempotent: true },
                    },
                },
            },
            'test.yaml',
            minimalQuerySchema
        )

        expect(code).not.toContain('output_format: z')
    })
})

describe('ToolConfigSchema validation', () => {
    const validBase = {
        operation: 'things_create',
        enabled: true,
        input_schema: 'ThingCreateSchema',
    }

    const conflictCases = [
        {
            name: 'rejects input_schema with include_params',
            extra: { include_params: ['name'] },
        },
        {
            name: 'rejects input_schema with exclude_params',
            extra: { exclude_params: ['name'] },
        },
        {
            name: 'rejects input_schema with param_overrides',
            extra: { param_overrides: { name: { description: 'x' } } },
        },
    ]

    it.each(conflictCases)('$name', ({ extra }) => {
        const result = ToolConfigSchema.safeParse({ ...validBase, ...extra })
        expect(result.success).toBe(false)
    })

    it('allows input_schema without include_params, exclude_params, or param_overrides', () => {
        const result = ToolConfigSchema.safeParse(validBase)
        expect(result.success).toBe(true)
    })

    it('accepts response_type override', () => {
        const result = ToolConfigSchema.safeParse({
            operation: 'things_list',
            enabled: true,
            response_type: "Omit<Schemas.ThingList, 'results'>",
        })
        expect(result.success).toBe(true)
    })

    it('rejects response.include with response.exclude', () => {
        const result = ToolConfigSchema.safeParse({
            operation: 'things_list',
            enabled: true,
            response: { include: ['id'], exclude: ['name'] },
        })
        expect(result.success).toBe(false)
    })

    it('accepts response.include alone', () => {
        const result = ToolConfigSchema.safeParse({
            operation: 'things_list',
            enabled: true,
            response: { include: ['id', 'name'] },
        })
        expect(result.success).toBe(true)
    })

    it('accepts response.exclude alone', () => {
        const result = ToolConfigSchema.safeParse({
            operation: 'things_list',
            enabled: true,
            response: { exclude: ['filters', 'created_by'] },
        })
        expect(result.success).toBe(true)
    })
})

// ------------------------------------------------------------------
// buildResponseFilter
// ------------------------------------------------------------------

describe('buildResponseFilter', () => {
    it('returns empty code when no response filtering configured', () => {
        const config: ToolConfig = { operation: 'things_list', enabled: true }
        const result = buildResponseFilter(config)
        expect(result.code).toBe('')
        expect(result.helperImport).toBeNull()
    })

    it('generates pickResponseFields for detail endpoint with response.include', () => {
        const config: ToolConfig = {
            operation: 'things_retrieve',
            enabled: true,
            response: { include: ['id', 'name', 'status'] },
        }
        const result = buildResponseFilter(config)
        expect(result.code).toContain('pickResponseFields(result, ')
        expect(result.code).toContain("'id', 'name', 'status'")
        expect(result.helperImport).toBe('pickResponseFields')
    })

    it('generates omitResponseFields for detail endpoint with response.exclude', () => {
        const config: ToolConfig = {
            operation: 'things_retrieve',
            enabled: true,
            response: { exclude: ['filters', 'created_by'] },
        }
        const result = buildResponseFilter(config)
        expect(result.code).toContain('omitResponseFields(result, ')
        expect(result.code).toContain("'filters', 'created_by'")
        expect(result.helperImport).toBe('omitResponseFields')
    })

    it('maps pickResponseFields over results for list endpoint with response.include', () => {
        const config: ToolConfig = {
            operation: 'things_list',
            enabled: true,
            list: true,
            response: { include: ['id', 'key'] },
        }
        const result = buildResponseFilter(config)
        expect(result.code).toContain('(result.results ?? []).map')
        expect(result.code).toContain('pickResponseFields(item, ')
        expect(result.helperImport).toBe('pickResponseFields')
    })

    it('maps omitResponseFields over results for list endpoint with response.exclude', () => {
        const config: ToolConfig = {
            operation: 'things_list',
            enabled: true,
            list: true,
            response: { exclude: ['large_blob'] },
        }
        const result = buildResponseFilter(config)
        expect(result.code).toContain('(result.results ?? []).map')
        expect(result.code).toContain('omitResponseFields(item, ')
        expect(result.helperImport).toBe('omitResponseFields')
    })

    it('preserves wildcard dot-path patterns in generated code', () => {
        const config: ToolConfig = {
            operation: 'things_retrieve',
            enabled: true,
            response: { exclude: ['filters.groups.*.properties', 'created_by'] },
        }
        const result = buildResponseFilter(config)
        expect(result.code).toContain("'filters.groups.*.properties'")
        expect(result.code).toContain("'created_by'")
    })
})

// ------------------------------------------------------------------
// generateToolCode — response filtering
// ------------------------------------------------------------------

describe('generateToolCode with response filtering', () => {
    it('generates pickResponseFields and uses filtered var for enrichment', () => {
        const config: ToolConfig = {
            operation: 'things_retrieve',
            enabled: true,
            response: { include: ['id', 'name'] },
            enrich_url: '{id}',
        }
        const resolved = makeResolved({
            method: 'GET',
            path: '/api/projects/{project_id}/things/{id}/',
        })

        const result = generateToolCode(
            'things-get',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.code).toContain('pickResponseFields(result, ')
        expect(result.code).toContain('const filtered = ')
        expect(result.code).toContain('withPostHogUrl(context, filtered,')
        expect(result.responseFilterImport).toBe('pickResponseFields')
    })

    it('generates omitResponseFields for detail endpoint', () => {
        const config: ToolConfig = {
            operation: 'things_retrieve',
            enabled: true,
            response: { exclude: ['filters'] },
        }
        const resolved = makeResolved({
            method: 'GET',
            path: '/api/projects/{project_id}/things/{id}/',
        })

        const result = generateToolCode(
            'things-get',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.code).toContain('omitResponseFields(result, ')
        expect(result.code).toContain('return filtered')
        expect(result.responseFilterImport).toBe('omitResponseFields')
    })

    it('returns null responseFilterImport when no filtering', () => {
        const config: ToolConfig = {
            operation: 'things_list',
            enabled: true,
        }
        const resolved = makeResolved()

        const result = generateToolCode(
            'things-list',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.responseFilterImport).toBeNull()
    })

    it('generates response filtering for list endpoint with enrichment', () => {
        const config: ToolConfig = {
            operation: 'things_list',
            enabled: true,
            list: true,
            enrich_url: '{id}',
            response: { exclude: ['large_field'] },
        }
        const resolved = makeResolved()

        const result = generateToolCode(
            'things-list',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.code).toContain('(result.results ?? []).map((item: any) => omitResponseFields(item, ')
        expect(result.code).toContain('...filtered,')
        expect(result.code).toContain('(filtered.results ?? []).map')
        expect(result.responseFilterImport).toBe('omitResponseFields')
    })
})

describe('path parameter encoding', () => {
    it('wraps project_id with encodeURIComponent in generated paths', () => {
        const config: ToolConfig = {
            operation: 'things_list',
            enabled: true,
        }
        const resolved = makeResolved()

        const result = generateToolCode(
            'things-list',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.code).toContain('${encodeURIComponent(String(projectId))}')
        expect(result.code).not.toMatch(/\$\{projectId\}/)
    })

    it('wraps organization_id with encodeURIComponent in generated paths', () => {
        const config: ToolConfig = {
            operation: 'members_list',
            enabled: true,
        }
        const resolved = makeResolved({
            path: '/api/organizations/{organization_id}/members/',
            operation: {
                operationId: 'members_list',
                parameters: [{ name: 'organization_id', in: 'path', required: true, schema: { type: 'string' } }],
            },
        })

        const result = generateToolCode(
            'org-members-list',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.code).toContain('${encodeURIComponent(String(orgId))}')
        expect(result.code).not.toMatch(/\$\{orgId\}/)
    })

    it('wraps user-provided path params with encodeURIComponent', () => {
        const config: ToolConfig = {
            operation: 'things_retrieve',
            enabled: true,
        }
        const resolved = makeResolved({
            method: 'GET',
            path: '/api/projects/{project_id}/things/{id}/',
            operation: {
                operationId: 'things_retrieve',
                parameters: [
                    { name: 'project_id', in: 'path', required: true, schema: { type: 'string' } },
                    { name: 'id', in: 'path', required: true, schema: { type: 'integer' } },
                ],
            },
        })

        const result = generateToolCode(
            'things-get',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        expect(result.code).toContain('${encodeURIComponent(String(params.id))}')
        expect(result.code).not.toMatch(/\$\{params\.id\}/)
    })

    it('wraps fallback-resolved params with encodeURIComponent', () => {
        const config: ToolConfig = {
            operation: 'things_retrieve',
            enabled: true,
            param_overrides: {
                id: { optional: true, fallback: 'orgId', description: 'Optional ID' },
            },
        }
        const resolved = makeResolved({
            method: 'GET',
            path: '/api/projects/{project_id}/things/{id}/',
            operation: {
                operationId: 'things_retrieve',
                parameters: [
                    { name: 'project_id', in: 'path', required: true, schema: { type: 'string' } },
                    { name: 'id', in: 'path', required: true, schema: { type: 'string' } },
                ],
            },
        })

        const result = generateToolCode(
            'things-get',
            config,
            resolved,
            defaultCategory,
            makeSpec(),
            new Set<string>(),
            stubGetQuerySchema
        )

        // Fallback params use local variable (no params. prefix) but still get encoded
        expect(result.code).toContain('${encodeURIComponent(String(id))}')
        expect(result.code).not.toMatch(/\$\{id\}[^)]/)
    })
})
