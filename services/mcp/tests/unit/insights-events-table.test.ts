import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/product_analytics'

describe('saving events tables', () => {
    const source = {
        kind: 'EventsQuery',
        select: ['event', 'timestamp', 'properties.example_property'],
        where: ['timestamp >= now() - interval 7 day'],
        properties: [{ type: 'event', key: 'example_property', operator: 'exact', value: ['example'] }],
        fixedProperties: [
            { type: 'event', key: 'example_scope', operator: 'exact', value: ['visible'] },
            {
                type: 'AND',
                values: [
                    {
                        type: 'OR',
                        values: [{ type: 'event', key: 'example_group', operator: 'exact', value: ['visible'] }],
                    },
                ],
            },
        ],
        events: ['example_event', 'another_event'],
        filterTestAccounts: false,
        after: '2026-01-01T00:00:00Z',
        before: '2026-01-08T00:00:00Z',
        orderBy: ['timestamp DESC'],
        limit: 25,
        offset: 10,
    }
    const table = {
        kind: 'DataTableNode',
        source,
        columns: source.select,
        pinnedColumns: ['event'],
        hiddenColumns: ['timestamp'],
        showAbsoluteTime: true,
        showPropertyFilter: true,
        showDateRange: true,
        expandable: false,
    }

    describe.each(['insight-create', 'insight-update'])('%s', (toolName) => {
        const schema = GENERATED_TOOLS[toolName]!().schema
        const params = toolName === 'insight-create' ? { name: 'Example events' } : { id: 'AaVQ8Ijw' }

        it.each([
            ['bare', source],
            ['wrapped', table],
        ])('preserves filters, columns and settings for a %s events query', (_name, query) => {
            const parsed = schema.parse({ ...params, query }) as Record<string, unknown>

            expect(parsed.query).toEqual(query)
        })

        it.each([
            ['other table source', { kind: 'DataTableNode', source: { kind: 'HogQLQuery', query: 'select 1' } }],
            ['missing select', { kind: 'DataTableNode', source: { kind: 'EventsQuery' } }],
            ['invalid select', { kind: 'EventsQuery', select: 'event' }],
        ])('rejects %s', (_name, query) => {
            expect(schema.safeParse({ ...params, query }).success).toBe(false)
        })
    })
})
