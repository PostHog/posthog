import { describe, expect, it } from 'vitest'

import { generateZodFromSchemaRef } from '../../scripts/lib/json-schema-to-zod'

describe('generateZodFromSchemaRef — array constraints', () => {
    it('propagates minItems to .min() on the generated Zod array', () => {
        const root = {
            definitions: {
                Group: {
                    type: 'object',
                    properties: {
                        nodes: {
                            type: 'array',
                            items: { type: 'string' },
                            minItems: 2,
                        },
                    },
                    required: ['nodes'],
                },
            },
        }

        const out = generateZodFromSchemaRef(root, 'Group')

        expect(out).toContain('z.array(z.string()).min(2)')
    })

    it('propagates maxItems to .max() on the generated Zod array', () => {
        const root = {
            definitions: {
                Capped: {
                    type: 'object',
                    properties: {
                        items: {
                            type: 'array',
                            items: { type: 'string' },
                            maxItems: 5,
                        },
                    },
                },
            },
        }

        const out = generateZodFromSchemaRef(root, 'Capped')

        expect(out).toContain('z.array(z.string()).max(5)')
    })

    it('propagates both minItems and maxItems together', () => {
        const root = {
            definitions: {
                Bounded: {
                    type: 'object',
                    properties: {
                        items: {
                            type: 'array',
                            items: { type: 'string' },
                            minItems: 1,
                            maxItems: 3,
                        },
                    },
                },
            },
        }

        const out = generateZodFromSchemaRef(root, 'Bounded')

        expect(out).toContain('z.array(z.string()).min(1).max(3)')
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
