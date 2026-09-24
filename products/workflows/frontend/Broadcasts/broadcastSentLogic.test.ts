import { initKeaTests } from '~/test/init'

import { MessageAsset, MessageAssetsParams, getMessageAssets } from '../Workflows/messageAssetsApi'
import { broadcastSentLogic } from './broadcastSentLogic'

jest.mock('../Workflows/messageAssetsApi', () => ({ getMessageAssets: jest.fn() }))

const sends = (prefix: string, count: number): MessageAsset[] =>
    Array.from({ length: count }, (_, i) => ({ invocation_id: `${prefix}-${i}`, action_id: 'email' }) as MessageAsset)

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
})
