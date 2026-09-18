import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import {
    mcpAnalyticsSessionsGenerateIntent,
    mcpAnalyticsSessionsList,
    mcpAnalyticsSessionsToolCalls,
} from '../generated/api'
import { mcpSessionsLogic } from './mcpSessionsLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast')
jest.mock('../generated/api', () => ({
    mcpAnalyticsSessionsList: jest.fn(),
    mcpAnalyticsSessionsToolCalls: jest.fn(),
    mcpAnalyticsSessionsGenerateIntent: jest.fn(),
}))

const listMock = mcpAnalyticsSessionsList as jest.Mock
const toolCallsMock = mcpAnalyticsSessionsToolCalls as jest.Mock
const generateIntentMock = mcpAnalyticsSessionsGenerateIntent as jest.Mock
const errorToastMock = lemonToast.error as jest.Mock

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

    // The global kea-loaders handler used to toast on top of this logic's own listener, so one
    // failed generation raised two stacked toasts. The 503 case guards the message choice: that
    // detail names one fixed cause, which is wrong for a timed-out or empty LLM response.
    it.each([
        {
            name: 'the server reason for a request that can never succeed',
            sessionId: 'too-long',
            status: 400,
            detail: 'session_id must be at most 200 characters.',
            expected: 'session_id must be at most 200 characters.',
        },
        {
            name: 'the retry hint when generation fails server-side',
            sessionId: 'session-a',
            status: 503,
            detail: 'Intent generation is unavailable (LLM not configured).',
            expected: 'Could not generate the session intent. Please try again.',
        },
    ])('raises one toast carrying $name', async ({ sessionId, status, detail, expected }) => {
        generateIntentMock.mockRejectedValueOnce({ status, detail })

        await expectLogic(logic, () => {
            logic.actions.generateIntent(sessionId)
        }).toDispatchActions(['generateIntentFailure'])

        expect(errorToastMock).toHaveBeenCalledTimes(1)
        expect(errorToastMock).toHaveBeenCalledWith(expected)
    })
})
