import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { MarketingAnalyticsOverview } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsOverview/MarketingAnalyticsOverview'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { marketingAnalyticsTilesLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { InsightVizNode, MarketingAnalyticsAggregatedQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

const response: MarketingAnalyticsAggregatedQueryResponse = {
    results: {
        Cost: { key: 'Cost', value: 100, kind: 'currency' },
        Clicks: { key: 'Clicks', value: 50, kind: 'unit' },
        CPC: { key: 'CPC', value: 2, kind: 'currency' },
        CTR: { key: 'CTR', value: 5, kind: 'percentage' },
        'Trial started': { key: 'Trial started', value: 10, kind: 'unit' },
    },
}

describe('Ad performance metric selection', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it.each([
        ['Clicks', 'clicks'],
        ['CPC', 'cpc'],
        ['CTR', 'ctr'],
    ])('selecting %s updates the existing trend without changing the filters', async (label, metric) => {
        render(
            <MarketingAnalyticsOverview
                query={{ kind: NodeKind.MarketingAnalyticsAggregatedQuery, properties: [] }}
                cachedResults={response}
                context={{}}
                uniqueKey="metric-selection"
            />
        )
        const before = (marketingAnalyticsTilesLogic.values.marketingChartTile.query as InsightVizNode).source
        const button = (await screen.findByText(label)).closest('button')!
        fireEvent.click(button)
        expect(marketingAnalyticsLogic.values.tileColumnSelection).toBe(metric)
        expect(button.getAttribute('aria-pressed')).toBe('true')
        expect(marketingAnalyticsTilesLogic.values.marketingChartTile.title).toBe(`Marketing ${metric}`)
        expect(
            (marketingAnalyticsTilesLogic.values.marketingChartTile.query as InsightVizNode).source.dateRange
        ).toEqual(before.dateRange)
        expect(screen.getByText('Trial Started').closest('button')).toBeNull()
    })
})
