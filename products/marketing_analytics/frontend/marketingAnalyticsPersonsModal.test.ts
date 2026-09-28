import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import {
    DataTableNode,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsTableQuery,
    NodeKind,
} from '~/queries/schema/schema-general'

import { marketingAnalyticsActorsQuery, openMarketingAnalyticsPersonsModal } from './marketingAnalyticsPersonsModal'

jest.mock('scenes/trends/persons-modal/PersonsModal', () => ({ openPersonsModal: jest.fn() }))

describe('marketingAnalyticsActorsQuery', () => {
    const tableQuery = (drillDownLevel: MarketingAnalyticsDrillDownLevel): DataTableNode => ({
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.MarketingAnalyticsTableQuery,
            dateRange: { date_from: '2026-01-01', date_to: '2026-01-31' },
            drillDownLevel,
            properties: [],
        } satisfies MarketingAnalyticsTableQuery,
    })

    it.each([
        [false, '10042'],
        [true, '10042'],
        [true, undefined],
        [true, null],
    ] as const)('only builds a scoped campaign query with the flag (%s) and match key (%s)', (enabled, matchKey) => {
        const actorsQuery = marketingAnalyticsActorsQuery({
            enabled,
            conversionGoalId: 'purchases',
            query: tableQuery(MarketingAnalyticsDrillDownLevel.Campaign),
            record: [
                { key: MarketingAnalyticsBaseColumns.Campaign, value: 'winter-sale', conversionMatchKey: matchKey },
                { key: MarketingAnalyticsBaseColumns.Source, value: 'google' },
            ],
        })

        if (!enabled || matchKey == null) {
            expect(actorsQuery).toBeNull()
            return
        }

        expect(actorsQuery?.source).toMatchObject({
            kind: NodeKind.MarketingAnalyticsActorsQuery,
            conversionGoalId: 'purchases',
            breakdown: { value: 'winter-sale', source: 'google', matchKey: '10042' },
        })
        expect(actorsQuery?.orderBy).toEqual(['id'])
        expect(actorsQuery).not.toBeNull()
        openMarketingAnalyticsPersonsModal({ conversionGoalName: 'Purchases', actorsQuery: actorsQuery! })
        expect(openPersonsModal).toHaveBeenCalledWith({
            title: 'Purchases: people attributed to winter-sale',
            actorsQuery,
        })
    })

    it.each([
        [MarketingAnalyticsDrillDownLevel.Campaign, MarketingAnalyticsBaseColumns.Campaign],
        [MarketingAnalyticsDrillDownLevel.ChannelSource, 'Channel'],
    ])('does not broaden %s drill-downs when Source is hidden', (level, column) => {
        expect(
            marketingAnalyticsActorsQuery({
                enabled: true,
                conversionGoalId: 'purchases',
                query: tableQuery(level),
                record: [{ key: column, value: 'winter-sale' }],
            })
        ).toBeNull()
    })

    it('uses the selected UTM dimension without adding a source filter', () => {
        const actorsQuery = marketingAnalyticsActorsQuery({
            enabled: true,
            conversionGoalId: 'signups',
            query: tableQuery(MarketingAnalyticsDrillDownLevel.Medium),
            record: [
                { key: 'Medium', value: 'paid-social' },
                { key: MarketingAnalyticsBaseColumns.Source, value: 'facebook' },
            ],
        })

        expect(actorsQuery?.source.breakdown).toEqual({ value: 'paid-social', source: undefined })
    })
})
