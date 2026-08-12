import { describe, expect, it } from 'vitest'

import { InsightQueryInputSchema } from '@/schema/tool-inputs'
import { GENERATED_TOOLS } from '@/tools/generated/product_analytics'

// Agents interchange `id` / `insightId` / `insight_id` / `short_id` / `shortId`
// across the insight tools — production traces show the mismatched key as the
// dominant validation failure for all four. Every alias must normalize to each
// tool's canonical param (canonical key wins on conflict, then the first-listed
// alias) or those failures come back.
describe('insight id aliases', () => {
    const ALIAS_KEYS = ['insightId', 'insight_id', 'short_id', 'shortId'] as const

    describe.each([['insight-get'], ['insight-update'], ['insight-delete']])(
        '%s normalizes aliases to `id`',
        (toolName) => {
            const schema = GENERATED_TOOLS[toolName]!().schema

            it.each([
                ['id (numeric)', { id: 123 }, 123],
                ['id (short_id value)', { id: 'AaVQ8Ijw' }, 'AaVQ8Ijw'],
                ['insightId', { insightId: 123 }, 123],
                ['insight_id', { insight_id: 123 }, 123],
                ['short_id', { short_id: 'AaVQ8Ijw' }, 'AaVQ8Ijw'],
                ['shortId', { shortId: 'AaVQ8Ijw' }, 'AaVQ8Ijw'],
                ['id over aliases on conflict', { id: 1, insightId: 2, short_id: 'AaVQ8Ijw' }, 1],
                ['first-listed alias on alias conflict', { insight_id: 3, shortId: 'AaVQ8Ijw' }, 3],
            ])('accepts %s', (_label, input, expected) => {
                const result = schema.safeParse(input)
                expect(result.success).toBe(true)
                const data = result.data as Record<string, unknown>
                expect(data.id).toEqual(expected)
                for (const alias of ALIAS_KEYS) {
                    expect(data).not.toHaveProperty(alias)
                }
            })

            it('still rejects a call with no identifier', () => {
                expect(schema.safeParse({}).success).toBe(false)
            })
        }
    )

    describe('insight-query normalizes aliases to `insightId` and coerces numbers to string', () => {
        it.each([
            ['insightId (string)', { insightId: 'AaVQ8Ijw' }, 'AaVQ8Ijw'],
            ['insightId (numeric)', { insightId: 36 }, '36'],
            ['id (numeric)', { id: 36 }, '36'],
            ['id (string)', { id: '36' }, '36'],
            ['insight_id', { insight_id: 36 }, '36'],
            ['short_id', { short_id: 'AaVQ8Ijw' }, 'AaVQ8Ijw'],
            ['shortId', { shortId: 'AaVQ8Ijw' }, 'AaVQ8Ijw'],
            ['insightId over aliases on conflict', { insightId: 1, id: 2 }, '1'],
            ['first-listed alias on alias conflict', { id: 2, short_id: 'AaVQ8Ijw' }, '2'],
        ])('accepts %s', (_label, input, expected) => {
            const result = InsightQueryInputSchema.safeParse(input)
            expect(result.success).toBe(true)
            expect(result.data?.insightId).toBe(expected)
        })

        it('still rejects a call with no identifier', () => {
            expect(InsightQueryInputSchema.safeParse({}).success).toBe(false)
        })
    })
})
