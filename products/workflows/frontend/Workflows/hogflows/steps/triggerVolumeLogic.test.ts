import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { matchingFiltersToPropertyGroup } from 'scenes/hog-functions/filters/matchingFilters'
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
    // On mode 2 the trends query leaves out flag calls, so a call that both tables hold counts once.
    it.each([
        ['events', FlagEvaluationsModeEnumApi.Number0, 500, 500, false],
        ['read flag evaluations', FlagEvaluationsModeEnumApi.Number1, 500, 500, false],
        ['flag evaluations only', FlagEvaluationsModeEnumApi.Number2, 1203, 1200, true],
    ])(
        'estimates a trigger on feature flag calls on the %s mode',
        async (_name, mode, total, peakPerDay, excludesFlagCalls) => {
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, flag_evaluations_mode: mode })
            const filters = {
                events: [{ id: '$feature_flag_called', type: 'events' as const, name: '$feature_flag_called' }],
            }
            const logic = triggerVolumeLogic({ id: 'trigger_node', filters })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadVolumeSuccess'])

            expect(logic.values.volume).toMatchObject({ total, peakPerDay })
            const queries = (performQuery as jest.Mock).mock.calls.map(([query]) => query)
            const trendsQuery = queries.find((query) => query.kind === NodeKind.TrendsQuery)
            const trendsProperties = JSON.stringify(trendsQuery.properties)
            expect(trendsProperties).toContain(JSON.stringify(matchingFiltersToPropertyGroup(filters)))
            expect(trendsProperties.includes("event != '$feature_flag_called'")).toBe(excludesFlagCalls)
            const flagCallsQuery = queries.find((query) => query.kind === NodeKind.EventsQuery)
            expect(flagCallsQuery?.modifiers?.personsOnEventsMode).toBe(
                excludesFlagCalls ? 'person_id_no_override_properties_on_events' : undefined
            )
        }
    )
})
