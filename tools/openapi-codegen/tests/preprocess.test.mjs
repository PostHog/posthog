import { describe, expect, it } from 'vitest'

import { clampIntegerBounds, INT32_MAX, INT32_MIN, preprocessSchema } from '../index.mjs'

describe('clampIntegerBounds', () => {
    it('clamps i64 bounds to int32 range on a type: integer schema', () => {
        const schema = {
            type: 'integer',
            // value as it lands after JSON.parse of 9223372036854775807
            maximum: 9223372036854776000,
            minimum: -9223372036854775808,
        }
        clampIntegerBounds(schema)
        expect(schema.maximum).toBe(INT32_MAX)
        expect(schema.minimum).toBe(INT32_MIN)
    })

    it('clamps exclusive bounds too', () => {
        const schema = {
            type: 'integer',
            exclusiveMaximum: 1e20,
            exclusiveMinimum: -1e20,
        }
        clampIntegerBounds(schema)
        expect(schema.exclusiveMaximum).toBe(INT32_MAX)
        expect(schema.exclusiveMinimum).toBe(INT32_MIN)
    })

    it('leaves in-range bounds untouched', () => {
        const schema = {
            type: 'integer',
            minimum: 0,
            maximum: 30000,
        }
        clampIntegerBounds(schema)
        expect(schema.minimum).toBe(0)
        expect(schema.maximum).toBe(30000)
    })

    it('ignores non-integer schemas', () => {
        const schema = {
            type: 'number',
            maximum: 1e20,
        }
        clampIntegerBounds(schema)
        expect(schema.maximum).toBe(1e20)
    })

    it('handles array-form type: ["integer", "null"]', () => {
        const schema = {
            type: ['integer', 'null'],
            maximum: 9223372036854776000,
        }
        clampIntegerBounds(schema)
        expect(schema.maximum).toBe(INT32_MAX)
    })

    it('recurses into nested properties', () => {
        const schema = {
            type: 'object',
            properties: {
                id: { type: 'integer', maximum: 9223372036854776000, minimum: -9223372036854775808 },
                name: { type: 'string' },
                nested: {
                    type: 'object',
                    properties: {
                        counter: { type: 'integer', maximum: 9223372036854776000 },
                    },
                },
            },
        }
        clampIntegerBounds(schema)
        expect(schema.properties.id.maximum).toBe(INT32_MAX)
        expect(schema.properties.id.minimum).toBe(INT32_MIN)
        expect(schema.properties.nested.properties.counter.maximum).toBe(INT32_MAX)
    })

    it('recurses through arrays', () => {
        const params = [
            { in: 'path', name: 'id', schema: { type: 'integer', maximum: 9223372036854776000 } },
            { in: 'query', name: 'limit', schema: { type: 'integer', maximum: 100 } },
        ]
        clampIntegerBounds(params)
        expect(params[0].schema.maximum).toBe(INT32_MAX)
        expect(params[1].schema.maximum).toBe(100)
    })

    it('is a no-op on null / undefined / primitives', () => {
        expect(() => clampIntegerBounds(null)).not.toThrow()
        expect(() => clampIntegerBounds(undefined)).not.toThrow()
        expect(() => clampIntegerBounds(42)).not.toThrow()
        expect(() => clampIntegerBounds('string')).not.toThrow()
    })
})

describe('preprocessSchema', () => {
    it('clamps integer bounds inside a full OpenAPI document', () => {
        const spec = {
            openapi: '3.1.0',
            info: { title: 'Test', version: '1.0.0' },
            paths: {
                '/api/projects/{id}/': {
                    get: {
                        operationId: 'projects_retrieve',
                        parameters: [
                            {
                                in: 'path',
                                name: 'id',
                                required: true,
                                schema: {
                                    type: 'integer',
                                    maximum: 9223372036854776000,
                                    minimum: -9223372036854775808,
                                },
                            },
                        ],
                        responses: { 200: { description: 'ok' } },
                    },
                },
            },
            components: { schemas: {} },
        }
        preprocessSchema(spec)
        const idSchema = spec.paths['/api/projects/{id}/'].get.parameters[0].schema
        expect(idSchema.maximum).toBe(INT32_MAX)
        expect(idSchema.minimum).toBe(INT32_MIN)
    })
})
