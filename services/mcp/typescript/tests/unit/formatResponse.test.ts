import { describe, expect, it } from 'vitest'

import { formatResponse } from '@/integrations/mcp/utils/formatResponse'

describe('formatResponse', () => {
    it('formats simple objects with toon', () => {
        const data = {
            id: 123,
            name: 'Test',
            active: true,
        }
        const result = formatResponse(data)
        expect(result).toContain('id: 123')
        expect(result).toContain('name: Test')
        expect(result).toContain('active: true')
    })

    it('formats nested query keys as JSON', () => {
        const data = {
            id: 123,
            name: 'Test',
            query: {
                kind: 'EventsQuery',
                select: ['*'],
                limit: 100,
            },
        }
        const result = formatResponse(data)
        expect(result).toContain('id: 123')
        expect(result).toContain('name: Test')
        expect(result).toContain('query:')

        const expectedJson = JSON.stringify(data.query, null, 2)
        expect(result).toContain(expectedJson)
    })

    it('formats deeply nested query keys as JSON', () => {
        const data = {
            insight: {
                id: 456,
                metadata: {
                    query: {
                        kind: 'TrendsQuery',
                        series: [{ event: 'pageview' }],
                    },
                },
            },
        }
        const result = formatResponse(data)
        expect(result).toContain('id: 456')
        expect(result).toContain('query:')

        const expectedJson = JSON.stringify(data.insight.metadata.query, null, 2)
        expect(result).toContain(expectedJson)
    })

    it('handles arrays', () => {
        const data = {
            flags: [
                { id: 1, key: 'flag-1' },
                { id: 2, key: 'flag-2' },
            ],
        }
        const result = formatResponse(data)
        expect(result).toContain('flag-1')
        expect(result).toContain('flag-2')
    })

    it('handles null and undefined values', () => {
        const data = {
            value: null,
            other: undefined,
            query: null,
        }
        const result = formatResponse(data)
        expect(result).toBeTruthy()
    })

    it('truncates responses exceeding max length', () => {
        // Create a large data object that will exceed 80k chars
        const largeArray = Array(10000)
            .fill(null)
            .map((_, i) => ({
                id: i,
                name: `Item ${i} with some extra text to make it longer`,
                description: 'A'.repeat(50),
            }))
        const data = { items: largeArray }

        const result = formatResponse(data)

        // Should be truncated to ~80k chars + truncation message
        expect(result.length).toBeLessThan(85000)
        expect(result).toContain('[Response truncated')
        expect(result).toContain('Use more specific filters or pagination')
    })

    it('does not truncate responses under max length', () => {
        const data = {
            id: 123,
            name: 'Test',
            items: Array(10)
                .fill(null)
                .map((_, i) => ({ id: i })),
        }
        const result = formatResponse(data)

        expect(result).not.toContain('[Response truncated')
    })
})
