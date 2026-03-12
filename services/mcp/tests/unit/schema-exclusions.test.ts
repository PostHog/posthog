import { describe, expect, it } from 'vitest'

import { applyNestedExclusions } from '../../scripts/lib/schema-exclusions.mjs'

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

        expect(spec.components.schemas.ActionStep.properties).not.toHaveProperty('selector_regex')
        expect(spec.components.schemas.ActionStep.properties).toHaveProperty('event')
        expect(spec.components.schemas.ActionStep.properties).toHaveProperty('tag_name')
        expect(spec.components.schemas.ActionStep.required).toEqual(['event'])
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

        // Even a non-dotted single-segment path works for direct property removal
        applyNestedExclusions(spec, new Map([['things_create', ['secret']]]))

        expect(spec.components.schemas.Thing.properties).not.toHaveProperty('secret')
        expect(spec.components.schemas.Thing.required).toEqual(['name'])
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
})
