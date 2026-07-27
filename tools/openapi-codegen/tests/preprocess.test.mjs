import { describe, expect, it } from 'vitest'

import {
    clampIntegerBounds,
    INT32_MAX,
    INT32_MIN,
    preprocessSchema,
    schemaAllowsNull,
    stripNullDefaults,
} from '../src/preprocess.mjs'

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

describe('schemaAllowsNull', () => {
    it.each([
        ['nullable: true', { nullable: true }],
        ['type: null', { type: 'null' }],
        ['type array with null', { type: ['string', 'null'] }],
        ['anyOf with null variant', { anyOf: [{ type: 'string' }, { type: 'null' }] }],
        ['oneOf with null variant', { oneOf: [{ type: 'integer' }, { type: 'null' }] }],
        ['nested anyOf with null', { anyOf: [{ anyOf: [{ type: 'null' }] }] }],
        ['untyped Any (bare object)', {}],
        ['untyped Any with title only', { title: 'Value' }],
    ])('returns true for %s', (_label, schema) => {
        expect(schemaAllowsNull(schema)).toBe(true)
    })

    it.each([
        ['plain string', { type: 'string' }],
        ['$ref', { $ref: '#/components/schemas/Foo' }],
        ['enum without null', { enum: ['a', 'b'] }],
        ['const', { const: 42 }],
        ['object with properties', { properties: { id: { type: 'integer' } } }],
        ['anyOf without null', { anyOf: [{ type: 'string' }, { type: 'integer' }] }],
        ['allOf with $ref', { allOf: [{ $ref: '#/components/schemas/Foo' }] }],
    ])('returns false for %s', (_label, schema) => {
        expect(schemaAllowsNull(schema)).toBe(false)
    })

    it('returns false for non-objects', () => {
        expect(schemaAllowsNull(null)).toBe(false)
        expect(schemaAllowsNull(undefined)).toBe(false)
        expect(schemaAllowsNull('string')).toBe(false)
        expect(schemaAllowsNull(42)).toBe(false)
    })
})

describe('stripNullDefaults', () => {
    it('drops default:null from a 3.1 anyOf-null property', () => {
        const schema = {
            anyOf: [{ type: 'string' }, { type: 'null' }],
            default: null,
            title: 'Label',
        }
        stripNullDefaults(schema)
        expect(schema).toEqual({
            anyOf: [{ type: 'string' }, { type: 'null' }],
            title: 'Label',
        })
    })

    it('drops default:null from a 3.0 nullable property', () => {
        const schema = { type: 'string', nullable: true, default: null }
        stripNullDefaults(schema)
        expect(schema).toEqual({ type: 'string', nullable: true })
    })

    it('drops default:null from an untyped Any property', () => {
        const schema = { default: null, title: 'Value' }
        stripNullDefaults(schema)
        expect(schema).toEqual({ title: 'Value' })
    })

    it('leaves default:null on a non-nullable typed property alone', () => {
        const schema = { type: 'string', default: null }
        stripNullDefaults(schema)
        expect(schema).toEqual({ type: 'string', default: null })
    })

    it('leaves non-null defaults alone', () => {
        const schema = { type: 'string', default: 'hello' }
        stripNullDefaults(schema)
        expect(schema).toEqual({ type: 'string', default: 'hello' })
    })

    it('recurses into nested properties', () => {
        const schema = {
            type: 'object',
            properties: {
                label: { anyOf: [{ type: 'string' }, { type: 'null' }], default: null },
                value: { default: null, title: 'Value' },
                name: { type: 'string' },
            },
        }
        stripNullDefaults(schema)
        expect(schema.properties.label).toEqual({ anyOf: [{ type: 'string' }, { type: 'null' }] })
        expect(schema.properties.value).toEqual({ title: 'Value' })
        expect(schema.properties.name).toEqual({ type: 'string' })
    })

    it('is a no-op on null / undefined / primitives', () => {
        expect(() => stripNullDefaults(null)).not.toThrow()
        expect(() => stripNullDefaults(undefined)).not.toThrow()
        expect(() => stripNullDefaults(42)).not.toThrow()
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
