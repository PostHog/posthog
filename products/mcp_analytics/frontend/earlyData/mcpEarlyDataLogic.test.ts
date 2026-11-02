import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { mcpAnalyticsSessionsActivityOverview } from '../generated/api'
import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'

jest.mock('lib/api')
jest.mock('../generated/api', () => ({ mcpAnalyticsSessionsActivityOverview: jest.fn() }))

const overviewMock = mcpAnalyticsSessionsActivityOverview as jest.Mock
const TOOL_FILTER: AnyPropertyFilter = {
    key: '$mcp_tool_name',
    value: ['create_insight'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

describe('mcpEarlyDataLogic', () => {
    let logic: ReturnType<typeof mcpEarlyDataLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api as jest.Mocked<typeof api>, 'query').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api.hogFunctions, 'list').mockResolvedValue({
            count: 0,
            next: null,
            previous: null,
            results: [],
        })
        overviewMock.mockResolvedValue(null)
        logic = mcpEarlyDataLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
    })

    it.each([
        [
            'restored URL filters',
            () => mcpAnalyticsFiltersLogic.actions.hydrateFilters(true, [TOOL_FILTER]),
            { filter_test_accounts: true, properties: expect.stringContaining('$mcp_tool_name') },
            { filterTestAccounts: true, properties: [TOOL_FILTER] },
        ],
        [
            'property filters',
            () => mcpAnalyticsFiltersLogic.actions.setPropertyFilters([TOOL_FILTER]),
            { properties: expect.stringContaining('$mcp_tool_name') },
            { filterTestAccounts: false, properties: [TOOL_FILTER] },
        ],
        [
            'the test-account switch',
            () => mcpAnalyticsFiltersLogic.actions.setFilterTestAccounts(true),
            { filter_test_accounts: true },
            { filterTestAccounts: true, properties: [] },
        ],
    ])('refetches activity with %s', async (_label, change, expectedParams, expectedQuery) => {
        await expectLogic(logic).toFinishAllListeners()
        overviewMock.mockClear()

        await expectLogic(logic, change).toDispatchActions(['loadOverviewSuccess'])

        expect(overviewMock).toHaveBeenCalledTimes(1)
        expect(overviewMock.mock.calls[0][1]).toMatchObject(expectedParams)
        expect(logic.values.activityQuery.source).toMatchObject(expectedQuery)
    })

    const MINUTE = 60_000

    it.each([
        ['refreshes after one minute', [MINUTE], 1],
        ['waits two minutes after a refresh nobody reacted to', [3 * MINUTE - 1], 1],
        ['refreshes again once the doubled wait passes', [3 * MINUTE], 2],
        ['goes back to every minute after user input', [3 * MINUTE, 'input', MINUTE], 3],
        ['does not back off when the input came before the refresh', [MINUTE - 1, 'input', MINUTE + 1], 2],
        [
            'does not push the refresh back while the user keeps moving',
            [3 * MINUTE, 'input', MINUTE / 2, 'input', MINUTE / 2],
            3,
        ],
        ['never waits more than 30 minutes', [91 * MINUTE], 7],
    ] as [string, (number | 'input')[], number][])('%s', async (_label, timeline, expectedRefreshes) => {
        logic.unmount()
        jest.useFakeTimers()
        try {
            initKeaTests()
            logic = mcpEarlyDataLogic()
            logic.mount()
            overviewMock.mockClear()

            for (const step of timeline) {
                if (step === 'input') {
                    window.dispatchEvent(new Event('keydown'))
                } else {
                    jest.advanceTimersByTime(step)
                }
            }

            expect(overviewMock).toHaveBeenCalledTimes(expectedRefreshes)
        } finally {
            jest.useRealTimers()
        }
    })
})
