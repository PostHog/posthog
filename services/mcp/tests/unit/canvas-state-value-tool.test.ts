import { describe, expect, it } from 'vitest'

import { GENERATED_TOOL_MAP } from '@/tools/generated'

describe('canvas-state-value-retrieve tool', () => {
    const firstChunk = { id: 'canvas-1', scope: 'shared', key: 'notes' }

    it('rejects a continuation that omits the revision', () => {
        const result = GENERATED_TOOL_MAP['canvas-state-value-retrieve']!().schema.safeParse({
            ...firstChunk,
            offset: 12000,
        })

        expect(result.success).toBe(false)
        expect(result.error?.issues.map((issue) => issue.path)).toEqual([['revision']])
    })

    it.each([
        { label: 'the first chunk', input: firstChunk },
        { label: 'a continuation carrying the revision', input: { ...firstChunk, offset: 12000, revision: 'rev-1' } },
    ])('accepts $label', ({ input }) => {
        expect(GENERATED_TOOL_MAP['canvas-state-value-retrieve']!().schema.safeParse(input).success).toBe(true)
    })
})
