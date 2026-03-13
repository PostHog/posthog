import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { reviewQueuePickerModalLogic } from './reviewQueuePickerModalLogic'
import { reviewQueuesApi } from './reviewQueuesApi'

const MOCK_CREATED_BY = {
    id: 1,
    uuid: 'user-1',
    distinct_id: 'user-1',
    first_name: 'Test',
    last_name: 'User',
    email: 'test@example.com',
    hedgehog_config: null,
} as const

jest.mock('./reviewQueuesApi', () => ({
    reviewQueuesApi: {
        listQueuePickerOptions: jest.fn(),
        createQueue: jest.fn(),
        createQueueItem: jest.fn(),
    },
}))

const mockReviewQueuesApi = reviewQueuesApi as jest.Mocked<typeof reviewQueuesApi>

describe('reviewQueuePickerModalLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
    })

    it('creates a queue inline and adds all provided traces', async () => {
        const onSuccess = jest.fn()
        const onClose = jest.fn()

        mockReviewQueuesApi.listQueuePickerOptions.mockResolvedValue({
            count: 0,
            next: null,
            previous: null,
            results: [],
        })
        mockReviewQueuesApi.createQueue.mockResolvedValue({
            id: 'queue_new',
            name: 'Support escalations',
            pending_item_count: 0,
            created_at: '2026-03-13T12:00:00Z',
            updated_at: '2026-03-13T12:00:00Z',
            created_by: MOCK_CREATED_BY,
            team: MOCK_DEFAULT_TEAM.id,
        })
        mockReviewQueuesApi.createQueueItem.mockResolvedValue({
            id: 'item_1',
            queue_id: 'queue_new',
            queue_name: 'Support escalations',
            trace_id: 'trace_1',
            created_at: '2026-03-13T12:00:00Z',
            updated_at: '2026-03-13T12:00:00Z',
            created_by: MOCK_CREATED_BY,
            team: MOCK_DEFAULT_TEAM.id,
        })

        const logic = reviewQueuePickerModalLogic({
            initialTraceIds: ['trace_1', 'trace_2'],
            onSuccess,
            onClose,
        })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSelectedQueueKey('Support escalations')

        await expectLogic(logic, () => {
            logic.actions.submit()
        }).toFinishAllListeners()

        expect(mockReviewQueuesApi.createQueue).toHaveBeenCalledWith({ name: 'Support escalations' })
        expect(mockReviewQueuesApi.createQueueItem).toHaveBeenNthCalledWith(1, {
            queue_id: 'queue_new',
            trace_id: 'trace_1',
        })
        expect(mockReviewQueuesApi.createQueueItem).toHaveBeenNthCalledWith(2, {
            queue_id: 'queue_new',
            trace_id: 'trace_2',
        })
        expect(onSuccess).toHaveBeenCalledWith({ queueId: 'queue_new', createdQueue: true })
        expect(onClose).toHaveBeenCalled()
    })
})
