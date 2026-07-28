import { describe, expect, it } from 'vitest'

import { stripEnumMinLength, stripUuidFormat } from '../../scripts/lib/schema-transforms.mjs'

describe('stripEnumMinLength', () => {
    it('removes minLength from a schema with enum', () => {
        const schema = {
            type: 'string',
            enum: ['Cohort', 'FeatureFlag', 'Insight'],
            minLength: 1,
        }

        stripEnumMinLength(schema)

        expect(schema).not.toHaveProperty('minLength')
        expect(schema).toHaveProperty('enum')
        expect(schema).toHaveProperty('type')
    })

    it('preserves minLength on string schemas without enum', () => {
        const schema = {
            type: 'string',
            minLength: 1,
        }

        stripEnumMinLength(schema)

        expect(schema.minLength).toBe(1)
    })

    it('handles nested enum schemas in parameters', () => {
        const spec = {
            paths: {
                '/api/projects/{project_id}/activity_log/': {
                    get: {
                        parameters: [
                            {
                                in: 'query',
                                name: 'scope',
                                schema: {
                                    type: 'string',
                                    enum: ['Cohort', 'FeatureFlag'],
                                    minLength: 1,
                                },
                            },
                            {
                                in: 'query',
                                name: 'item_id',
                                schema: {
                                    type: 'string',
                                    minLength: 1,
                                },
                            },
                        ],
                    },
                },
            },
        }

        stripEnumMinLength(spec)

        const params = spec.paths['/api/projects/{project_id}/activity_log/'].get.parameters
        expect(params[0]!.schema).not.toHaveProperty('minLength')
        expect(params[0]!.schema.enum).toEqual(['Cohort', 'FeatureFlag'])
        expect(params[1]!.schema.minLength).toBe(1)
    })

    it('handles array items with enum and minLength', () => {
        const spec = {
            paths: {
                '/api/things/': {
                    get: {
                        parameters: [
                            {
                                in: 'query',
                                name: 'scopes',
                                schema: {
                                    type: 'array',
                                    items: {
                                        type: 'string',
                                        enum: ['Cohort', 'FeatureFlag'],
                                        minLength: 1,
                                    },
                                },
                            },
                        ],
                    },
                },
            },
        }

        stripEnumMinLength(spec)

        const items = spec.paths['/api/things/'].get.parameters[0]!.schema.items
        expect(items).not.toHaveProperty('minLength')
        expect(items.enum).toEqual(['Cohort', 'FeatureFlag'])
    })

    it('handles enum in component schemas', () => {
        const spec = {
            components: {
                schemas: {
                    ScopeEnum: {
                        type: 'string',
                        enum: ['A', 'B', 'C'],
                        minLength: 1,
                    },
                    RegularString: {
                        type: 'string',
                        minLength: 3,
                    },
                },
            },
        }

        stripEnumMinLength(spec)

        expect(spec.components.schemas.ScopeEnum).not.toHaveProperty('minLength')
        expect(spec.components.schemas.RegularString.minLength).toBe(3)
    })

    it('is a no-op for null and undefined', () => {
        expect(() => stripEnumMinLength(null)).not.toThrow()
        expect(() => stripEnumMinLength(undefined)).not.toThrow()
    })

    it('is a no-op for empty objects', () => {
        const obj = {}
        stripEnumMinLength(obj)
        expect(obj).toEqual({})
    })

    it('handles deeply nested structures', () => {
        const spec = {
            a: {
                b: {
                    c: {
                        type: 'string',
                        enum: ['X', 'Y'],
                        minLength: 1,
                    },
                },
            },
        }

        stripEnumMinLength(spec)

        expect(spec.a.b.c).not.toHaveProperty('minLength')
        expect(spec.a.b.c.enum).toEqual(['X', 'Y'])
    })
})

describe('stripUuidFormat', () => {
    it('strips format from a scalar string uuid field', () => {
        const schema = { type: 'string', format: 'uuid' }

        stripUuidFormat(schema)

        expect(schema).not.toHaveProperty('format')
        expect(schema.type).toBe('string')
    })

    it('strips format from a nullable uuid field with array-form type', () => {
        const schema = { type: ['string', 'null'], format: 'uuid' }

        stripUuidFormat(schema)

        expect(schema).not.toHaveProperty('format')
        expect(schema.type).toEqual(['string', 'null'])
    })

    it('leaves non-uuid formats untouched', () => {
        const schema = { type: 'string', format: 'date-time' }

        stripUuidFormat(schema)

        expect(schema.format).toBe('date-time')
    })

    it('strips uuid format from a nested nullable provider key field', () => {
        const spec = {
            components: {
                schemas: {
                    ModelConfiguration: {
                        type: 'object',
                        properties: {
                            provider_key_id: { type: ['string', 'null'], format: 'uuid' },
                        },
                    },
                },
            },
        }

        stripUuidFormat(spec)

        expect(spec.components.schemas.ModelConfiguration.properties.provider_key_id).not.toHaveProperty('format')
    })

    it('is a no-op for null and undefined', () => {
        expect(() => stripUuidFormat(null)).not.toThrow()
        expect(() => stripUuidFormat(undefined)).not.toThrow()
    })
})
