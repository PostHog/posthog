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

    it('accepts HogQLQuery with tags for ClickHouse query tagging', () => {
        const result = QueryRunInputSchema.safeParse({
            query: {
                kind: 'HogQLQuery',
                query: 'SELECT 1',
                tags: { productKey: 'tracing', name: 'mcp_custom' },
            },
        })

        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.data.query.kind).toBe('HogQLQuery')
            if (result.data.query.kind === 'HogQLQuery') {
                expect(result.data.query.tags?.productKey).toBe('tracing')
                expect(result.data.query.tags?.name).toBe('mcp_custom')
            }
        }
    })
})
