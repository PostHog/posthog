import { describe, expect, it } from 'vitest'

import { generateZodFromSchemaRef } from '../../scripts/lib/json-schema-to-zod'

describe('generateZodFromSchemaRef — array constraints', () => {
    it.each([
        { label: 'minItems only', constraints: { minItems: 2 }, expected: 'z.array(z.string()).min(2)' },
        { label: 'maxItems only', constraints: { maxItems: 5 }, expected: 'z.array(z.string()).max(5)' },
        {
            label: 'minItems and maxItems together',
            constraints: { minItems: 1, maxItems: 3 },
            expected: 'z.array(z.string()).min(1).max(3)',
        },
    ])('propagates $label to the generated Zod array', ({ constraints, expected }) => {
        const root = {
            definitions: {
                Subject: {
                    type: 'object',
                    properties: {
                        items: {
                            type: 'array',
                            items: { type: 'string' },
                            ...constraints,
                        },
                    },
                },
            },
        }

        const out = generateZodFromSchemaRef(root, 'Subject')

        expect(out).toContain(expected)
    })

    it('emits a bare z.array() when no array constraints are present', () => {
        const root = {
            definitions: {
                Plain: {
                    type: 'object',
                    properties: {
                        items: { type: 'array', items: { type: 'string' } },
                    },
                },
            },
        }

        const out = generateZodFromSchemaRef(root, 'Plain')

        expect(out).toContain('z.array(z.string())')
        expect(out).not.toMatch(/\.min\(/)
        expect(out).not.toMatch(/\.max\(/)
    })
})

describe('generateZodFromSchemaRef — union primitive strictness', () => {
    // Coercing branches inside a union are greedy (z.coerce.boolean() accepts any
    // input, z.coerce.number() turns null into 0), which made later array/null
    // branches unreachable: a `["host.com"]` property-filter value parsed as `true`
    // and a feature-flag variant string parsed as `true`. Union members must be strict.
    it.each([
        {
            label: 'anyOf of primitives',
            schema: {
                anyOf: [{ type: 'string' }, { type: 'number' }, { type: 'boolean' }],
            },
            expected: 'z.union([z.string(), z.number(), z.boolean()])',
        },
        {
            label: 'anyOf with array and null branches',
            schema: {
                anyOf: [
                    { anyOf: [{ type: 'string' }, { type: 'number' }] },
                    { type: 'array', items: { type: 'string' } },
                    { type: 'null' },
                ],
            },
            expected: 'z.union([z.union([z.string(), z.number()]), z.array(z.string()), z.null()])',
        },
        {
            label: 'multi-type array',
            schema: { type: ['string', 'boolean'] },
            expected: 'z.union([z.string(), z.boolean()])',
        },
    ])('emits strict primitives for $label', ({ schema, expected }) => {
        const root = { definitions: { Subject: { type: 'object', properties: { value: schema } } } }

        const out = generateZodFromSchemaRef(root, 'Subject')

        expect(out).toContain(expected)
        expect(out).not.toContain('z.coerce')
    })

    it('keeps coercion on lone primitive fields', () => {
        const root = {
            definitions: {
                Subject: {
                    type: 'object',
                    properties: { count: { type: 'number' }, flag: { type: 'boolean' } },
                },
            },
        }

        const out = generateZodFromSchemaRef(root, 'Subject')

        expect(out).toContain('z.coerce.number()')
        expect(out).toContain('z.coerce.boolean()')
    })
})
