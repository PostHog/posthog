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
        expect(logic.values.toolCalls.map((c) => c.event_id)).toEqual(['a1'])

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
        expect(logic.values.isSelectedSessionToolCallsLoading).toBe(true)

        // A's load-more finally resolves. It must neither merge into B's list nor drop B's skeleton.
        await expectLogic(logic, () => {
            resolveAMore({ results: [toolCall('a2')], has_next: false })
        }).toDispatchActions(['loadMoreToolCallsSuccess'])

        expect(logic.values.isSelectedSessionToolCallsLoading).toBe(true)
        expect(logic.values.toolCalls.map((c) => c.event_id)).not.toContain('a2')
    })
})
