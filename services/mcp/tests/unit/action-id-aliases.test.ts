import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/actions'

// Agents interchange `id` / `actionId` / `action_id` across the action tools —
// production traces show the mismatched key as the dominant validation failure
// for action-get, action-update, and action-delete. Every alias must normalize
// to `id` (canonical key wins on conflict, then the first-listed alias) or those
// failures come back.
describe('action id aliases', () => {
    const ALIAS_KEYS = ['actionId', 'action_id'] as const

    describe.each([['action-get'], ['action-update'], ['action-delete']])(
        '%s normalizes aliases to `id`',
        (toolName) => {
            const schema = GENERATED_TOOLS[toolName]!().schema

            it.each([
                ['id (numeric)', { id: 123 }, 123],
                ['id (stringified integer)', { id: '123' }, 123],
                ['actionId (numeric)', { actionId: 123 }, 123],
                ['actionId (stringified integer)', { actionId: '123' }, 123],
                ['action_id (numeric)', { action_id: 123 }, 123],
                ['id over aliases on conflict', { id: 1, actionId: 2 }, 1],
                ['first-listed alias on alias conflict', { actionId: 3, action_id: 4 }, 3],
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
})
