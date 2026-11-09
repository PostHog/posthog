import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import {
    RecommendationsLoadStatus,
    groupRecommendations,
    recommendationKey,
    recommendationsShownState,
    withoutDismissed,
} from './recommendations'

function recommendation(overrides: Partial<MarketingAnalyticsRecommendation>): MarketingAnalyticsRecommendation {
    return {
        rule: 'spend_without_conversions',
        level: 'search_term',
        subject: 'term',
        action: 'Add it as a negative',
        reason: 'No conversions',
        impact: 100,
        impactDirection: 'save',
        impactType: 'measured',
        currency: 'USD',
        ...overrides,
    }
}

describe('recommendations', () => {
    describe('groupRecommendations', () => {
        it('puts groups that only say keep last and sums impact per currency', () => {
            const groups = groupRecommendations([
                recommendation({ rule: 'brand_overlap', impactDirection: 'keep', impact: 5000 }),
                recommendation({ subject: 'a', impact: 100, currency: 'USD' }),
                recommendation({ subject: 'b', impact: 50, currency: 'USD' }),
                recommendation({ subject: 'c', impact: 90000, currency: 'EUR' }),
            ])

            expect(groups.map((group) => [group.rule, group.totals])).toEqual([
                [
                    'spend_without_conversions',
                    [
                        { direction: 'save', currency: 'USD', amount: 150 },
                        { direction: 'save', currency: 'EUR', amount: 90000 },
                    ],
                ],
                ['brand_overlap', [{ direction: 'keep', currency: 'USD', amount: 5000 }]],
            ])
        })
    })

    describe('withoutDismissed', () => {
        it('hides a dismissal stored with an empty campaign for a recommendation without one', () => {
            const rows = [
                recommendation({ rule: 'review_campaign', level: 'campaign', subject: 'Campaign A', campaign: null }),
                recommendation({ subject: 'example shoes', campaign: 'Campaign A' }),
                recommendation({ subject: 'example shoes', campaign: 'Campaign B' }),
            ]
            const dismissed = new Set([
                recommendationKey({ rule: 'review_campaign', subject: 'Campaign A', campaign: '' }),
                recommendationKey({
                    rule: 'spend_without_conversions',
                    subject: 'example shoes',
                    campaign: 'Campaign A',
                }),
            ])

            expect(withoutDismissed(rows, dismissed).map((row) => [row.subject, row.campaign])).toEqual([
                ['example shoes', 'Campaign B'],
            ])
        })
    })

    describe('recommendationsShownState', () => {
        const loaded: RecommendationsLoadStatus = {
            sourcesLoading: false,
            dismissalsPending: false,
            responseLoading: false,
            responseError: false,
            connectedSourceCount: 1,
            selectedSourceCount: 1,
            hasRecommendations: true,
        }

        it.each([
            ['dismissals still loading', { dismissalsPending: true }, null],
            ['first response still loading', { responseLoading: true, hasRecommendations: false }, null],
            ['reload over earlier results', { responseLoading: true }, 'recommendations'],
            ['failed load over earlier results', { responseError: true }, 'error'],
            ['no results', { hasRecommendations: false }, 'empty'],
            ['nothing connected', { connectedSourceCount: 0, selectedSourceCount: 0 }, 'no_connected_source'],
        ] as const)('%s', (_, overrides, expected) => {
            expect(recommendationsShownState({ ...loaded, ...overrides })).toEqual(expected)
        })
    })
})
