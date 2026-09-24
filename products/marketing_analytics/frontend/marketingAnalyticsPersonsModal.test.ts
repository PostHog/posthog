import {
    DataTableNode,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsTableQuery,
    NodeKind,
} from '~/queries/schema/schema-general'

import { marketingAnalyticsActorsQuery } from './marketingAnalyticsPersonsModal'

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

    it('keeps the source when a campaign name is shared by multiple integrations', () => {
        const actorsQuery = marketingAnalyticsActorsQuery({
            conversionGoalId: 'purchases',
            query: tableQuery(MarketingAnalyticsDrillDownLevel.Campaign),
            record: [
                { key: MarketingAnalyticsBaseColumns.Campaign, value: 'winter-sale' },
                { key: MarketingAnalyticsBaseColumns.Source, value: 'google' },
            ],
        })

        expect(actorsQuery?.source).toMatchObject({
            kind: NodeKind.MarketingAnalyticsActorsQuery,
            conversionGoalId: 'purchases',
            breakdown: { value: 'winter-sale', source: 'google' },
        })
    })

    it('uses the selected UTM dimension without adding a source filter', () => {
        const actorsQuery = marketingAnalyticsActorsQuery({
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
