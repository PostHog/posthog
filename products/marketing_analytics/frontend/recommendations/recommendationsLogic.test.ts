import { expectLogic } from 'kea-test-utils'

import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { recommendationKey } from './recommendations'
import { recommendationsLogic } from './recommendationsLogic'

const RESOLUTIONS_URL = '/api/projects/:team_id/marketing_analytics_recommendation_resolutions/'

const RECOMMENDATION: MarketingAnalyticsRecommendation = {
    rule: 'spend_without_conversions',
    level: 'search_term',
    subject: 'example shoes',
    campaign: 'Search',
    identity: {
        rule: 'spend_without_conversions',
        source_type: 'google_ads',
        customer_id: '1234567890',
        campaign_id: '',
        subject: 'example shoes',
    },
    action: 'Add it as a negative keyword',
    reason: 'No conversions',
    impact: 100,
    impactDirection: 'save',
    impactType: 'measured',
    currency: 'USD',
}

describe('recommendationsLogic', () => {
    let logic: ReturnType<typeof recommendationsLogic.build>

    beforeEach(() => {
        useMocks({
            get: { '/api/environments/:team_id/external_data_sources/': { results: [] } },
        })
        initKeaTests()
        logic = recommendationsLogic()
        logic.mount()
    })

    it.each([
        {
            name: 'opening reports the entry point',
            run: () => logic.actions.openRecommendations('brand_leak', 'intro', 7),
            reported: () => marketingAnalyticsLogic.actionCreators.reportRecommendationsOpened('intro', 7),
        },
        {
            name: 'selecting a rule reports the rule',
            run: () => logic.actions.selectRule('keyword_gap', 3),
            reported: () => marketingAnalyticsLogic.actionCreators.reportRecommendationsRuleSelected('keyword_gap', 3),
        },
        {
            name: 'closing reports the rule that was open',
            run: () => {
                logic.actions.openRecommendations('brand_leak', 'button', 7)
                logic.actions.closeRecommendations()
            },
            reported: () => marketingAnalyticsLogic.actionCreators.reportRecommendationsClosed('brand_leak'),
        },
        {
            name: 'dismissing the intro reports it',
            run: () => logic.actions.dismissIntro(),
            reported: () => marketingAnalyticsLogic.actionCreators.reportRecommendationsIntroDismissed(),
        },
    ])('$name', async ({ run, reported }) => {
        await expectLogic(marketingAnalyticsLogic, run).toDispatchActions([reported()])
    })

    it.each(['dismissed', 'applied'] as const)(
        'hides a recommendation marked %s, restores it, and reports both',
        async (resolution) => {
            let posted: Record<string, unknown> | undefined
            useMocks({
                post: {
                    [RESOLUTIONS_URL]: async ({ request }) => {
                        posted = (await request.json()) as Record<string, unknown>
                        return [201, { id: 'resolution-1', ...posted, resolved_at: '2026-11-01T00:00:00Z' }]
                    },
                },
                delete: { [`${RESOLUTIONS_URL}:id/`]: [204] },
            })
            const key = recommendationKey(RECOMMENDATION)

            await expectLogic(marketingAnalyticsLogic, () =>
                logic.actions.resolveRecommendation(RECOMMENDATION, resolution)
            ).toDispatchActions([
                marketingAnalyticsLogic.actionCreators.reportRecommendationResolved(
                    'spend_without_conversions',
                    'search_term',
                    resolution
                ),
            ])
            expect(posted).toEqual({
                ...RECOMMENDATION.identity,
                resolution,
                snapshot: { action: 'Add it as a negative keyword', impact: 100, currency: 'USD' },
            })
            expect(logic.values.resolutionOverrides[key]?.state).toBe(resolution)
            expect(logic.values.pendingKeys).toEqual([])

            await expectLogic(marketingAnalyticsLogic, () =>
                logic.actions.restoreRecommendation({
                    ...RECOMMENDATION,
                    resolution: logic.values.resolutionOverrides[key],
                })
            ).toDispatchActions([
                marketingAnalyticsLogic.actionCreators.reportRecommendationRestored(
                    'spend_without_conversions',
                    'search_term',
                    resolution
                ),
            ])
            expect(logic.values.resolutionOverrides[key]).toBeNull()
            expect(logic.values.pendingKeys).toEqual([])

            await expectLogic(logic, () =>
                dataNodeLogic(logic.values.dataNodeProps).actions.loadDataSuccess({ results: [], disclaimer: '' })
            ).toMatchValues({ resolutionOverrides: {} })
        }
    )

    it('clears the pending state and reports nothing when resolving fails', async () => {
        useMocks({ post: { [RESOLUTIONS_URL]: () => [500, { detail: 'nope' }] } })

        await expectLogic(logic, () => logic.actions.resolveRecommendation(RECOMMENDATION, 'dismissed'))
            .toDispatchActions(['resolutionRequestFailed'])
            .toNotHaveDispatchedActions(['resolutionSaved'])
        expect(logic.values.resolutionOverrides).toEqual({})
        expect(logic.values.pendingKeys).toEqual([])
    })

    it('drops the local resolution when someone else already restored it', async () => {
        useMocks({ delete: { [`${RESOLUTIONS_URL}:id/`]: () => [404, { detail: 'Not found.' }] } })
        const resolved = {
            ...RECOMMENDATION,
            resolution: { id: 'resolution-1', state: 'dismissed' as const, resolvedAt: '2026-11-01T00:00:00Z' },
        }

        await expectLogic(logic, () => logic.actions.restoreRecommendation(resolved))
            .toDispatchActions(['resolutionRemoved'])
            .toNotHaveDispatchedActions(['resolutionRequestFailed'])
        expect(logic.values.resolutionOverrides[recommendationKey(RECOMMENDATION)]).toBeNull()
        expect(logic.values.pendingKeys).toEqual([])
    })
})
