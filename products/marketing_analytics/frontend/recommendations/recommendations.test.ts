import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import {
    RecommendationsLoadStatus,
    ResolutionOverrides,
    groupRecommendations,
    reconcileResolutionOverrides,
    recommendationsShownState,
    unresolved,
    withResolutionOverrides,
} from './recommendations'

const DISMISSED = { id: 'r1', resolution: 'dismissed' as const, resolved_at: '2026-11-01T00:00:00Z' }

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
        key: 'key-term',
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
        const rows = [
            recommendation({ rule: 'brand_overlap', key: 'keep', impactDirection: 'keep' }),
            recommendation({ key: 'a' }),
            recommendation({ key: 'b', resolution: DISMISSED }),
            recommendation({ rule: 'keyword_gap', key: 'c', resolution: DISMISSED }),
        ]

        it.each([
            {
                name: 'puts groups that only say keep last and leaves out fully resolved rules',
                showResolved: false,
                keepRule: null,
                expected: [
                    ['spend_without_conversions', ['a'], 1],
                    ['brand_overlap', ['keep'], 1],
                ],
            },
            {
                name: 'keeps the open rule with no rows once all of it is resolved',
                showResolved: false,
                keepRule: 'keyword_gap' as const,
                expected: [
                    ['spend_without_conversions', ['a'], 1],
                    ['keyword_gap', [], 0],
                    ['brand_overlap', ['keep'], 1],
                ],
            },
            {
                name: 'lists resolved rows while they are on show',
                showResolved: true,
                keepRule: null,
                expected: [
                    ['spend_without_conversions', ['a', 'b'], 1],
                    ['keyword_gap', ['c'], 0],
                    ['brand_overlap', ['keep'], 1],
                ],
            },
        ])('$name', ({ showResolved, keepRule, expected }) => {
            expect(
                groupRecommendations(rows, showResolved, keepRule).map((group) => [
                    group.rule,
                    group.recommendations.map((row) => row.key),
                    group.activeCount,
                ])
            ).toEqual(expected)
        })
    })

    describe('withResolutionOverrides', () => {
        it('applies resolutions made in this session to the matching key only', () => {
            const rows = [
                recommendation({ key: '111' }),
                recommendation({ key: '222', resolution: DISMISSED }),
                recommendation({ key: '333', resolution: DISMISSED }),
            ]

            const shown = withResolutionOverrides(rows, {
                '111': { ...DISMISSED, resolution: 'applied' },
                '222': null,
            })

            expect(unresolved(shown).map((row) => row.key)).toEqual(['222'])
            expect(shown[0].resolution?.resolution).toBe('applied')
        })
    })

    describe('reconcileResolutionOverrides', () => {
        const applied = { ...DISMISSED, resolution: 'applied' as const }

        it.each([
            ['keeps a dismissal an in-flight response does not have yet', DISMISSED, [recommendation({})], true],
            ['keeps a dismissal over an older resolution', DISMISSED, [recommendation({ resolution: applied })], true],
            [
                'keeps a restore an in-flight response does not have yet',
                null,
                [recommendation({ resolution: DISMISSED })],
                true,
            ],
            [
                'drops a dismissal the response agrees with',
                DISMISSED,
                [recommendation({ resolution: DISMISSED })],
                false,
            ],
            ['drops a restore the response agrees with', null, [recommendation({ resolution: null })], false],
            ['drops an override the response has no recommendation for', DISMISSED, [], false],
        ])('%s', (_, override, fromResponse, kept) => {
            const overrides: ResolutionOverrides = { 'key-term': override }

            expect(reconcileResolutionOverrides(overrides, fromResponse)).toEqual(kept ? overrides : {})
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
