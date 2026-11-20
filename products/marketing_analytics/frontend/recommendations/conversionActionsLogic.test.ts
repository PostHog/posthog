import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'
import { marketingAnalyticsSettingsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'

import { useMocks } from '~/mocks/jest'
import { MarketingAnalyticsConversionActionsQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { conversionActionsLogic } from './conversionActionsLogic'

const QUERY_URL = '/api/environments/:team_id/query/MarketingAnalyticsConversionActionsQuery/'
const PURCHASE = 'customers/1/conversionActions/10'
const SIGNUP = 'customers/1/conversionActions/20'
const RESPONSE: MarketingAnalyticsConversionActionsQueryResponse = {
    results: [PURCHASE, SIGNUP].map((action) => ({
        action,
        name: action,
        account: 'Google Ads account 1',
        campaignTable: 'googleads.campaign',
        primaryConversions: action === PURCHASE ? 10 : 0,
        allConversions: 10,
        recent: true,
    })),
    unmatchedSavedActions: [],
}

describe('conversionActionsLogic', () => {
    let logic: ReturnType<typeof conversionActionsLogic.build>
    let queries: number

    beforeEach(() => {
        queries = 0
        useMocks({
            post: {
                [QUERY_URL]: () => {
                    queries += 1
                    return [200, RESPONSE]
                },
            },
        })
        initKeaTests()
        logic = conversionActionsLogic()
        logic.mount()
    })

    it('saves the selection, drops the draft, and reloads the options once the team saves', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openEditor()
        logic.actions.setSelection([SIGNUP])
        expect(logic.values.changed).toBe(true)

        await expectLogic(logic, () => logic.actions.save())
            .toDispatchActions([
                marketingAnalyticsSettingsLogic.actionCreators.updateRecommendationConversionActions([SIGNUP]),
            ])
            .toMatchValues({ draft: null, editorOpen: false, selection: [SIGNUP], changed: false })

        await expectLogic(logic).toDispatchActions(['updateCurrentTeamSuccess', 'loadOptions', 'loadOptionsSuccess'])
        expect(queries).toBe(2)

        teamLogic.actions.updateCurrentTeamSuccess(teamLogic.values.currentTeam!, { name: 'Renamed project' })
        await expectLogic(logic).toFinishAllListeners()
        expect(queries).toBe(2)
    })
})
