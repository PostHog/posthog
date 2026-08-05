import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { formatInputValidationError } from '@/tools/exec'
import { GENERATED_TOOLS } from '@/tools/generated/product_analytics'

// Minimal valid input per tool: create requires `query`, update requires `id`.
const cases = [
    { tool: 'insight-create', base: { query: { source: { kind: 'TrendsQuery' } } } },
    { tool: 'insight-update', base: { id: 1 } },
]

// The Insight model caps `description` at 400 characters; these tests keep the
// advertised limit, the enforced limit, and the rejection message in lockstep.
describe('insight description 400-character limit', () => {
    it.each(cases)('$tool accepts a description of exactly 400 characters', ({ tool, base }) => {
        const schema = GENERATED_TOOLS[tool]!().schema

        expect(schema.safeParse({ ...base, description: 'a'.repeat(400) }).success).toBe(true)
    })

    it.each(cases)('$tool rejects a 401-character description, naming actual length and limit', ({ tool, base }) => {
        const { name, schema } = GENERATED_TOOLS[tool]!()
        const result = schema.safeParse({ ...base, description: 'a'.repeat(401) }, { reportInput: true })
        expect(result.success).toBe(false)

        const message = formatInputValidationError(name, result.error!)

        expect(message).toContain('parameter "description" is too long: 401 characters (max 400)')
    })

    it.each(cases)('$tool advertises the 400-character limit on the description param', ({ tool }) => {
        const inputSchema = z.toJSONSchema(GENERATED_TOOLS[tool]!().schema, { io: 'input' }) as {
            properties: Record<string, { description?: string }>
        }

        expect(inputSchema.properties['description']?.description).toMatch(/[Mm]ax 400 characters/)
    })
})
