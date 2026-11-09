import { expectLogic } from 'kea-test-utils'

import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { useMocks } from '~/mocks/jest'
import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { dismissalFields, recommendationKey } from './recommendations'
import { recommendationsLogic } from './recommendationsLogic'

const DISMISSALS_URL = '/api/projects/:team_id/marketing_analytics_recommendation_dismissals/'

const RECOMMENDATION: MarketingAnalyticsRecommendation = {
    rule: 'spend_without_conversions',
    level: 'search_term',
    subject: 'example shoes',
    campaign: null,
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
            get: { '/api/environments/:team_id/external_data_sources/': { results: [] }, [DISMISSALS_URL]: [] },
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

    it('hides a dismissed recommendation, restores it, and reports both', async () => {
        useMocks({
            post: {
                [DISMISSALS_URL]: () => [201, { id: 'dismissal-1', ...dismissalFields(RECOMMENDATION) }],
            },
            delete: { [`${DISMISSALS_URL}:id/`]: [204] },
        })

        await expectLogic(marketingAnalyticsLogic, () =>
            logic.actions.dismissRecommendation(RECOMMENDATION)
        ).toDispatchActions([
            marketingAnalyticsLogic.actionCreators.reportRecommendationDismissed(
                'spend_without_conversions',
                'search_term'
            ),
        ])
        expect(logic.values.dismissedKeys.has(recommendationKey(RECOMMENDATION))).toBe(true)
        expect(logic.values.pendingKeys).toEqual([])

        await expectLogic(marketingAnalyticsLogic, () =>
            logic.actions.restoreRecommendation(RECOMMENDATION)
        ).toDispatchActions([
            marketingAnalyticsLogic.actionCreators.reportRecommendationRestored(
                'spend_without_conversions',
                'search_term'
            ),
        ])
        expect(logic.values.dismissedKeys.size).toBe(0)
        expect(logic.values.pendingKeys).toEqual([])
    })

    it('clears the pending state and reports nothing when dismissing fails', async () => {
        useMocks({ post: { [DISMISSALS_URL]: () => [500, { detail: 'nope' }] } })

        await expectLogic(logic, () => logic.actions.dismissRecommendation(RECOMMENDATION))
            .toDispatchActions(['dismissalRequestFailed'])
            .toNotHaveDispatchedActions(['dismissalSaved'])
        expect(logic.values.dismissedKeys.size).toBe(0)
        expect(logic.values.pendingKeys).toEqual([])
    })
})
