import { MarketingAnalyticsSearchRow } from '~/queries/schema/schema-general'

import { searchRecommendations } from './searchRecommendationRules'

const previous = { clicks: 200, impressions: 2000, cost: 100, conversions: 10, ctr: 0.1, cpc: 0.5, cpa: 10 }
const row: MarketingAnalyticsSearchRow = {
    ...previous,
    keyword: 'example keyword',
    platform: 'GoogleAds',
    matchType: 'exact',
    currency: 'USD',
    cost: 200,
    previous,
    posthogConversions: [
        { id: 'purchase', name: 'Purchases', conversions: 0, previousConversions: 5, costPerConversion: null },
    ],
}

describe('searchRecommendations', () => {
    it('uses one selected PostHog goal instead of platform conversions', () => {
        expect(searchRecommendations([row], 'purchase')).toEqual([
            { row, kind: 'spend_without_conversions', current: 0, previous: 5 },
        ])
        expect(searchRecommendations([row], null)).toEqual([{ row, kind: 'higher_cpa', current: 20, previous: 10 }])
        expect(searchRecommendations([row], 'missing')).toEqual([])
    })

    it.each([
        { previous: null },
        { currency: null },
        { cost: null },
        { cost: Number.NaN },
        { conversions: null },
        { conversions: 2 },
        { conversions: -1 },
        { previous: { ...previous, conversions: 0 } },
        { previous: { ...previous, cost: 0 } },
    ])('does not recommend paid changes with incomplete evidence: %j', (patch) => {
        expect(searchRecommendations([{ ...row, ...patch }], null)).toEqual([])
    })

    it('requires enough clicks before highlighting zero conversions', () => {
        expect(searchRecommendations([{ ...row, clicks: 99 }], 'purchase')).toEqual([])
    })

    it('uses raw organic clicks and impressions without assigning conversions to GSC queries', () => {
        const organic: MarketingAnalyticsSearchRow = {
            ...row,
            platform: 'GoogleSearchConsole',
            currency: null,
            cost: null,
            clicks: 20,
            impressions: 2000,
            ctr: 0.99,
        }
        expect(searchRecommendations([organic], 'missing')).toEqual([
            { row: organic, kind: 'lower_organic_ctr', current: 0.01, previous: 0.1 },
        ])
        expect(searchRecommendations([{ ...organic, impressions: 999 }], null)).toEqual([])
    })
})
