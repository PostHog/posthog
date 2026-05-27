import { z } from 'zod'

import { zodToJsonSchema } from './zod-to-jsonschema'

describe('zodToJsonSchema', () => {
    it('converts a primitive string', () => {
        expect(zodToJsonSchema(z.string())).toEqual({ type: 'string' })
    })

    it('converts an object with required + optional fields', () => {
        const out = zodToJsonSchema(
            z.object({
                name: z.string(),
                age: z.number().optional(),
                role: z.string().default('user'),
            })
        )
        expect(out.type).toBe('object')
        expect(out.properties).toEqual({
            name: { type: 'string' },
            age: { type: 'number' },
            role: { type: 'string' },
        })
        expect(out.required).toEqual(['name'])
    })

    it('converts arrays of objects', () => {
        const out = zodToJsonSchema(z.array(z.object({ x: z.string() })))
        expect(out.type).toBe('array')
        expect((out.items as { type: string }).type).toBe('object')
    })

    it('converts records', () => {
        const out = zodToJsonSchema(z.record(z.string(), z.number()))
        expect(out.type).toBe('object')
        expect(out.additionalProperties).toEqual({ type: 'number' })
    })

    it('converts unions', () => {
        const out = zodToJsonSchema(z.union([z.string(), z.number()]))
        expect(out.oneOf).toEqual([{ type: 'string' }, { type: 'number' }])
    })

    it('preserves description', () => {
        const out = zodToJsonSchema(z.string().describe('user name'))
        expect(out.description).toBe('user name')
    })
})
