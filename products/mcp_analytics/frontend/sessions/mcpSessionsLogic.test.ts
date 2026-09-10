import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { mcpAnalyticsSessionsList, mcpAnalyticsSessionsToolCalls } from '../generated/api'
import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import { mcpSessionsLogic } from './mcpSessionsLogic'

jest.mock('../generated/api', () => ({
    mcpAnalyticsSessionsList: jest.fn(),
    mcpAnalyticsSessionsToolCalls: jest.fn(),
    mcpAnalyticsSessionsGenerateIntent: jest.fn(),
}))

const listMock = mcpAnalyticsSessionsList as jest.Mock
const toolCallsMock = mcpAnalyticsSessionsToolCalls as jest.Mock

const toolCall = (eventId: string): any => ({
    event_id: eventId,
    timestamp: '2026-01-01T00:00:00Z',
    tool_name: eventId,
    intent: '',
    is_error: false,
    error_message: '',
    duration_ms: null,
})

describe('mcpSessionsLogic', () => {
    let logic: ReturnType<typeof mcpSessionsLogic.build>

    beforeEach(() => {
        initKeaTests()
        listMock.mockResolvedValue({ results: [], has_next: false })
        logic = mcpSessionsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
    })

    it('keeps the skeleton on the newly selected session when a prior load-more resolves late', async () => {
        // Session A: a first page with a further page available.
        toolCallsMock.mockResolvedValueOnce({ results: [toolCall('a1')], has_next: true })
        await expectLogic(logic, () => {
            logic.actions.selectSession('A')
        }).toDispatchActions(['loadToolCallsSuccess'])
        expect(logic.values.selectedSessionToolCalls.calls.map((c) => c.event_id)).toEqual(['a1'])

        // "Load more" for A is dispatched but held in flight.
        let resolveAMore: (value: any) => void = () => {}
        toolCallsMock.mockImplementationOnce(() => new Promise((resolve) => (resolveAMore = resolve)))
        await expectLogic(logic, () => {
            logic.actions.loadMoreToolCalls()
        }).toDispatchActions(['loadMoreToolCalls'])

        // The user switches to B before A's page returns; B's first page never resolves here.
        toolCallsMock.mockImplementationOnce(() => new Promise(() => {}))
        await expectLogic(logic, () => {
            logic.actions.selectSession('B')
        }).toDispatchActions(['loadToolCalls'])
        expect(logic.values.selectedSessionId).toBe('B')
        expect(logic.values.selectedSessionToolCalls.loading).toBe(true)

        // A's load-more finally resolves. It must neither merge into B's list nor drop B's skeleton.
        await expectLogic(logic, () => {
            resolveAMore({ results: [toolCall('a2')], has_next: false })
        }).toDispatchActions(['loadMoreToolCallsSuccess'])

        expect(logic.values.selectedSessionToolCalls.loading).toBe(true)
        expect(logic.values.selectedSessionToolCalls.calls.map((c) => c.event_id)).not.toContain('a2')
    })

    describe('shared filters', () => {
        const TOOL_FILTER: AnyPropertyFilter = {
            key: '$mcp_tool_name',
            value: ['create_insight'],
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        }

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
        ])('reloads the list with %s', async (_label, change, expectedParams) => {
            listMock.mockClear()

            await expectLogic(logic, change).toDispatchActions(['loadSessionsSuccess'])

            expect(listMock).toHaveBeenCalledTimes(1)
            expect(listMock.mock.calls[0][1]).toMatchObject(expectedParams)
        })

        // Without this the list narrows but the open session's detail panel keeps showing calls
        // the list no longer counts. The panel must not show the old calls in the meantime either,
        // which is what tagging the loaded calls with their filters buys.
        it("reloads the selected session's calls with the same filters", async () => {
            listMock.mockResolvedValue({
                results: [{ session_id: 'A', session_start: '2026-01-01T00:05:00Z' }],
                has_next: true,
            })
            toolCallsMock.mockResolvedValueOnce({ results: [toolCall('a1')], has_next: true })
            // Load the list first: the detail scan is bounded by the session row's session_start.
            await expectLogic(logic, () => {
                logic.actions.loadSessions()
            }).toDispatchActions(['loadSessionsSuccess', 'loadToolCallsSuccess'])
            toolCallsMock.mockClear()

            let resolveFiltered: (value: any) => void = () => {}
            toolCallsMock.mockImplementationOnce(() => new Promise((resolve) => (resolveFiltered = resolve)))
            await expectLogic(logic, () => {
                mcpAnalyticsFiltersLogic.actions.setPropertyFilters([TOOL_FILTER])
            }).toDispatchActions(['loadToolCalls'])

            // The pre-filter calls are gone from the panel while the filtered page is in flight, so
            // no stale row shows and "Load more" cannot paginate from them.
            expect(logic.values.selectedSessionToolCalls.loading).toBe(true)
            expect(logic.values.selectedSessionToolCalls.calls).toEqual([])
            expect(logic.values.selectedSessionToolCalls.hasNext).toBe(false)

            await expectLogic(logic, () => {
                resolveFiltered({ results: [toolCall('filtered')], has_next: false })
            }).toDispatchActions(['loadToolCallsSuccess'])

            expect(toolCallsMock.mock.calls[0][2]).toMatchObject({
                properties: JSON.stringify([TOOL_FILTER]),
                // session_start is filter-independent, so the detail scan still covers the session.
                date_from: '2026-01-01T00:05:00Z',
            })
            expect(logic.values.selectedSessionToolCalls.calls.map((c) => c.event_id)).toEqual(['filtered'])
        })

        // The session stays selected across a filter change, so the session-id guard alone lets an
        // in-flight "load more" put the pre-filter page back on screen.
        it('drops a load-more page fetched under the previous filters', async () => {
            listMock.mockResolvedValue({
                results: [{ session_id: 'A', session_start: '2026-01-01T00:05:00Z' }],
                has_next: false,
            })
            toolCallsMock.mockResolvedValueOnce({ results: [toolCall('a1')], has_next: true })
            await expectLogic(logic, () => {
                logic.actions.selectSession('A')
            }).toDispatchActions(['loadToolCallsSuccess'])

            let resolveMore: (value: any) => void = () => {}
            toolCallsMock.mockImplementationOnce(() => new Promise((resolve) => (resolveMore = resolve)))
            await expectLogic(logic, () => {
                logic.actions.loadMoreToolCalls()
            }).toDispatchActions(['loadMoreToolCalls'])

            toolCallsMock.mockResolvedValue({ results: [toolCall('filtered')], has_next: false })
            await expectLogic(logic, () => {
                mcpAnalyticsFiltersLogic.actions.setPropertyFilters([TOOL_FILTER])
            }).toDispatchActions(['loadToolCallsSuccess'])

            await expectLogic(logic, () => {
                resolveMore({ results: [toolCall('a2')], has_next: false })
            }).toDispatchActions(['loadMoreToolCallsSuccess'])

            expect(logic.values.selectedSessionToolCalls.calls.map((c) => c.event_id)).toEqual(['filtered'])
        })

        // Two rapid filter changes leave two list requests in flight. If the first one still
        // publishes, its stale session rows bound the detail scan the second one asked for.
        it('drops a superseded session page', async () => {
            let resolveFirst: (value: any) => void = () => {}
            listMock.mockImplementationOnce(() => new Promise((resolve) => (resolveFirst = resolve)))
            await expectLogic(logic, () => {
                mcpAnalyticsFiltersLogic.actions.setPropertyFilters([TOOL_FILTER])
            }).toDispatchActions(['loadSessions'])

            listMock.mockResolvedValue({
                results: [{ session_id: 'current', session_start: '2026-01-01T00:00:00Z' }],
                has_next: false,
            })
            toolCallsMock.mockResolvedValue({ results: [], has_next: false })
            await expectLogic(logic, () => {
                mcpAnalyticsFiltersLogic.actions.setPropertyFilters([])
            }).toDispatchActions(['loadSessionsSuccess'])

            resolveFirst({ results: [{ session_id: 'superseded', session_start: '2026-01-01T00:09:00Z' }] })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.sessions.map((s) => s.session_id)).toEqual(['current'])
        })
    })
})
