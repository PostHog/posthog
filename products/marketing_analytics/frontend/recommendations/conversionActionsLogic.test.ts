import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

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

    const useTeamPatchMock = (status: number): void => {
        useMocks({
            patch: {
                '/api/projects/:id': async ({ request }) =>
                    status === 200
                        ? [200, { ...MOCK_DEFAULT_TEAM, ...((await request.json()) as Record<string, any>) }]
                        : [status, { detail: 'Invalid conversion action' }],
            },
        })
    }

    it('saves the selection, drops the draft, and reloads the options once the team saves', async () => {
        useTeamPatchMock(200)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openEditor()
        logic.actions.setSelection([SIGNUP])
        expect(logic.values.changed).toBe(true)

        await expectLogic(logic, () => logic.actions.save())
            .toDispatchActions([
                marketingAnalyticsSettingsLogic.actionCreators.updateRecommendationConversionActions([SIGNUP]),
                'updateCurrentTeamSuccess',
                'loadOptions',
                'loadOptionsSuccess',
            ])
            .toMatchValues({ draft: null, editorOpen: false, savedActions: [SIGNUP], changed: false })
        expect(queries).toBe(2)

        teamLogic.actions.updateCurrentTeamSuccess(teamLogic.values.currentTeam!, { name: 'Renamed project' })
        await expectLogic(logic).toFinishAllListeners()
        expect(queries).toBe(2)
    })

    it('keeps the draft and the editor open when the save fails, so it can be retried', async () => {
        useTeamPatchMock(400)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openEditor()
        logic.actions.setSelection([SIGNUP])

        await expectLogic(logic, () => logic.actions.save())
            .toDispatchActions([teamLogic.actionTypes.updateCurrentTeamFailure])
            .toMatchValues({ draft: [SIGNUP], editorOpen: true, savedActions: [], changed: true })
    })
})
