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
