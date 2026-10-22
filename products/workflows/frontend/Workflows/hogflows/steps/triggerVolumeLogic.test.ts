import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { performQuery } from '~/queries/query'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { triggerVolumeLogic } from './triggerVolumeLogic'

jest.mock('~/queries/query', () => ({
    ...jest.requireActual('~/queries/query'),
    performQuery: jest.fn(),
}))

describe('triggerVolumeLogic', () => {
    beforeEach(() => {
        initKeaTests()
        ;(performQuery as jest.Mock).mockReset()
        ;(performQuery as jest.Mock).mockImplementation(async (query) =>
            query.kind === NodeKind.EventsQuery
                ? {
                      results: [
                          ['2026-10-16', 700],
                          ['2026-10-17', 3],
                      ],
                  }
                : {
                      results: [
                          {
                              data: [0, 500, 0],
                              count: 500,
                              labels: ['15-Oct-2026', '16-Oct-2026', '17-Oct-2026'],
                              days: ['2026-10-15', '2026-10-16', '2026-10-17'],
                          },
                      ],
                  }
        )
    })

    // Mode 1 still writes flag calls to events, so only mode 2 adds the flag_evaluations count.
    it.each([
        ['events', FlagEvaluationsModeEnumApi.Number0, 500, 500],
        ['read flag evaluations', FlagEvaluationsModeEnumApi.Number1, 500, 500],
        ['flag evaluations only', FlagEvaluationsModeEnumApi.Number2, 1203, 1200],
    ])('estimates a trigger on feature flag calls on the %s mode', async (_name, mode, total, peakPerDay) => {
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, flag_evaluations_mode: mode })
        const logic = triggerVolumeLogic({
            id: 'trigger_node',
            filters: { events: [{ id: '$feature_flag_called', type: 'events', name: '$feature_flag_called' }] },
        })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadVolumeSuccess'])

        expect(logic.values.volume).toMatchObject({ total, peakPerDay })
    })
})
