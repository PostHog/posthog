import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { tracingSpansImpactCreate } from 'products/tracing/frontend/generated/api'
import type { _TracingImpactResponseApi } from 'products/tracing/frontend/generated/api.schemas'

import { tracingDataLogic } from './tracingDataLogic'
import { tracingFiltersLogic } from './tracingFiltersLogic'
import { tracingImpactLogic } from './tracingImpactLogic'

jest.mock('products/tracing/frontend/generated/api', () => ({
    __esModule: true,
    tracingSpansImpactCreate: jest.fn(),
}))

const mockImpact = tracingSpansImpactCreate as jest.MockedFunction<typeof tracingSpansImpactCreate>

const ID = 'test-viewer'

const IMPACT: _TracingImpactResponseApi = {
    total: 1000,
    spansWithSessionId: 400,
    sessions: 214,
    spansWithDistinctId: 300,
    users: 96,
    topSessions: [{ value: 'sess-a', count: 40 }],
    topUsers: [{ value: 'user-1', count: 30 }],
}

// What heatmapBrushToFilters produces for the heatmap's slow tail: a duration range, in ms.
const durationFilterGroup: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [
        {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: PropertyFilterType.Span,
                    key: 'duration',
                    operator: PropertyOperator.GreaterThanOrEqual,
                    value: 500,
                },
                {
                    type: PropertyFilterType.Span,
                    key: 'duration',
                    operator: PropertyOperator.LessThan,
                    value: 1000,
                },
            ] as UniversalFiltersGroup['values'],
        },
    ],
}

describe('tracingImpactLogic', () => {
    let logic: ReturnType<typeof tracingImpactLogic.build>
    let filtersLogic: ReturnType<typeof tracingFiltersLogic.build>
    let dataLogic: ReturnType<typeof tracingDataLogic.build>

    const requestBody = (): any => mockImpact.mock.calls[mockImpact.mock.calls.length - 1][1].query

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockImpact.mockResolvedValue(IMPACT)
        filtersLogic = tracingFiltersLogic({ id: ID })
        filtersLogic.mount()
        dataLogic = tracingDataLogic({ id: ID })
        dataLogic.mount()
        logic = tracingImpactLogic({ id: ID })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        dataLogic.unmount()
        filtersLogic.unmount()
    })

    it('loads the counts on mount', async () => {
        await expectLogic(logic).toDispatchActions(['loadImpactSuccess']).toMatchValues({ impact: IMPACT })
    })

    it('scopes the request to the viewer filters', async () => {
        filtersLogic.actions.setServiceNames(['checkout'])
        filtersLogic.actions.setFilterGroup(durationFilterGroup)

        await expectLogic(logic, () => {
            dataLogic.actions.runQuery()
        }).toDispatchActions(['loadImpactSuccess'])

        // A brushed latency selection reaches the strip as these duration filters.
        expect(requestBody().serviceNames).toEqual(['checkout'])
        expect(requestBody().filterGroup).toEqual(durationFilterGroup)
    })

    it('refreshes when the filters change', async () => {
        await expectLogic(logic).toDispatchActions(['loadImpactSuccess'])

        await expectLogic(logic, () => {
            filtersLogic.actions.setServiceNames(['checkout'])
            dataLogic.actions.runQuery()
        }).toDispatchActions(['loadImpact', 'loadImpactSuccess'])

        expect(mockImpact).toHaveBeenCalledTimes(2)
    })

    it('does not re-query when the filters are unchanged', async () => {
        await expectLogic(logic).toDispatchActions(['loadImpactSuccess'])

        dataLogic.actions.runQuery()
        await expectLogic(logic).toNotHaveDispatchedActions(['loadImpact'])

        expect(mockImpact).toHaveBeenCalledTimes(1)
    })

    it('re-queries the same filters on an explicit refresh', async () => {
        await expectLogic(logic).toDispatchActions(['loadImpactSuccess'])

        await expectLogic(logic, () => {
            dataLogic.actions.refreshQuery()
        }).toDispatchActions(['loadImpact', 'loadImpactSuccess'])

        expect(mockImpact).toHaveBeenCalledTimes(2)
    })

    it('drops the previous counts while reloading', async () => {
        await expectLogic(logic).toDispatchActions(['loadImpactSuccess']).toMatchValues({ impact: IMPACT })

        await expectLogic(logic, () => {
            filtersLogic.actions.setServiceNames(['checkout'])
            dataLogic.actions.runQuery()
        })
            .toDispatchActions(['loadImpact'])
            .toMatchValues({ impact: null })
    })

    it('renders nothing rather than an error when the request fails', async () => {
        mockImpact.mockRejectedValue(new Error('boom'))

        await expectLogic(logic, () => {
            filtersLogic.actions.setServiceNames(['checkout'])
            dataLogic.actions.runQuery()
        })
            .toDispatchActions(['loadImpactSuccess'])
            .toMatchValues({ impact: null })
    })

    it('retries after a failure rather than treating the filters as done', async () => {
        mockImpact.mockRejectedValue(new Error('boom'))
        await expectLogic(logic).toDispatchActions(['loadImpactSuccess']).toMatchValues({ impact: null })

        mockImpact.mockResolvedValue(IMPACT)
        await expectLogic(logic, () => {
            dataLogic.actions.runQuery()
        })
            .toDispatchActions(['loadImpactSuccess'])
            .toMatchValues({ impact: IMPACT })
    })
})
