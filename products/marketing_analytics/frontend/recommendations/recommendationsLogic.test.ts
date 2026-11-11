import { expectLogic } from 'kea-test-utils'

import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { recommendationsLogic } from './recommendationsLogic'

describe('recommendationsLogic', () => {
    let logic: ReturnType<typeof recommendationsLogic.build>

    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/external_data_sources/': { results: [] } } })
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
})
