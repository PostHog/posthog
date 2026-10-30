import { describe, expect, it } from 'vitest'

import { formatResponse } from '@/lib/response'

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

    it.each([
        ["$'", "SELECT count() FROM events WHERE match(properties.$pathname, '^/pricing$')"],
        ['$&', "SELECT '$&' AS token"],
        ['$`', 'SELECT 1 AS `$`col`'],
        ['$$', "SELECT '$$' AS cost"],
    ])('keeps %s in a query literal', (_sequence, sql) => {
        const data = {
            charts: [
                { name: 'first', query: { kind: 'HogQLQuery', query: sql } },
                {
                    name: 'second',
                    query: { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: sql } },
                },
            ],
            metrics: 'trailing-metrics-field',
            prompts: 'trailing-prompts-field',
        }
        const result = formatResponse(data)

        expect(result).toContain(JSON.stringify(data.charts[0]!.query, null, 2))
        expect(result).toContain(JSON.stringify(data.charts[1]!.query, null, 2))
        expect(result.split('trailing-metrics-field')).toHaveLength(2)
        expect(result.split('trailing-prompts-field')).toHaveLength(2)
        expect(result).not.toContain('__QUERY_PLACEHOLDER_')
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

    it('returns string input verbatim (no TOON, no character expansion)', () => {
        // Regression: previously a string handler result was object-rest-destructured
        // in the MCP wrapper, turning 'foo' into {'0':'f','1':'o','2':'o'} before
        // hitting formatResponse. formatResponse itself must pass strings through
        // unchanged so the wrapper's pass-through is correct.
        const jsonPayload = '{"name":"query-trends","title":"Run a trends query"}'
        const result = formatResponse(jsonPayload)

        expect(result).toBe(jsonPayload)
        // The character-indexed regression signature must never appear.
        expect(result).not.toMatch(/"0":\s*"\{"/)
        expect(result).not.toMatch(/"1":\s*"\\"/)
    })

    it('does NOT truncate even for very large responses (MCP must return full data)', () => {
        // IMPORTANT: truncation was removed because the MCP must never silently
        // drop data — downstream clients are responsible for any size handling.
        // This test exists to catch anyone re-introducing truncation.
        const hugeValue = 'X'.repeat(500_000)
        const data = { payload: hugeValue }

        const result = formatResponse(data)

        expect(result.length).toBeGreaterThan(500_000)
        expect(result).toContain(hugeValue)
        expect(result).not.toContain('[Response truncated')
        expect(result).not.toContain('Response truncated')
        expect(result).not.toContain('exceeded maximum length')
    })

    it('does NOT truncate large string inputs either', () => {
        const hugeString = 'Y'.repeat(500_000)
        const result = formatResponse(hugeString)

        expect(result).toBe(hugeString)
        expect(result.length).toBe(500_000)
        expect(result).not.toContain('[Response truncated')
    })
})
