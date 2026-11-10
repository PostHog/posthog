import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import {
    RecommendationsLoadStatus,
    groupRecommendations,
    recommendationKey,
    recommendationsShownState,
    unresolved,
    withResolutionOverrides,
} from './recommendations'

function recommendation(overrides: Partial<MarketingAnalyticsRecommendation>): MarketingAnalyticsRecommendation {
    return {
        rule: 'spend_without_conversions',
        level: 'search_term',
        subject: 'term',
        identity: {
            rule: 'spend_without_conversions',
            source_type: 'google_ads',
            customer_id: '111',
            campaign_id: '',
            subject: 'term',
        },
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

    describe('withResolutionOverrides', () => {
        it('applies resolutions made in this session to the matching identity only', () => {
            const identity = recommendation({}).identity
            const dismissed = { id: 'r1', state: 'dismissed' as const, resolvedAt: '2026-11-01T00:00:00Z' }
            const rows = [
                recommendation({ identity: { ...identity, customer_id: '111' } }),
                recommendation({ identity: { ...identity, customer_id: '222' }, resolution: dismissed }),
                recommendation({ identity: { ...identity, customer_id: '333' }, resolution: dismissed }),
            ]

            const shown = withResolutionOverrides(rows, {
                [recommendationKey(rows[0])]: { ...dismissed, state: 'applied' },
                [recommendationKey(rows[1])]: null,
            })

            expect(unresolved(shown).map((row) => row.identity.customer_id)).toEqual(['222'])
            expect(shown[0].resolution?.state).toBe('applied')
        })
    })

    describe('recommendationsShownState', () => {
        const loaded: RecommendationsLoadStatus = {
            sourcesLoading: false,
            responseLoading: false,
            responseError: false,
            connectedSourceCount: 1,
            selectedSourceCount: 1,
            hasRecommendations: true,
        }

        it.each([
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
