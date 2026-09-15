import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { mcpAnalyticsSessionsActivityOverview, mcpAnalyticsSessionsIntentDigest } from '../generated/api'
import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'

jest.mock('lib/api')
jest.mock('../generated/api', () => ({
    mcpAnalyticsSessionsActivityOverview: jest.fn(),
    mcpAnalyticsSessionsIntentDigest: jest.fn(),
}))

const overviewMock = mcpAnalyticsSessionsActivityOverview as jest.Mock
const digestMock = mcpAnalyticsSessionsIntentDigest as jest.Mock

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
        overviewMock.mockResolvedValue(null)
        digestMock.mockResolvedValue({ digest: 'agents looked at signups', intent_count: 9, themes: [] })
        logic = mcpEarlyDataLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
    })

    // The feed's own query object carries the filters, but the counters, top tools and clients come
    // from this endpoint — without the refetch they keep describing the unfiltered set.
    it.each([
        [
            'property filters',
            () => mcpAnalyticsFiltersLogic.actions.setPropertyFilters([TOOL_FILTER]),
            { properties: JSON.stringify([TOOL_FILTER]) },
        ],
        [
            'the test-account switch',
            () => mcpAnalyticsFiltersLogic.actions.setFilterTestAccounts(true),
            { filter_test_accounts: true },
        ],
    ])('refetches the activity overview with %s', async (_label, change, expectedParams) => {
        await expectLogic(logic).toFinishAllListeners()
        overviewMock.mockClear()

        await expectLogic(logic, change).toDispatchActions(['loadOverviewSuccess'])

        expect(overviewMock).toHaveBeenCalledTimes(1)
        expect(overviewMock.mock.calls[0][1]).toMatchObject(expectedParams)
    })

    it('clears the old overview during a filtered request and keeps it cleared on failure', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadOverviewSuccess({
            stats: {
                total_calls: 10,
                distinct_tools: 1,
                distinct_sessions: 1,
                distinct_clients: 1,
                calls_with_intent: 0,
                error_calls: 0,
                missing_capability_reports: 0,
            },
            top_tools: [{ tool: 'previous_tool', calls: 10, errors: 0 }],
            clients: [{ client: 'previous_client', calls: 10 }],
            recent_calls: [],
        })
        let rejectOverview: (error: Error) => void = () => {}
        overviewMock.mockImplementationOnce(() => new Promise((_, reject) => (rejectOverview = reject)))

        await expectLogic(logic, () => {
            mcpAnalyticsFiltersLogic.actions.setPropertyFilters([TOOL_FILTER])
        }).toMatchValues({ overview: null, overviewLoading: true, topTools: [], clients: [] })

        await expectLogic(logic, () => {
            rejectOverview(new Error('Unavailable'))
        }).toDispatchActions(['loadOverviewFailure'])
        expect(logic.values.overview).toBeNull()
        expect(logic.values.overviewError).toBe(true)
        expect(logic.values.overviewLoading).toBe(false)
    })

    // The digest is a project-level LLM summary with no filtered variant, and the card prefers it
    // over the verbatim intents. Left in place it would describe traffic the rest of the tab
    // excludes; dropped, the card falls back to the intents from the filtered overview.
    it('drops the intent digest while a shared filter is active, and restores it after', async () => {
        await expectLogic(logic).toDispatchActions(['loadIntentDigestSuccess'])
        expect(logic.values.intentDigest?.digest).toBe('agents looked at signups')
        digestMock.mockClear()

        await expectLogic(logic, () => {
            mcpAnalyticsFiltersLogic.actions.setPropertyFilters([TOOL_FILTER])
        }).toDispatchActions(['loadIntentDigestSuccess'])
        expect(logic.values.intentDigest).toBeNull()
        expect(digestMock).not.toHaveBeenCalled()

        await expectLogic(logic, () => {
            mcpAnalyticsFiltersLogic.actions.setPropertyFilters([])
        }).toDispatchActions(['loadIntentDigestSuccess'])
        expect(logic.values.intentDigest?.digest).toBe('agents looked at signups')
    })
})
