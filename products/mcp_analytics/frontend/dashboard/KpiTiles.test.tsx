import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { kpiTileUrls } from './KpiTiles'

const EVENT_FILTER: AnyPropertyFilter = {
    key: '$mcp_tool_name',
    value: ['create_insight'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

describe('KpiTiles', () => {
    it('keeps dashboard filters in Sessions and Tool quality links', () => {
        const searchParams = {
            date_from: '-7d',
            properties: [EVENT_FILTER],
            filter_test_accounts: false,
        }
        const tileUrls = kpiTileUrls({ ...searchParams, landing: 'old', search: 'old' })

        expect(tileUrls.sessions).toBe(combineUrl(urls.mcpAnalyticsSessions(), searchParams).url)
        expect(tileUrls.toolQuality).toBe(combineUrl(urls.mcpAnalyticsToolQuality(), searchParams).url)
        expect(tileUrls.intentClustering).toBe(combineUrl(urls.mcpAnalyticsIntentClustering(), searchParams).url)
    })
})
