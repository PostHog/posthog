import { describe, expect, it } from 'vitest'
import { z } from 'zod'

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

    it('keeps coercion on lone number fields but never coerces booleans', () => {
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
        expect(out).toContain('flag: z.boolean()')
        expect(out).not.toContain('z.coerce.boolean()')
    })
})

describe('generateZodFromSchemaRef — parsed values', () => {
    // Runs the emitted source with zod, so these check what a caller actually gets back.
    function build(definitions: Record<string, unknown>): z.ZodTypeAny {
        const code = generateZodFromSchemaRef(
            { definitions } as Parameters<typeof generateZodFromSchemaRef>[0],
            'Subject'
        )
        return new Function('z', `${code}\nreturn Subject`)(z) as z.ZodTypeAny
    }

    const subject = build({
        integer: { type: 'integer' },
        Subject: {
            type: 'object',
            properties: {
                flag: { type: 'boolean' },
                count: { type: 'number' },
                group: { anyOf: [{ $ref: '#/definitions/integer' }, { type: 'null' }] },
            },
        },
    })

    // Boolean("false") is true, so a coercing boolean flips a caller's string "false".
    // The shared `integer` const coerces for lone fields, so reusing it inside a union
    // turns null into 0, which is a real group type index.
    it.each([
        { label: 'boolean false', input: { flag: false }, expected: { flag: false } },
        { label: 'boolean true', input: { flag: true }, expected: { flag: true } },
        { label: 'numeric string for a lone number', input: { count: '5' }, expected: { count: 5 } },
        { label: 'null for an integer-or-null ref', input: { group: null }, expected: { group: null } },
        { label: 'integer for an integer-or-null ref', input: { group: 1 }, expected: { group: 1 } },
    ])('keeps $label', ({ input, expected }) => {
        expect(subject.parse(input)).toEqual(expected)
    })

    it.each([
        { label: 'the string "false" for a boolean', input: { flag: 'false' } },
        { label: 'an empty string for an integer-or-null ref', input: { group: '' } },
    ])('rejects $label', ({ input }) => {
        expect(subject.safeParse(input).success).toBe(false)
    })
})
