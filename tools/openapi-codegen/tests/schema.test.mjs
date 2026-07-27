import { describe, expect, it } from 'vitest'

import {
    collectOpenApiPropertyTree,
    discoverCatalogEntryConfigPropertyKeys,
    discoverComponentSchemaNames,
    filterSchemaByOperationIds,
} from '../src/schema.mjs'

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

describe('discoverComponentSchemaNames', () => {
    it('finds schemas by suffix and merges explicit includes', () => {
        const filtered = filterSchemaByOperationIds(buildSpec(), new Set(['widgets_create']))

        expect(
            discoverComponentSchemaNames(filtered, {
                nameSuffix: 'Request',
                include: ['WidgetResponseNested'],
            })
        ).toEqual(['WidgetCreateRequest', 'WidgetResponseNested'])
    })
})

describe('discoverCatalogEntryConfigPropertyKeys', () => {
    it('maps widget_type to config property keys via catalog entry schemas', () => {
        const spec = buildSpec()
        spec.components.schemas.ErrorTrackingListWidgetTypeEnum = {
            enum: ['error_tracking_list'],
            type: 'string',
        }
        spec.components.schemas.ErrorTrackingListWidgetConfig = {
            type: 'object',
            properties: {
                limit: { type: 'integer' },
                orderBy: { type: 'string' },
            },
        }
        spec.components.schemas.ErrorTrackingListWidgetCatalogEntryOpenApi = {
            type: 'object',
            properties: {
                widget_type: { $ref: '#/components/schemas/ErrorTrackingListWidgetTypeEnum' },
                config_schema: { $ref: '#/components/schemas/ErrorTrackingListWidgetConfig' },
            },
        }
        spec.paths['/api/widget_catalog/'] = {
            get: {
                operationId: 'widget_catalog_retrieve',
                responses: {
                    200: {
                        content: {
                            'application/json': {
                                schema: { $ref: '#/components/schemas/WidgetCatalogResponse' },
                            },
                        },
                    },
                },
            },
        }
        spec.components.schemas.WidgetCatalogResponse = {
            type: 'object',
            properties: {
                results: {
                    type: 'array',
                    items: { $ref: '#/components/schemas/ErrorTrackingListWidgetCatalogEntryOpenApi' },
                },
            },
        }

        const filtered = filterSchemaByOperationIds(spec, new Set(['widget_catalog_retrieve']))
        expect(
            discoverCatalogEntryConfigPropertyKeys(filtered, {
                entrySuffix: 'CatalogEntryOpenApi',
                typeField: 'widget_type',
                configField: 'config_schema',
            })
        ).toEqual({
            propertyKeys: {
                error_tracking_list: ['limit', 'orderBy'],
            },
        })
    })

    it('collects nested property trees when requested', () => {
        const spec = buildSpec()
        spec.components.schemas.ErrorTrackingListWidgetTypeEnum = {
            enum: ['error_tracking_list'],
            type: 'string',
        }
        spec.components.schemas.WidgetAssigneeFilter = {
            type: 'object',
            properties: {
                id: { type: 'string' },
                type: { enum: ['user', 'role'], type: 'string' },
            },
        }
        spec.components.schemas.ErrorTrackingListWidgetConfig = {
            type: 'object',
            properties: {
                limit: { type: 'integer' },
                assignee: { $ref: '#/components/schemas/WidgetAssigneeFilter' },
            },
        }
        spec.components.schemas.ErrorTrackingListWidgetCatalogEntryOpenApi = {
            type: 'object',
            properties: {
                widget_type: { $ref: '#/components/schemas/ErrorTrackingListWidgetTypeEnum' },
                config_schema: { $ref: '#/components/schemas/ErrorTrackingListWidgetConfig' },
            },
        }
        spec.paths['/api/widget_catalog/'] = {
            get: {
                operationId: 'widget_catalog_retrieve',
                responses: {
                    200: {
                        content: {
                            'application/json': {
                                schema: { $ref: '#/components/schemas/WidgetCatalogResponse' },
                            },
                        },
                    },
                },
            },
        }
        spec.components.schemas.WidgetCatalogResponse = {
            type: 'object',
            properties: {
                results: {
                    type: 'array',
                    items: { $ref: '#/components/schemas/ErrorTrackingListWidgetCatalogEntryOpenApi' },
                },
            },
        }

        const filtered = filterSchemaByOperationIds(spec, new Set(['widget_catalog_retrieve']))
        const { propertyTrees } = discoverCatalogEntryConfigPropertyKeys(filtered, {
            includePropertyTrees: true,
        })

        expect(propertyTrees.error_tracking_list).toEqual({
            limit: { $type: 'integer' },
            assignee: {
                id: { $type: 'string' },
                type: { $enum: ['role', 'user'] },
            },
        })
        expect(collectOpenApiPropertyTree('WidgetAssigneeFilter', filtered.components.schemas)).toEqual({
            id: { $type: 'string' },
            type: { $enum: ['role', 'user'] },
        })
    })
})
