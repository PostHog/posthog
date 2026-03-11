import { describe, expect, it } from 'vitest'

import { composeToolSchema, extractPathParams, generateToolCode } from '../../scripts/generate-tools'
import type { OpenApiSpec, ResolvedOperation } from '../../scripts/generate-tools'
import { ToolConfigSchema } from '../../scripts/yaml-config-schema'
import type { ToolConfig } from '../../scripts/yaml-config-schema'

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

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

// ------------------------------------------------------------------
// extractPathParams
// ------------------------------------------------------------------

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

// ------------------------------------------------------------------
// composeToolSchema — input_schema in param_overrides
// ------------------------------------------------------------------

describe('composeToolSchema', () => {
    it('returns empty toolInputsImports when no param_overrides have input_schema', () => {
        const config: ToolConfig = {
            operation: 'things_list',
            enabled: true,
        }
        const resolved = makeResolved()
        const result = composeToolSchema(config, resolved, makeSpec())

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
        const result = composeToolSchema(config, resolved, makeSpec())

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

        const result = composeToolSchema(config, resolved, makeSpec())

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

        const result = composeToolSchema(config, resolved, makeSpec())

        expect(result.schemaExpr).toContain('.extend({ steps: StepsSchema })')
    })
})

// ------------------------------------------------------------------
// generateToolCode — tool-level input_schema
// ------------------------------------------------------------------

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
            new Set<string>()
        )

        expect(result.toolInputsImports).toEqual(['ThingCreateSchema'])
        expect(result.orvalImports).toEqual([])
        expect(result.code).toContain('const ThingsCreateSchema = ThingCreateSchema')
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
            new Set<string>()
        )

        expect(result.code).toContain('body: params')
    })

    it('generates query forwarding for GET with input_schema', () => {
        const config: ToolConfig = {
            operation: 'things_list',
            enabled: true,
            input_schema: 'ThingListSchema',
        }
        const resolved = makeResolved({ method: 'GET' })

        const result = generateToolCode('things-list', config, resolved, defaultCategory, makeSpec(), new Set<string>())

        expect(result.code).toContain('query: params')
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
            new Set<string>()
        )

        expect(result.code).toContain('id, ...body')
        expect(result.code).toContain('${id}')
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
            new Set<string>()
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
            new Set<string>()
        )

        expect(result.code).toContain('_posthogUrl:')
        expect(result.code).toContain('getProjectBaseUrl')
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

        const result = generateToolCode('things-list', config, resolved, defaultCategory, makeSpec(), new Set<string>())

        expect(result.code).toContain('.results ?? result')
        expect(result.code).toContain('.map(')
    })
})

// ------------------------------------------------------------------
// generateToolCode — without input_schema (standard path)
// ------------------------------------------------------------------

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

        const result = generateToolCode('things-list', config, resolved, defaultCategory, makeSpec(), new Set<string>())

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
            new Set<string>()
        )

        expect(result.toolInputsImports).toContain('StepsSchema')
        expect(result.code).toContain('.extend({ steps: StepsSchema })')
    })
})

// ------------------------------------------------------------------
// ToolConfigSchema — input_schema conflicts
// ------------------------------------------------------------------

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
})
