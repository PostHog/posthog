import { describe, expect, it } from 'vitest'

import { filterSchemaByOperationIds } from '../index.mjs'

const buildSpec = () => ({
    openapi: '3.1.0',
    info: {
        title: 'Test API',
        version: '1.0.0',
    },
    paths: {
        '/api/widgets/': {
            post: {
                operationId: 'widgets_create',
                requestBody: {
                    content: {
                        'application/json': {
                            schema: { $ref: '#/components/schemas/WidgetCreateRequest' },
                        },
                    },
                },
                responses: {
                    200: {
                        description: 'Created',
                        headers: {
                            etag: {
                                schema: { type: 'string' },
                            },
                        },
                        content: {
                            'application/json': {
                                schema: { $ref: '#/components/schemas/WidgetResponse' },
                            },
                        },
                    },
                },
            },
        },
    },
    components: {
        schemas: {
            WidgetCreateRequest: {
                type: 'object',
                properties: {
                    name: { type: 'string' },
                    metadata: { $ref: '#/components/schemas/WidgetCreateMeta' },
                },
            },
            WidgetCreateMeta: {
                type: 'object',
                properties: {
                    source: { type: 'string' },
                },
            },
            WidgetResponse: {
                type: 'object',
                properties: {
                    id: { type: 'string' },
                    nested: { $ref: '#/components/schemas/WidgetResponseNested' },
                },
            },
            WidgetResponseNested: {
                type: 'object',
                properties: {
                    count: { type: 'number' },
                },
            },
            ErrorResponse: {
                type: 'object',
                properties: {
                    detail: { type: 'string' },
                },
            },
        },
    },
})

describe('filterSchemaByOperationIds', () => {
    it('includes response refs by default', () => {
        const filtered = filterSchemaByOperationIds(buildSpec(), new Set(['widgets_create']))

        expect(filtered.components.schemas).toHaveProperty('WidgetCreateRequest')
        expect(filtered.components.schemas).toHaveProperty('WidgetCreateMeta')
        expect(filtered.components.schemas).toHaveProperty('WidgetResponse')
        expect(filtered.components.schemas).toHaveProperty('WidgetResponseNested')
    })

    it('excludes response refs when includeResponseSchemas is false while keeping request refs', () => {
        const filtered = filterSchemaByOperationIds(buildSpec(), new Set(['widgets_create']), {
            includeResponseSchemas: false,
        })

        expect(filtered.components.schemas).toHaveProperty('WidgetCreateRequest')
        expect(filtered.components.schemas).toHaveProperty('WidgetCreateMeta')
        expect(filtered.components.schemas).not.toHaveProperty('WidgetResponse')
        expect(filtered.components.schemas).not.toHaveProperty('WidgetResponseNested')
    })

    it('preserves component parameters referenced by filtered operations', () => {
        const spec = buildSpec()
        spec.paths['/api/widgets/'].post.parameters = [
            { $ref: '#/components/parameters/ProjectIdPath' },
            { $ref: '#/components/parameters/FormatQuery' },
            { $ref: '#/components/parameters/FilterParam' },
        ]
        spec.components.parameters = {
            ProjectIdPath: {
                in: 'path',
                name: 'project_id',
                required: true,
                schema: { type: 'string' },
                description: 'The project ID.',
            },
            FormatQuery: {
                in: 'query',
                name: 'format',
                schema: { type: 'string' },
            },
            // Param that references a component schema — should pull that schema in too.
            FilterParam: {
                in: 'query',
                name: 'filter',
                schema: { $ref: '#/components/schemas/WidgetCreateMeta' },
            },
            UnreferencedParam: {
                in: 'query',
                name: 'stale',
                schema: { type: 'string' },
            },
        }

        const filtered = filterSchemaByOperationIds(spec, new Set(['widgets_create']))

        expect(filtered.components.parameters).toHaveProperty('ProjectIdPath')
        expect(filtered.components.parameters).toHaveProperty('FormatQuery')
        expect(filtered.components.parameters).toHaveProperty('FilterParam')
        expect(filtered.components.parameters).not.toHaveProperty('UnreferencedParam')
        expect(filtered.components.parameters.ProjectIdPath.description).toBe('The project ID.')

        // FilterParam's inner schema ref should pull WidgetCreateMeta into the filtered schemas.
        expect(filtered.components.schemas).toHaveProperty('WidgetCreateMeta')
    })

    it('omits components.parameters when no operation references one', () => {
        const filtered = filterSchemaByOperationIds(buildSpec(), new Set(['widgets_create']))

        expect(filtered.components).not.toHaveProperty('parameters')
    })

    it('keeps response status keys and only description when includeResponseSchemas is false', () => {
        const spec = buildSpec()
        spec.paths['/api/widgets/'].post.responses = {
            200: {
                description: 'Created',
                headers: {
                    etag: {
                        schema: { type: 'string' },
                    },
                },
                content: {
                    'application/json': {
                        schema: { $ref: '#/components/schemas/WidgetResponse' },
                    },
                },
            },
            400: {
                $ref: '#/components/responses/BadRequest',
            },
            404: {
                content: {
                    'application/json': {
                        schema: { $ref: '#/components/schemas/ErrorResponse' },
                    },
                },
            },
        }

        const filtered = filterSchemaByOperationIds(spec, new Set(['widgets_create']), {
            includeResponseSchemas: false,
        })
        const responses = filtered.paths['/api/widgets/'].post.responses

        expect(Object.keys(responses)).toEqual(['200', '400', '404'])
        expect(responses['200']).toEqual({ description: 'Created' })
        expect(responses['400']).toEqual({ description: '' })
        expect(responses['404']).toEqual({ description: '' })

        for (const response of Object.values(responses)) {
            expect(typeof response.description).toBe('string')
            expect(response).not.toHaveProperty('$ref')
            expect(response).not.toHaveProperty('content')
            expect(response).not.toHaveProperty('headers')
        }
    })
})
