import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/canvas'

// Agents compose canvas calls from scratch and guess the identifier key from
// context: production traces show `canvas-source-retrieve` receiving `canvas_id`
// / `canvasId` and `canvas-create` receiving `channel` where the schemas require
// `id` / `channel_id`. The mismatched key was the dominant validation failure for
// both tools. Every alias must normalize to the canonical param (canonical key
// wins on conflict, then the first-listed alias) or those failures come back.
describe('canvas id aliases', () => {
    describe('canvas-source-retrieve normalizes aliases to `id`', () => {
        const schema = GENERATED_TOOLS['canvas-source-retrieve']!().schema
        const ALIAS_KEYS = ['canvas_id', 'canvasId'] as const

        it.each([
            ['id', { id: 'cnv_123' }, 'cnv_123'],
            ['canvas_id', { canvas_id: 'cnv_123' }, 'cnv_123'],
            ['canvasId', { canvasId: 'cnv_123' }, 'cnv_123'],
            ['id over aliases on conflict', { id: 'keep', canvas_id: 'drop' }, 'keep'],
            ['first-listed alias on alias conflict', { canvas_id: 'first', canvasId: 'second' }, 'first'],
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
    })

    describe('canvas-create normalizes aliases to `channel_id`', () => {
        const schema = GENERATED_TOOLS['canvas-create']!().schema
        const ALIAS_KEYS = ['channel', 'channelId'] as const

        it.each([
            ['channel_id', { name: 'n', channel_id: 'ch_1' }, 'ch_1'],
            ['channel', { name: 'n', channel: 'ch_1' }, 'ch_1'],
            ['channelId', { name: 'n', channelId: 'ch_1' }, 'ch_1'],
            ['channel_id over aliases on conflict', { name: 'n', channel_id: 'keep', channel: 'drop' }, 'keep'],
            ['first-listed alias on alias conflict', { name: 'n', channel: 'first', channelId: 'second' }, 'first'],
        ])('accepts %s', (_label, input, expected) => {
            const result = schema.safeParse(input)
            expect(result.success).toBe(true)
            const data = result.data as Record<string, unknown>
            expect(data.channel_id).toEqual(expected)
            for (const alias of ALIAS_KEYS) {
                expect(data).not.toHaveProperty(alias)
            }
        })

        it('still rejects a call with no channel', () => {
            expect(schema.safeParse({ name: 'n' }).success).toBe(false)
        })
    })
})
