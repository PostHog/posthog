import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { MessageAsset, MessageAssetsParams, getMessageAssets } from '../Workflows/messageAssetsApi'
import { broadcastSentLogic } from './broadcastSentLogic'

jest.mock('../Workflows/messageAssetsApi', () => ({ getMessageAssets: jest.fn() }))

const sends = (prefix: string, count: number): MessageAsset[] =>
    Array.from({ length: count }, (_, i) => ({ invocation_id: `${prefix}-${i}`, action_id: 'email' }) as MessageAsset)

const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

describe('broadcastSentLogic', () => {
    let requests: { params: MessageAssetsParams; resolve: (rows: MessageAsset[]) => void }[]

    beforeEach(() => {
        initKeaTests()
        requests = []
        jest.mocked(getMessageAssets).mockImplementation(
            (_id, params = {}) => new Promise((resolve) => requests.push({ params, resolve }))
        )
    })

    it('keeps the new filter results when a stale load-more re-enables the button', async () => {
        const logic = broadcastSentLogic({ id: 'flow-1', parentRunId: 'run-1', runCreatedAt: null })
        logic.mount()

        logic.actions.loadSends()
        requests[0].resolve(sends('all', 500))
        await settle()

        logic.actions.loadMoreSends()
        logic.actions.setStatusFilter('bounced')
        requests[1].resolve(sends('all-page-2', 500))
        await settle()

        logic.actions.loadMoreSends()
        const bouncedRequest = requests.find((request) => request.params.status === 'bounced')
        bouncedRequest?.resolve(sends('bounced', 1))
        await settle()
        requests.slice(3).forEach((request) => request.resolve(sends('all-page-3', 500)))

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.sends.map((send) => send.invocation_id)).toEqual(['bounced-0'])
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
