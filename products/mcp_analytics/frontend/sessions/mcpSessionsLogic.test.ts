import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { mcpAnalyticsSessionsList, mcpAnalyticsSessionsToolCalls } from '../generated/api'
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

const session = (sessionId: string): any => ({
    session_id: sessionId,
    session_start: '2026-01-01T00:00:00Z',
    session_end: '2026-01-01T00:01:00Z',
    tool_calls: 1,
    tools_used: [],
    mcp_client_name: '',
    distinct_id: '',
    person_email: '',
    person_name: '',
    intent: '',
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

    it('surfaces an error state when the first page of sessions fails to load', async () => {
        // Let the mount's initial (empty) load settle before overriding the mock.
        await expectLogic(logic).toDispatchActions(['loadSessionsSuccess'])

        listMock.mockRejectedValueOnce(new Error('500'))
        await expectLogic(logic, () => {
            logic.actions.loadSessions()
        }).toDispatchActions(['loadSessions', 'loadSessionsFailure'])

        expect(logic.values.loadError).toBe(true)
        expect(logic.values.sessions).toEqual([])
    })

    it('keeps the loaded list without an error state when loading more fails', async () => {
        await expectLogic(logic).toDispatchActions(['loadSessionsSuccess'])

        listMock.mockResolvedValueOnce({ results: [session('a')], has_next: true })
        await expectLogic(logic, () => {
            logic.actions.loadSessions()
        }).toDispatchActions(['loadSessionsSuccess'])

        listMock.mockRejectedValueOnce(new Error('500'))
        await expectLogic(logic, () => {
            logic.actions.loadMoreSessions()
        }).toDispatchActions(['loadMoreSessions', 'loadMoreSessionsFailure'])

        expect(logic.values.sessions.map((s: any) => s.session_id)).toEqual(['a'])
        expect(logic.values.loadError).toBe(false)
    })
})
