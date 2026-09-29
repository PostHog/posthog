import { initKeaTests } from '~/test/init'

import { MessageAsset, MessageAssetsParams, getMessageAssets } from '../Workflows/messageAssetsApi'
import { broadcastSentLogic } from './broadcastSentLogic'

jest.mock('../Workflows/messageAssetsApi', () => ({ getMessageAssets: jest.fn() }))

const sends = (prefix: string, count: number): MessageAsset[] =>
    Array.from({ length: count }, (_, i) => ({
        invocation_id: `${prefix}-${i}`,
        action_id: 'email',
        function_id: 'flow-1',
        function_name: 'Broadcast',
        parent_run_id: 'run-1',
        kind: 'email',
        distinct_id: `${prefix}-${i}`,
        person_id: `person-${prefix}-${i}`,
        recipient: `${prefix}-${i}@example.com`,
        subject: 'Hello',
        status: 'sent',
        sent_at: '2026-01-01T00:00:00Z',
    }))

describe('broadcastSentLogic', () => {
    let requests: { params: MessageAssetsParams; resolve: (rows: MessageAsset[]) => void }[]

    beforeEach(() => {
        initKeaTests()
        requests = []
        jest.mocked(getMessageAssets).mockImplementation(
            (_id, params = {}) => new Promise((resolve) => requests.push({ params, resolve }))
        )
    })

    it('keeps the new search results when a stale load-more re-enables the button', async () => {
        jest.useFakeTimers()
        try {
            const logic = broadcastSentLogic({ id: 'flow-1', parentRunId: 'run-1', runCreatedAt: null })
            logic.mount()

            logic.actions.loadSends()
            requests[0].resolve(sends('all', 500))
            await jest.advanceTimersByTimeAsync(0)

            logic.actions.loadMoreSends()
            logic.actions.setRecipientSearch('ada')
            await jest.advanceTimersByTimeAsync(300)
            requests[1].resolve(sends('all-page-2', 500))
            await jest.advanceTimersByTimeAsync(0)

            logic.actions.loadMoreSends()
            const searchRequest = requests.find((request) => request.params.search === 'ada')
            searchRequest?.resolve(sends('ada', 1))
            await jest.advanceTimersByTimeAsync(0)
            requests
                .filter((request) => request !== searchRequest)
                .forEach((request) => request.resolve(sends('stale', 500)))
            await jest.advanceTimersByTimeAsync(0)

            expect(logic.values.sends.map((send) => send.invocation_id)).toEqual(['ada-0'])
        } finally {
            jest.useRealTimers()
        }
    })

    it('sends a search of only spaces as no search', async () => {
        jest.useFakeTimers()
        try {
            const logic = broadcastSentLogic({ id: 'flow-1', parentRunId: 'run-1', runCreatedAt: null })
            logic.mount()

            logic.actions.setRecipientSearch('   ')
            await jest.advanceTimersByTimeAsync(300)

            expect(requests).toHaveLength(1)
            expect(requests[0].params.search).toBeUndefined()
        } finally {
            jest.useRealTimers()
        }
    })

    it('loads the full list at once when a search with no matches is cleared', async () => {
        jest.useFakeTimers()
        try {
            const logic = broadcastSentLogic({ id: 'flow-1', parentRunId: 'run-1', runCreatedAt: null })
            logic.mount()

            logic.actions.setRecipientSearch('nobody')
            await jest.advanceTimersByTimeAsync(300)
            requests[0].resolve([])
            await jest.advanceTimersByTimeAsync(0)

            logic.actions.setRecipientSearch('')

            expect(logic.values.sendsLoading).toBe(true)
            expect(requests).toHaveLength(2)
            expect(requests[1].params.search).toBeUndefined()
        } finally {
            jest.useRealTimers()
        }
    })

    it.each([
        ['on the 29th UTC day after the run started', '2026-01-30T23:59:00Z', false],
        ['from UTC midnight on the 30th day, before 30 full days pass', '2026-01-31T00:00:00Z', true],
    ])('marks a late-day run as past retention %s', (_, now, expected) => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date(now))
        try {
            const logic = broadcastSentLogic({
                id: 'flow-1',
                parentRunId: 'run-1',
                runCreatedAt: '2026-01-01T23:00:00Z',
            })
            logic.mount()

            expect(logic.values.runPastRetention).toBe(expected)
        } finally {
            jest.useRealTimers()
        }
    })
})
