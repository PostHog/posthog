import { describe, expect, it } from 'vitest'

import { applyNestedExclusions } from '../index.mjs'

describe('applyNestedExclusions', () => {
    it('removes a nested property via wildcard path (array items)', () => {
        const spec = {
            paths: {
                '/api/projects/{project_id}/actions/': {
                    post: {
                        operationId: 'actions_create',
                        requestBody: {
                            content: {
                                'application/json': {
                                    schema: { $ref: '#/components/schemas/Action' },
                                },
                            },
                        },
                    },
                },
            },
            components: {
                schemas: {
                    Action: {
                        type: 'object',
                        properties: {
                            name: { type: 'string' },
                            steps: {
                                type: 'array',
                                items: {
                                    $ref: '#/components/schemas/ActionStep',
                                },
                            },
                        },
                    },
                    ActionStep: {
                        type: 'object',
                        required: ['event', 'selector_regex'],
                        properties: {
                            event: { type: 'string' },
                            selector_regex: { type: 'string' },
                            tag_name: { type: 'string' },
                        },
                    },
                },
            },
        }

        applyNestedExclusions(spec, new Map([['actions_create', ['steps.*.selector_regex']]]))

        // Shared component schemas must be untouched
        expect(spec.components.schemas.ActionStep.properties).toHaveProperty('selector_regex')
        expect(spec.components.schemas.ActionStep.required).toEqual(['event', 'selector_regex'])
        expect(spec.components.schemas.Action.properties.steps.items).toHaveProperty('$ref')

        // The operation's inlined copy should have the field removed
        const inlinedBody =
            spec.paths['/api/projects/{project_id}/actions/'].post.requestBody.content['application/json'].schema
        expect(inlinedBody).not.toHaveProperty('$ref')
        const inlinedStep = inlinedBody.properties.steps.items
        expect(inlinedStep).not.toHaveProperty('$ref')
        expect(inlinedStep.properties).not.toHaveProperty('selector_regex')
        expect(inlinedStep.properties).toHaveProperty('event')
        expect(inlinedStep.properties).toHaveProperty('tag_name')
        expect(inlinedStep.required).toEqual(['event'])
    })

    it('removes a deep nested property via double wildcard', () => {
        const spec = {
            paths: {
                '/api/things/': {
                    post: {
                        operationId: 'things_create',
                        requestBody: {
                            content: {
                                'application/json': {
                                    schema: {
                                        type: 'object',
                                        properties: {
                                            steps: {
                                                type: 'array',
                                                items: {
                                                    type: 'object',
                                                    properties: {
                                                        properties: {
                                                            type: 'array',
                                                            items: {
                                                                type: 'object',
                                                                required: ['key', 'value'],
                                                                properties: {
                                                                    key: { type: 'string' },
                                                                    value: { type: 'string' },
                                                                },
                                                            },
                                                        },
                                                    },
                                                },
                                            },
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
            components: { schemas: {} },
        }

        applyNestedExclusions(spec, new Map([['things_create', ['steps.*.properties.*.value']]]))

        const innerProps =
            spec.paths['/api/things/'].post.requestBody.content['application/json'].schema.properties.steps.items
                .properties.properties.items.properties
        expect(innerProps).not.toHaveProperty('value')
        expect(innerProps).toHaveProperty('key')
    })

    it('removes a property via object path (no wildcard)', () => {
        const spec = {
            paths: {
                '/api/things/': {
                    post: {
                        operationId: 'things_create',
                        requestBody: {
                            content: {
                                'application/json': {
                                    schema: {
                                        type: 'object',
                                        properties: {
                                            config: {
                                                type: 'object',
                                                properties: {
                                                    keep: { type: 'string' },
                                                    remove: { type: 'string' },
                                                },
                                            },
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
            components: { schemas: {} },
        }

        applyNestedExclusions(spec, new Map([['things_create', ['config.remove']]]))

        const configProps =
            spec.paths['/api/things/'].post.requestBody.content['application/json'].schema.properties.config.properties
        expect(configProps).not.toHaveProperty('remove')
        expect(configProps).toHaveProperty('keep')
    })

    it('resolves $ref at the request body level', () => {
        const spec = {
            paths: {
                '/api/things/': {
                    post: {
                        operationId: 'things_create',
                        requestBody: {
                            content: {
                                'application/json': {
                                    schema: { $ref: '#/components/schemas/Thing' },
                                },
                            },
                        },
                    },
                },
            },
            components: {
                schemas: {
                    Thing: {
                        type: 'object',
                        required: ['name', 'secret'],
                        properties: {
                            name: { type: 'string' },
                            secret: { type: 'string' },
                        },
                    },
                },
            },
        }

        applyNestedExclusions(spec, new Map([['things_create', ['secret']]]))

        // Shared component schema must be untouched
        expect(spec.components.schemas.Thing.properties).toHaveProperty('secret')
        expect(spec.components.schemas.Thing.required).toContain('secret')

        // The operation's body should have an inlined clone without 'secret'
        const inlinedBody = spec.paths['/api/things/'].post.requestBody.content['application/json'].schema
        expect(inlinedBody).not.toHaveProperty('$ref')
        expect(inlinedBody.properties).not.toHaveProperty('secret')
        expect(inlinedBody.required).toEqual(['name'])
    })

    it('deletes required array when all required fields are excluded', () => {
        const spec = {
            paths: {
                '/api/things/': {
                    post: {
                        operationId: 'things_create',
                        requestBody: {
                            content: {
                                'application/json': {
                                    schema: {
                                        type: 'object',
                                        required: ['only_field'],
                                        properties: {
                                            only_field: { type: 'string' },
                                            optional: { type: 'string' },
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
            components: { schemas: {} },
        }

        applyNestedExclusions(spec, new Map([['things_create', ['only_field']]]))

        const bodySchema = spec.paths['/api/things/'].post.requestBody.content['application/json'].schema
        expect(bodySchema.properties).not.toHaveProperty('only_field')
        expect(bodySchema).not.toHaveProperty('required')
    })

    it('is a no-op for nonexistent paths', () => {
        const spec = {
            paths: {
                '/api/things/': {
                    post: {
                        operationId: 'things_create',
                        requestBody: {
                            content: {
                                'application/json': {
                                    schema: {
                                        type: 'object',
                                        properties: {
                                            name: { type: 'string' },
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
            components: { schemas: {} },
        }

        expect(() => applyNestedExclusions(spec, new Map([['things_create', ['nonexistent.*.field']]]))).not.toThrow()

        expect(
            spec.paths['/api/things/'].post.requestBody.content['application/json'].schema.properties
        ).toHaveProperty('name')
    })

    it('is a no-op for nonexistent operationId', () => {
        const spec = {
            paths: {},
            components: { schemas: {} },
        }

        expect(() => applyNestedExclusions(spec, new Map([['nonexistent_op', ['foo.bar']]]))).not.toThrow()
    })

    it('handles empty spec gracefully', () => {
        expect(() => applyNestedExclusions({}, new Map())).not.toThrow()
    })

    it('handles empty exclusions map', () => {
        const spec = {
            paths: {
                '/api/things/': {
                    post: {
                        operationId: 'things_create',
                        requestBody: {
                            content: {
                                'application/json': {
                                    schema: {
                                        type: 'object',
                                        properties: { name: { type: 'string' } },
                                    },
                                },
                            },
                        },
                    },
                },
            },
            components: { schemas: {} },
        }

        applyNestedExclusions(spec, new Map())
        expect(
            spec.paths['/api/things/'].post.requestBody.content['application/json'].schema.properties
        ).toHaveProperty('name')
    })

    it('does not mutate shared component schemas across operations', () => {
        const spec = {
            paths: {
                '/api/things/': {
                    post: {
                        operationId: 'things_create',
                        requestBody: {
                            content: {
                                'application/json': {
                                    schema: { $ref: '#/components/schemas/Thing' },
                                },
                            },
                        },
                    },
                },
                '/api/things/{id}/': {
                    get: {
                        operationId: 'things_retrieve',
                        responses: {
                            200: {
                                content: {
                                    'application/json': {
                                        schema: { $ref: '#/components/schemas/Thing' },
                                    },
                                },
                            },
                        },
                    },
                },
            },
            components: {
                schemas: {
                    Thing: {
                        type: 'object',
                        required: ['name', 'deleted'],
                        properties: {
                            name: { type: 'string' },
                            deleted: { type: 'boolean' },
                        },
                    },
                },
            },
        }

        applyNestedExclusions(spec, new Map([['things_create', ['deleted']]]))

        // The shared component schema must be untouched
        expect(spec.components.schemas.Thing.properties).toHaveProperty('deleted')
        expect(spec.components.schemas.Thing.required).toContain('deleted')

        // The create operation's body should be an inlined schema without 'deleted'
        const createBody = spec.paths['/api/things/'].post.requestBody.content['application/json'].schema
        expect(createBody).not.toHaveProperty('$ref')
        expect(createBody.properties).not.toHaveProperty('deleted')

        // The retrieve response still references the shared component
        const retrieveSchema = spec.paths['/api/things/{id}/'].get.responses[200].content['application/json'].schema
        expect(retrieveSchema).toHaveProperty('$ref', '#/components/schemas/Thing')
    })

    it('clones nested $ref schemas without mutating the component', () => {
        const spec = {
            paths: {
                '/api/things/': {
                    post: {
                        operationId: 'things_create',
                        requestBody: {
                            content: {
                                'application/json': {
                                    schema: { $ref: '#/components/schemas/Thing' },
                                },
                            },
                        },
                    },
                },
            },
            components: {
                schemas: {
                    Thing: {
                        type: 'object',
                        properties: {
                            name: { type: 'string' },
                            filters: { $ref: '#/components/schemas/ThingFilters' },
                        },
                    },
                    ThingFilters: {
                        type: 'object',
                        required: ['query', 'bytecode'],
                        properties: {
                            query: { type: 'string' },
                            bytecode: { type: 'string' },
                        },
                    },
                },
            },
        }

        applyNestedExclusions(spec, new Map([['things_create', ['filters.bytecode']]]))

        // Both component schemas must be untouched
        expect(spec.components.schemas.Thing.properties.filters).toHaveProperty('$ref')
        expect(spec.components.schemas.ThingFilters.properties).toHaveProperty('bytecode')
        expect(spec.components.schemas.ThingFilters.required).toContain('bytecode')

        // The operation's inlined schema should have bytecode removed from filters
        const inlinedBody = spec.paths['/api/things/'].post.requestBody.content['application/json'].schema
        expect(inlinedBody).not.toHaveProperty('$ref')
        const inlinedFilters = inlinedBody.properties.filters
        expect(inlinedFilters).not.toHaveProperty('$ref')
        expect(inlinedFilters.properties).not.toHaveProperty('bytecode')
        expect(inlinedFilters.properties).toHaveProperty('query')
        expect(inlinedFilters.required).toEqual(['query'])
    })
})
