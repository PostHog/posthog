import {
    DataTableNode,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsTableQuery,
    NodeKind,
} from '~/queries/schema/schema-general'

import {
    conversionRecordingsRequest,
    conversionRecordingsTableQuery,
    restoreConversionRecordingsColumns,
} from './conversionRecordingsRequest'

describe('conversion recordings row selection', () => {
    const source: MarketingAnalyticsTableQuery = {
        kind: NodeKind.MarketingAnalyticsTableQuery,
        properties: [],
        select: ['Purchases'],
    }
    const query: DataTableNode = { kind: NodeKind.DataTableNode, source }

    it.each([
        [MarketingAnalyticsDrillDownLevel.Campaign, ['Campaign', 'Source', 'ID']],
        [MarketingAnalyticsDrillDownLevel.ChannelSource, ['Channel', 'Source']],
        [MarketingAnalyticsDrillDownLevel.Source, ['Source']],
        [MarketingAnalyticsDrillDownLevel.Medium, ['Medium']],
    ])('keeps hidden row keys available at %s level without saving them', (level, columns) => {
        const original: DataTableNode = {
            ...query,
            source: { ...source, drillDownLevel: level },
            hiddenColumns: ['Cost'],
        }
        const prepared = conversionRecordingsTableQuery(original, true)
        expect((prepared.source as MarketingAnalyticsTableQuery).select).toEqual(['Purchases', ...columns])
        expect(prepared.hiddenColumns).toEqual(['Cost', ...columns])

        const record = columns.map((key) => ({ key, value: `${key} value` }))
        const request = conversionRecordingsRequest(prepared.source as MarketingAnalyticsTableQuery, record, 'purchase')
        expect(request).toMatchObject({ goal_id: 'purchase', group: `${columns[0]} value` })
        if (columns.includes('ID')) {
            expect(request).toMatchObject({ campaign_id: 'ID value', source_name: 'Source value' })
        }

        const sorted: DataTableNode = {
            ...prepared,
            source: { ...(prepared.source as MarketingAnalyticsTableQuery), orderBy: [['Purchases', 'DESC']] },
        }
        expect(restoreConversionRecordingsColumns(sorted, original)).toEqual({
            ...original,
            source: { ...original.source, orderBy: [['Purchases', 'DESC']] },
        })
    })

    it.each([
        [false, 'campaign-id', 'campaign-id'],
        [false, null, '-'],
        [false, '', '-'],
        [true, 'campaign-id', undefined],
        [true, null, undefined],
    ])('selects the campaign ID %s/%s without splitting comparison rows', (compare, id, expected) => {
        const prepared = conversionRecordingsTableQuery(
            { ...query, source: { ...source, compareFilter: { compare } } },
            true
        )
        expect((prepared.source as MarketingAnalyticsTableQuery).select).toEqual([
            'Purchases',
            'Campaign',
            'Source',
            ...(compare ? [] : ['ID']),
        ])
        expect(
            conversionRecordingsRequest(
                prepared.source as MarketingAnalyticsTableQuery,
                [
                    { key: 'Campaign', value: 'winter-sale' },
                    { key: 'Source', value: 'google' },
                    { key: 'ID', value: id },
                ],
                'purchase'
            )?.campaign_id
        ).toBe(expected)
    })

    it.each([false, true])('leaves complete queries unchanged (enabled: %s)', (enabled) => {
        const complete: DataTableNode = {
            ...query,
            source: { ...source, select: ['Campaign', 'Source', 'ID', 'Purchases'] },
        }
        expect(conversionRecordingsTableQuery(complete, enabled)).toBe(complete)
        if (!enabled) {
            expect(conversionRecordingsTableQuery(query, enabled)).toBe(query)
        }
    })
})
