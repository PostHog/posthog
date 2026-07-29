import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { generateZodFromSchemaRef } from '../../scripts/lib/json-schema-to-zod'

/** Evaluate generated Zod source so assertions run against real parse behavior. */
function buildSchema(root: Parameters<typeof generateZodFromSchemaRef>[0], entry: string): z.ZodTypeAny {
    const src = generateZodFromSchemaRef(root, entry)
    return new Function('z', `${src}; return ${entry}`)(z) as z.ZodTypeAny
}

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

describe('generateZodFromSchemaRef — union branch ordering', () => {
    // Shape of PropertyFilterValue: a coercing scalar branch authored alongside array
    // and null branches, which it would otherwise swallow.
    const propertyFilterRoot = {
        definitions: {
            Filter: {
                type: 'object',
                properties: {
                    value: {
                        anyOf: [
                            { type: ['string', 'number', 'boolean'] },
                            { type: 'array', items: { type: ['string', 'number', 'boolean'] } },
                            { type: 'null' },
                        ],
                    },
                },
            },
        },
    }

    it.each([
        { label: 'string array', value: ['Mobile'] },
        { label: 'multi-element string array', value: ['Mobile', 'Desktop'] },
        { label: 'empty array', value: [] },
        { label: 'number array', value: [2500, 4000] },
        { label: 'null', value: null },
        { label: 'bare string', value: 'Mobile' },
        { label: 'bare boolean', value: true },
        { label: 'bare number', value: 42 },
    ])('preserves $label instead of collapsing it into a coerced scalar', ({ value }) => {
        const Filter = buildSchema(propertyFilterRoot, 'Filter')

        expect(Filter.parse({ value })).toEqual({ value })
    })

    it('keeps a variant name as a string when the union also accepts a boolean', () => {
        const FlagValue = buildSchema(
            {
                definitions: {
                    FlagValue: {
                        type: 'object',
                        properties: { value: { type: ['boolean', 'string'] } },
                    },
                },
            },
            'FlagValue'
        )

        expect(FlagValue.parse({ value: 'control' })).toEqual({ value: 'control' })
        expect(FlagValue.parse({ value: true })).toEqual({ value: true })
    })

    it('keeps null distinct from zero on a nullable integer', () => {
        const Grouped = buildSchema(
            {
                definitions: {
                    Grouped: {
                        type: 'object',
                        properties: { group_type_index: { anyOf: [{ type: 'integer' }, { type: 'null' }] } },
                    },
                },
            },
            'Grouped'
        )

        expect(Grouped.parse({ group_type_index: null })).toEqual({ group_type_index: null })
        expect(Grouped.parse({ group_type_index: 0 })).toEqual({ group_type_index: 0 })
    })

    it('still coerces numeric strings for MCP clients that send numbers as strings', () => {
        const Grouped = buildSchema(
            {
                definitions: {
                    Grouped: {
                        type: 'object',
                        properties: { group_type_index: { anyOf: [{ type: 'integer' }, { type: 'null' }] } },
                    },
                },
            },
            'Grouped'
        )

        expect(Grouped.parse({ group_type_index: '3' })).toEqual({ group_type_index: 3 })
    })
})
