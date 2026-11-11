import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { kpiTileUrls, retryFailedSources } from './KpiTiles'

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
        expect(tileUrls.erroredSessions).toBe(
            combineUrl(urls.mcpAnalyticsSessions(), { ...searchParams, has_errors: 'true' }).url
        )
        expect(tileUrls.toolQuality).toBe(combineUrl(urls.mcpAnalyticsToolQuality(), searchParams).url)
        expect(tileUrls.intentClustering).toBe(combineUrl(urls.mcpAnalyticsIntentClustering(), searchParams).url)
    })

    it.each([
        { kpisFailed: true, usersFailed: false, expected: ['kpis'] },
        { kpisFailed: false, usersFailed: true, expected: ['users'] },
        { kpisFailed: true, usersFailed: true, expected: ['kpis', 'users'] },
    ])(
        'retries only the failed queries behind a combined tile: kpis $kpisFailed, users $usersFailed',
        ({ kpisFailed, usersFailed, expected }) => {
            const retried: string[] = []
            retryFailedSources([
                { failed: kpisFailed, retry: () => retried.push('kpis') },
                { failed: usersFailed, retry: () => retried.push('users') },
            ])
            expect(retried).toEqual(expected)
        }
    )
})
