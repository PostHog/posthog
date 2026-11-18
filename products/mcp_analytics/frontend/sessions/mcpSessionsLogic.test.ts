import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { mcpAnalyticsSessionsList, mcpAnalyticsSessionsToolCalls } from '../generated/api'
import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import { MAX_CACHED_SESSIONS, mcpSessionsLogic } from './mcpSessionsLogic'

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

const TOOL_FILTER: AnyPropertyFilter = {
    key: '$mcp_tool_name',
    value: ['create_insight'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

const SESSION_FILTER: AnyPropertyFilter = {
    key: '$session_id',
    value: ['linked-session'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

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

    it('deep-links a session through the shared property filters', async () => {
        listMock.mockResolvedValue({
            results: [{ session_id: 'linked-session', session_start: '2026-01-01T00:00:00Z' }],
            has_next: false,
        })
        toolCallsMock.mockResolvedValue({ results: [], has_next: false })

        await expectLogic(logic, () => {
            router.actions.push(urls.mcpAnalyticsSessions(), {
                search: 'ignored-session',
                properties: [SESSION_FILTER],
            })
        }).toDispatchActions(['loadSessionsSuccess', 'loadToolCallsSuccess'])

        expect(logic.values.selectedSessionId).toBe('linked-session')
        expect(listMock.mock.lastCall?.[1]).toMatchObject({ properties: JSON.stringify([SESSION_FILTER]) })
        expect(listMock.mock.lastCall?.[1].search).toBeUndefined()
    })

    it.each([
        ['nothing', () => {}, false],
        ['has errors', () => logic.actions.setFilters({ hasErrors: false }), true],
        ['date range', () => logic.actions.setDateFilter('-30d', null), true],
        ['property filter', () => mcpAnalyticsFiltersLogic.actions.setPropertyFilters([TOOL_FILTER]), true],
        ['test accounts', () => mcpAnalyticsFiltersLogic.actions.setFilterTestAccounts(true), true],
    ])('hasActiveFilters with %s', (_name, apply, expected) => {
        apply()
        expect(logic.values.hasActiveFilters).toBe(expected)
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
            logic.actions.loadMoreToolCalls('A')
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

    it.each([
        ['unchanged filters', () => {}, 0, ['a1']],
        ['changed filters', () => mcpAnalyticsFiltersLogic.actions.setPropertyFilters([TOOL_FILTER]), 1, ['again']],
    ])('revisiting a session after another failed, with %s', async (_label, change, refetches, expectedCalls) => {
        const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
        toolCallsMock.mockResolvedValueOnce({ results: [toolCall('a1')], has_next: false })
        await expectLogic(logic, () => logic.actions.selectSession('A')).toDispatchActions(['loadToolCallsSuccess'])
        toolCallsMock.mockRejectedValueOnce(new Error('Unavailable'))
        await expectLogic(logic, () => logic.actions.selectSession('B')).toDispatchActions(['loadToolCallsFailure'])
        change()
        await expectLogic(logic).toFinishAllListeners()
        toolCallsMock.mockClear()
        toolCallsMock.mockResolvedValue({ results: [toolCall('again')], has_next: false })

        logic.actions.selectSession('A')
        await expectLogic(logic).toFinishAllListeners()

        expect(toolCallsMock).toHaveBeenCalledTimes(refetches)
        expect(logic.values.selectedSessionToolCalls).toMatchObject({ loading: false, error: false })
        expect(logic.values.selectedSessionToolCalls.calls.map((call) => call.event_id)).toEqual(expectedCalls)
        consoleErrorSpy.mockRestore()
    })

    it.each([
        ['the oldest', 0, 1],
        ['the next oldest', 1, 0],
    ])('caps the cache at %s session after visiting one more than fit', async (_label, revisited, refetches) => {
        toolCallsMock.mockResolvedValue({ results: [toolCall('call')], has_next: false })
        for (let i = 0; i <= MAX_CACHED_SESSIONS; i++) {
            await expectLogic(logic, () => logic.actions.selectSession(`s${i}`)).toDispatchActions([
                'loadToolCallsSuccess',
            ])
        }
        toolCallsMock.mockClear()

        logic.actions.selectSession(`s${revisited}`)
        await expectLogic(logic).toFinishAllListeners()

        expect(toolCallsMock).toHaveBeenCalledTimes(refetches)
    })

    it('keeps the selected session cached when a background page evicts the oldest', async () => {
        toolCallsMock.mockResolvedValue({ results: [toolCall('call')], has_next: false })
        for (let i = 0; i < MAX_CACHED_SESSIONS; i++) {
            await expectLogic(logic, () => logic.actions.selectSession(`s${i}`)).toDispatchActions([
                'loadToolCallsSuccess',
            ])
        }
        let resolveNewest: (value: any) => void = () => {}
        toolCallsMock.mockImplementationOnce(() => new Promise((resolve) => (resolveNewest = resolve)))
        logic.actions.selectSession('newest')
        logic.actions.selectSession('s0')

        await expectLogic(logic, () => resolveNewest({ results: [], has_next: false })).toDispatchActions([
            'loadToolCallsSuccess',
        ])

        expect(logic.values.selectedSessionToolCalls).toMatchObject({ loading: false, calls: [toolCall('call')] })
    })

    describe('with session A on screen and more calls to load', () => {
        const pending = (): Promise<never> => new Promise(() => {})

        beforeEach(async () => {
            listMock.mockResolvedValue({
                results: [
                    { session_id: 'A', session_start: '2026-01-01T00:00:00Z', session_end: '2026-01-01T00:10:00Z' },
                    { session_id: 'B', session_start: '2026-01-01T00:01:00Z', session_end: '2026-01-01T00:02:00Z' },
                ],
                has_next: false,
            })
            toolCallsMock.mockResolvedValueOnce({ results: [toolCall('a1')], has_next: true })
            await expectLogic(logic, () => logic.actions.loadSessions()).toDispatchActions(['loadToolCallsSuccess'])
        })

        it.each([
            ['a refresh refetches A', () => logic.actions.refreshSessions(), false],
            [
                "B's first page loads behind cached A",
                () => {
                    logic.actions.selectSession('B')
                    logic.actions.selectSession('A')
                },
                false,
            ],
            ['a load more runs for A', () => logic.actions.loadMoreToolCalls('A'), true],
        ])('reports loadingMore while %s', (_label, act, expected) => {
            toolCallsMock.mockImplementationOnce(pending)

            act()

            expect(logic.values.selectedSessionToolCalls).toMatchObject({ calls: [toolCall('a1')], hasNext: true })
            expect(logic.values.selectedSessionToolCalls.loadingMore).toBe(expected)
        })

        it.each([
            ['fails', (other: { reject: (e: Error) => void }) => other.reject(new Error('Unavailable'))],
            ['succeeds', (other: { resolve: (v: any) => void }) => other.resolve({ results: [], has_next: false })],
        ])("keeps A's load more spinning when B's load more %s first", async (_label, settle) => {
            const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
            toolCallsMock.mockResolvedValueOnce({ results: [toolCall('b1')], has_next: true })
            await expectLogic(logic, () => logic.actions.selectSession('B')).toDispatchActions(['loadToolCallsSuccess'])
            let otherRequest: { resolve: (v: any) => void; reject: (e: Error) => void } = {
                resolve: () => {},
                reject: () => {},
            }
            toolCallsMock.mockImplementationOnce(pending)
            toolCallsMock.mockImplementationOnce(
                () => new Promise((resolve, reject) => (otherRequest = { resolve, reject }))
            )
            logic.actions.selectSession('A')
            logic.actions.loadMoreToolCalls('A')
            logic.actions.selectSession('B')
            logic.actions.loadMoreToolCalls('B')

            settle(otherRequest)
            await new Promise((resolve) => setTimeout(resolve, 0))
            logic.actions.selectSession('A')

            expect(logic.values.selectedSessionToolCalls.loadingMore).toBe(true)
            consoleErrorSpy.mockRestore()
        })

        it('bounds every page of A by its start and end', async () => {
            toolCallsMock.mockResolvedValueOnce({ results: [toolCall('a2')], has_next: false })

            await expectLogic(logic, () => logic.actions.loadMoreToolCalls('A')).toDispatchActions([
                'loadMoreToolCallsSuccess',
            ])

            expect(toolCallsMock.mock.calls.map(([, , params]) => [params.date_from, params.date_to])).toEqual([
                ['2026-01-01T00:00:00Z', '2026-01-01T00:10:00Z'],
                ['2026-01-01T00:00:00Z', '2026-01-01T00:10:00Z'],
            ])
        })

        it.each([
            ['keeps its bounds', '2026-01-01T00:00:00Z', '2026-01-01T00:10:00Z', 0],
            ['moves its start', '2025-12-20T00:00:00Z', '2026-01-01T00:10:00Z', 1],
            ['moves its end', '2026-01-01T00:00:00Z', '2026-01-01T00:20:00Z', 1],
        ])('refetches A when a list reload %s', async (_label, sessionStart, sessionEnd, refetches) => {
            toolCallsMock.mockClear()
            toolCallsMock.mockResolvedValue({ results: [toolCall('wider')], has_next: false })
            listMock.mockResolvedValue({
                results: [{ session_id: 'A', session_start: sessionStart, session_end: sessionEnd }],
                has_next: false,
            })

            await expectLogic(logic, () => logic.actions.setDateFilter('-90d', null)).toDispatchActions([
                'loadSessionsSuccess',
            ])
            await expectLogic(logic).toFinishAllListeners()

            expect(toolCallsMock).toHaveBeenCalledTimes(refetches)
            toolCallsMock.mock.calls.forEach(([, , params]) =>
                expect([params.date_from, params.date_to]).toEqual([sessionStart, sessionEnd])
            )
        })

        it.each([
            ['the session ended over an hour ago', () => '2026-01-01T00:10:00Z', null, '2026-01-01T00:10:00Z'],
            [
                'the session ended minutes ago',
                () => new Date(Date.now() - 5 * 60 * 1000).toISOString(),
                null,
                undefined,
            ],
            ['the range has a fixed end', () => '2026-01-01T00:10:00Z', '2026-01-02', undefined],
        ])('picks date_to for A when %s', async (_label, sessionEnd, dateTo, expectedDateTo) => {
            toolCallsMock.mockClear()
            toolCallsMock.mockResolvedValue({ results: [toolCall('a1')], has_next: false })
            listMock.mockResolvedValue({
                results: [{ session_id: 'A', session_start: '2025-12-31T00:00:00Z', session_end: sessionEnd() }],
                has_next: false,
            })

            await expectLogic(logic, () => logic.actions.setDateFilter('2025-12-25', dateTo)).toDispatchActions([
                'loadSessionsSuccess',
            ])
            await expectLogic(logic).toFinishAllListeners()

            expect(toolCallsMock).toHaveBeenCalledTimes(1)
            expect(toolCallsMock.mock.calls[0][2].date_to).toBe(expectedDateTo)
        })

        it('refetches A when its bounds move back while the moved page is loading', async () => {
            let resolveMoved: (value: any) => void = () => {}
            toolCallsMock.mockImplementationOnce(() => new Promise((resolve) => (resolveMoved = resolve)))
            const listWithStart = (sessionStart: string): void => {
                listMock.mockResolvedValue({
                    results: [{ session_id: 'A', session_start: sessionStart, session_end: '2026-01-01T00:10:00Z' }],
                    has_next: false,
                })
            }
            listWithStart('2025-12-20T00:00:00Z')
            await expectLogic(logic, () => logic.actions.setDateFilter('-90d', null)).toDispatchActions([
                'loadSessionsSuccess',
            ])
            listWithStart('2026-01-01T00:00:00Z')
            await expectLogic(logic, () => logic.actions.setDateFilter('-7d', null)).toDispatchActions([
                'loadSessionsSuccess',
            ])
            toolCallsMock.mockResolvedValue({ results: [toolCall('current')], has_next: false })

            resolveMoved({ results: [toolCall('moved')], has_next: false })
            await expectLogic(logic).toFinishAllListeners()
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(logic.values.selectedSessionToolCalls.calls.map((call) => call.event_id)).toEqual(['current'])
            expect(toolCallsMock.mock.calls.at(-1)?.[2].date_from).toBe('2026-01-01T00:00:00Z')
        })

        it("stops A's load more spinner when a filter change replaces its first page", async () => {
            toolCallsMock.mockImplementationOnce(pending)
            logic.actions.loadMoreToolCalls('A')
            toolCallsMock.mockResolvedValueOnce({ results: [toolCall('filtered')], has_next: true })

            await expectLogic(logic, () =>
                mcpAnalyticsFiltersLogic.actions.setPropertyFilters([TOOL_FILTER])
            ).toDispatchActions(['loadToolCallsSuccess'])

            expect(logic.values.selectedSessionToolCalls).toMatchObject({
                calls: [toolCall('filtered')],
                loadingMore: false,
            })
        })

        it("keeps A's newer load more spinning when an obsolete one fails", async () => {
            const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
            let rejectObsolete: (e: Error) => void = () => {}
            toolCallsMock.mockImplementationOnce(() => new Promise((_, reject) => (rejectObsolete = reject)))
            logic.actions.loadMoreToolCalls('A')
            toolCallsMock.mockResolvedValueOnce({ results: [toolCall('filtered')], has_next: true })
            await expectLogic(logic, () =>
                mcpAnalyticsFiltersLogic.actions.setPropertyFilters([TOOL_FILTER])
            ).toDispatchActions(['loadToolCallsSuccess'])
            toolCallsMock.mockImplementationOnce(pending)
            logic.actions.loadMoreToolCalls('A')

            rejectObsolete(new Error('Unavailable'))
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(logic.values.selectedSessionToolCalls.loadingMore).toBe(true)
            consoleErrorSpy.mockRestore()
        })

        it('keeps the cached calls when a refetch fails', async () => {
            const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
            toolCallsMock.mockRejectedValueOnce(new Error('Unavailable'))

            await expectLogic(logic, () => logic.actions.refreshSessions()).toDispatchActions(['loadToolCallsFailure'])

            expect(logic.values.selectedSessionToolCalls).toMatchObject({ error: false, calls: [toolCall('a1')] })
            consoleErrorSpy.mockRestore()
        })
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
        await expectLogic(logic, () => logic.actions.loadMoreToolCalls('A')).toDispatchActions(['loadMoreToolCalls'])

        toolCallsMock.mockResolvedValueOnce({ results: [toolCall('fresh')], has_next: false })
        await expectLogic(logic, () => logic.actions.loadToolCalls('A')).toDispatchActions(['loadToolCallsSuccess'])
        await expectLogic(logic, () =>
            resolveMore({ results: [toolCall('stale')], has_next: false })
        ).toDispatchActions(['loadMoreToolCallsSuccess'])

        expect(logic.values.selectedSessionToolCalls.calls.map((call) => call.event_id)).toEqual(['fresh'])
    })

    describe('shared filters', () => {
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
            [
                "the team's test-account default",
                () =>
                    teamLogic.actions.loadCurrentTeamSuccess({
                        ...teamLogic.values.currentTeam!,
                        test_account_filters_default_checked: true,
                    }),
                { filter_test_accounts: true },
            ],
        ])('reloads the list and selected session with %s', async (_label, change, expectedParams) => {
            listMock.mockResolvedValue({ results: [{ session_id: 'A', session_start: '2026-01-01T00:05:00Z' }] })
            toolCallsMock.mockResolvedValue({ results: [toolCall('a1')], has_next: false })
            await expectLogic(logic, () => logic.actions.loadSessions()).toDispatchActions([
                'loadSessionsSuccess',
                'loadToolCallsSuccess',
            ])
            listMock.mockClear()
            toolCallsMock.mockClear()

            await expectLogic(logic, change).toDispatchActions(['loadSessionsSuccess', 'loadToolCallsSuccess'])

            expect(listMock).toHaveBeenCalledTimes(1)
            expect(listMock.mock.calls[0][1]).toMatchObject(expectedParams)
            expect(toolCallsMock).toHaveBeenCalledTimes(1)
            expect(toolCallsMock.mock.calls[0][2]).toMatchObject(expectedParams)
            expect(logic.values.selectedSessionToolCalls).toMatchObject({ loading: false, calls: [toolCall('a1')] })
        })

        it.each([false, true])("reloads the selected session's calls with failure=%s", async (fails) => {
            const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
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
            expect(consoleErrorSpy).toHaveBeenCalledTimes(fails ? 1 : 0)
            consoleErrorSpy.mockRestore()
        })

        it.each([
            ['no URL params', {}],
            ['shared filters', { filter_test_accounts: true, properties: [TOOL_FILTER] }],
            [
                'shared filters and a date range',
                { filter_test_accounts: true, properties: [TOOL_FILTER], date_from: '-30d' },
            ],
        ])('loads the list once when mounting with %s', async (_label, searchParams) => {
            logic.unmount()
            listMock.mockClear()
            router.actions.push(urls.mcpAnalyticsSessions(), searchParams)

            logic = mcpSessionsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(listMock).toHaveBeenCalledTimes(1)
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
                logic.actions.loadMoreToolCalls('A')
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
