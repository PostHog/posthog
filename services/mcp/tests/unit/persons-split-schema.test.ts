import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/persons'

describe('persons-split schema', () => {
    const tool = GENERATED_TOOLS['persons-split']!()

    it('accepts a surgical split of named distinct IDs', () => {
        const result = tool.schema.safeParse({ id: '42', distinct_ids_to_split: ['device-a', 'device-b'] })

        expect(result.success).toBe(true)
    })

    it.each([
        ['no distinct IDs named', { id: '42' }],
        ['a null list', { id: '42', distinct_ids_to_split: null }],
        ['an empty list', { id: '42', distinct_ids_to_split: [] }],
        ['a main distinct ID instead', { id: '42', main_distinct_id: 'device-a' }],
    ])('rejects %s', (_case, params) => {
        const result = tool.schema.safeParse(params)

        expect(result.success).toBe(false)
    })
})
