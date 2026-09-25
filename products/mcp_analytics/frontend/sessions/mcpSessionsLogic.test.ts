import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

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

    it('refreshes the list and selected session calls together', async () => {
        listMock.mockResolvedValue({ results: [{ session_id: 'A', session_start: '2026-01-01T00:00:00Z' }] })
        toolCallsMock.mockResolvedValue({ results: [toolCall('first')], has_next: false })
        await expectLogic(logic, () => logic.actions.loadSessions()).toDispatchActions([
            'loadSessionsSuccess',
            'loadToolCallsSuccess',
        ])
        listMock.mockClear()
        toolCallsMock.mockClear()
        toolCallsMock.mockResolvedValue({ results: [toolCall('updated')], has_next: false })

        await expectLogic(logic, () => logic.actions.refreshSessions()).toDispatchActions([
            'loadSessionsSuccess',
            'loadToolCallsSuccess',
        ])

        expect(listMock).toHaveBeenCalledTimes(1)
        expect(toolCallsMock).toHaveBeenCalledTimes(1)
        expect(logic.values.selectedSessionId).toBe('A')
        expect(logic.values.selectedSessionToolCalls.calls.map((call) => call.event_id)).toEqual(['updated'])
    })

    it.each([true, false])('deep-links has_errors=%s into the sessions query and clears it', async (hasErrors) => {
        await expectLogic(logic, () => {
            router.actions.push(urls.mcpAnalyticsSessions(), { has_errors: String(hasErrors) })
        }).toDispatchActions(['loadSessionsSuccess'])

        expect(logic.values.filters.hasErrors).toBe(hasErrors)
        expect(listMock).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({ has_errors: hasErrors }))

        await expectLogic(logic, () => logic.actions.setFilters({ hasErrors: null })).toDispatchActions([
            'loadSessionsSuccess',
        ])

        expect(router.values.searchParams).not.toHaveProperty('has_errors')
        expect(listMock).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({ has_errors: undefined }))
    })

    it('ignores a failed request for a previously selected session', async () => {
        let rejectFirst: (error: Error) => void = () => {}
        toolCallsMock.mockImplementationOnce(
            () =>
                new Promise((_resolve, reject) => {
                    rejectFirst = reject
                })
        )
        await expectLogic(logic, () => logic.actions.selectSession('A')).toDispatchActions(['loadToolCalls'])
        toolCallsMock.mockResolvedValueOnce({ results: [toolCall('b1')], has_next: false })
        await expectLogic(logic, () => logic.actions.selectSession('B')).toDispatchActions(['loadToolCallsSuccess'])

        rejectFirst(new Error('Unavailable'))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.selectedSessionId).toBe('B')
        expect(logic.values.selectedSessionToolCalls.calls.map((call) => call.event_id)).toEqual(['b1'])
        expect(logic.values.selectedSessionToolCalls.error).toBe(false)
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

    it('drops a session page when a refresh starts with the same filters', async () => {
        listMock.mockResolvedValueOnce({
            results: [{ session_id: 'old', session_start: '2026-01-01T00:00:00Z' }],
            has_next: true,
        })
        toolCallsMock.mockResolvedValue({ results: [], has_next: false })
        await expectLogic(logic, () => logic.actions.loadSessions()).toDispatchActions(['loadSessionsSuccess'])

        let resolveMore: (value: any) => void = () => {}
        listMock.mockImplementationOnce(() => new Promise((resolve) => (resolveMore = resolve)))
        await expectLogic(logic, () => logic.actions.loadMoreSessions()).toDispatchActions(['loadMoreSessions'])

        listMock.mockResolvedValueOnce({
            results: [{ session_id: 'fresh', session_start: '2026-01-01T00:01:00Z' }],
            has_next: false,
        })
        await expectLogic(logic, () => logic.actions.loadSessions()).toDispatchActions(['loadSessionsSuccess'])
        await expectLogic(logic, () =>
            resolveMore({ results: [{ session_id: 'stale' }], has_next: false })
        ).toDispatchActions(['loadMoreSessionsSuccess'])

        expect(logic.values.sessions.map((session) => session.session_id)).toEqual(['fresh'])
    })

    it('drops a tool-call page when a refresh starts for the same session', async () => {
        toolCallsMock.mockResolvedValueOnce({ results: [toolCall('old')], has_next: true })
        await expectLogic(logic, () => logic.actions.selectSession('A')).toDispatchActions(['loadToolCallsSuccess'])

        let resolveMore: (value: any) => void = () => {}
        toolCallsMock.mockImplementationOnce(() => new Promise((resolve) => (resolveMore = resolve)))
        await expectLogic(logic, () => logic.actions.loadMoreToolCalls()).toDispatchActions(['loadMoreToolCalls'])

        toolCallsMock.mockResolvedValueOnce({ results: [toolCall('fresh')], has_next: false })
        await expectLogic(logic, () => logic.actions.loadToolCalls('A')).toDispatchActions(['loadToolCallsSuccess'])
        await expectLogic(logic, () =>
            resolveMore({ results: [toolCall('stale')], has_next: false })
        ).toDispatchActions(['loadMoreToolCallsSuccess'])

        expect(logic.values.selectedSessionToolCalls.calls.map((call) => call.event_id)).toEqual(['fresh'])
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
                'restored URL filters',
                () => mcpAnalyticsFiltersLogic.actions.hydrateFilters(true, [TOOL_FILTER]),
                { filter_test_accounts: true, properties: JSON.stringify([TOOL_FILTER]) },
            ],
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

        it.each([false, true])("reloads the selected session's calls with failure=%s", async (fails) => {
            const consoleErrorSpy = fails ? jest.spyOn(console, 'error').mockImplementation(() => {}) : null
            listMock.mockResolvedValue({
                results: [{ session_id: 'A', session_start: '2026-01-01T00:05:00Z' }],
                has_next: true,
            })
            toolCallsMock.mockResolvedValueOnce({ results: [toolCall('a1')], has_next: true })
            await expectLogic(logic, () => {
                logic.actions.loadSessions()
            }).toDispatchActions(['loadSessionsSuccess', 'loadToolCallsSuccess'])
            toolCallsMock.mockClear()

            let resolveFiltered: (value: any) => void = () => {}
            let rejectFiltered: (error: Error) => void = () => {}
            toolCallsMock.mockImplementationOnce(
                () =>
                    new Promise((resolve, reject) => {
                        resolveFiltered = resolve
                        rejectFiltered = reject
                    })
            )
            await expectLogic(logic, () => {
                mcpAnalyticsFiltersLogic.actions.setPropertyFilters([TOOL_FILTER])
            }).toDispatchActions(['loadToolCalls'])

            expect(logic.values.selectedSessionToolCalls.loading).toBe(true)
            expect(logic.values.selectedSessionToolCalls.calls).toEqual([])
            expect(logic.values.selectedSessionToolCalls.hasNext).toBe(false)

            await expectLogic(logic, () => {
                if (fails) {
                    rejectFiltered(new Error('Unavailable'))
                } else {
                    resolveFiltered({ results: [toolCall('filtered')], has_next: false })
                }
            }).toDispatchActions([fails ? 'loadToolCallsFailure' : 'loadToolCallsSuccess'])

            expect(toolCallsMock.mock.calls[0][2]).toMatchObject({
                properties: JSON.stringify([TOOL_FILTER]),
                date_from: '2026-01-01T00:05:00Z',
            })
            expect(logic.values.selectedSessionToolCalls.loading).toBe(false)
            expect(logic.values.selectedSessionToolCalls.error).toBe(fails)
            expect(logic.values.selectedSessionToolCalls.calls.map((c) => c.event_id)).toEqual(
                fails ? [] : ['filtered']
            )
            if (consoleErrorSpy) {
                expect(consoleErrorSpy).toHaveBeenCalledTimes(1)
                consoleErrorSpy.mockRestore()
            }
        })

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
