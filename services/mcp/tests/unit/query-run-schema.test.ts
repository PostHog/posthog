import { describe, expect, it } from 'vitest'

import { QueryRunInputSchema } from '@/schema/tool-inputs'

describe('QueryRunInputSchema', () => {
    it('accepts a bare HogQLQuery node', () => {
        const result = QueryRunInputSchema.safeParse({
            query: {
                kind: 'HogQLQuery',
                query: 'SELECT count() AS total FROM system.insight_variables',
            },
        })

        expect(result.success).toBe(true)
    })
})
