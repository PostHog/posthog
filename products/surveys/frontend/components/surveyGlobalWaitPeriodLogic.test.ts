import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { surveyGlobalWaitPeriodLogic } from './surveyGlobalWaitPeriodLogic'

describe('surveyGlobalWaitPeriodLogic', () => {
    let logic: ReturnType<typeof surveyGlobalWaitPeriodLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = surveyGlobalWaitPeriodLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('shows the saved wait period when the project loads after mount', () => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            survey_config: { seenSurveyWaitPeriodInDays: 30 },
        })

        expectLogic(logic).toMatchValues({ enabled: true, days: 30, saveDisabledReason: 'No changes to save' })
    })

    it('saves only the wait period key', async () => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            survey_config: { appearance: { backgroundColor: '#eeeded' }, seenSurveyWaitPeriodInDays: 30 },
        })

        await expectLogic(logic, () => {
            logic.actions.setDays(45)
            logic.actions.save()
        })
            .toDispatchActions([
                teamLogic.actionCreators.updateCurrentTeam({ survey_config: { seenSurveyWaitPeriodInDays: 45 } }),
            ])
            .toMatchValues({ editDisabledReason: 'Saving changes' })
    })
})
