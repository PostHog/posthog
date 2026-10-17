import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { queryPerformanceLogic } from 'products/experiments/frontend/scenes/queryPerformanceLogic'

describe('queryPerformanceLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api, 'get').mockResolvedValue([])
    })

    test.each([
        ['a positive integer', '42', 'team_id=42&experiment_id=42'],
        ['a decimal', '1.5', ''],
        ['NaN', 'NaN', ''],
        ['zero', '0', ''],
        ['a negative number', '-3', ''],
    ])('sends the ID filters to slowest queries only for %s', async (_, value, expectedIdParams) => {
        const logic = queryPerformanceLogic()
        logic.mount()
        logic.actions.setTeamIdFilter(value)
        logic.actions.setExperimentIdFilter(value)

        await expectLogic(logic, () => logic.actions.loadSlowestQueries()).toFinishAllListeners()

        expect(api.get).toHaveBeenLastCalledWith(
            `api/debug_ch_queries/slowest_queries/?hours=1${expectedIdParams ? `&${expectedIdParams}` : ''}`
        )
    })
})
