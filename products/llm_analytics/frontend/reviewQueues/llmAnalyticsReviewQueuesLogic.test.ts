import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from '~/lib/api.mock'

import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { addProjectIdIfMissing } from 'lib/utils/router-utils'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import {
    llmAnalyticsReviewQueuesLogic,
    REVIEW_QUEUE_ITEMS_PER_PAGE,
    REVIEW_QUEUES_PER_PAGE,
} from './llmAnalyticsReviewQueuesLogic'
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
        listQueues: jest.fn(),
        getQueue: jest.fn(),
        listQueueItems: jest.fn(),
        createQueue: jest.fn(),
        updateQueue: jest.fn(),
        deleteQueue: jest.fn(),
        deleteQueueItem: jest.fn(),
    },
}))

const mockReviewQueuesApi = reviewQueuesApi as jest.Mocked<typeof reviewQueuesApi>

describe('llmAnalyticsReviewQueuesLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()

        mockReviewQueuesApi.listQueues.mockResolvedValue({
            count: 2,
            next: null,
            previous: null,
            results: [
                {
                    id: 'queue_1',
                    name: 'Support',
                    pending_item_count: 2,
                    created_at: '2026-03-13T12:00:00Z',
                    updated_at: '2026-03-13T12:00:00Z',
                    created_by: MOCK_CREATED_BY,
                    team: MOCK_DEFAULT_TEAM.id,
                },
                {
                    id: 'queue_2',
                    name: 'Billing',
                    pending_item_count: 1,
                    created_at: '2026-03-13T12:00:00Z',
                    updated_at: '2026-03-13T12:00:00Z',
                    created_by: MOCK_CREATED_BY,
                    team: MOCK_DEFAULT_TEAM.id,
                },
            ],
        })
        mockReviewQueuesApi.getQueue.mockResolvedValue({
            id: 'queue_99',
            name: 'Escalations',
            pending_item_count: 4,
            created_at: '2026-03-13T12:00:00Z',
            updated_at: '2026-03-13T12:00:00Z',
            created_by: MOCK_CREATED_BY,
            team: MOCK_DEFAULT_TEAM.id,
        })
        mockReviewQueuesApi.listQueueItems.mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [
                {
                    id: 'item_1',
                    queue_id: 'queue_1',
                    queue_name: 'Support',
                    trace_id: 'trace_1',
                    created_at: '2026-03-13T12:00:00Z',
                    updated_at: '2026-03-13T12:00:00Z',
                    created_by: MOCK_CREATED_BY,
                    team: MOCK_DEFAULT_TEAM.id,
                },
            ],
        })
    })

    it('loads queues on mount and auto-selects the first queue', async () => {
        const logic = llmAnalyticsReviewQueuesLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(mockReviewQueuesApi.listQueues).toHaveBeenCalledWith({
            search: undefined,
            order_by: 'name',
            offset: 0,
            limit: REVIEW_QUEUES_PER_PAGE,
        })
        expect(mockReviewQueuesApi.listQueueItems).toHaveBeenCalledWith({
            queue_id: 'queue_1',
            search: undefined,
            order_by: 'created_at',
            offset: 0,
            limit: REVIEW_QUEUE_ITEMS_PER_PAGE,
        })
        expect(logic.values.selectedQueueId).toBe('queue_1')
        expect(logic.values.activeQueue?.name).toBe('Support')
    })

    it('keeps a selected queue active even when it is not in the current list page', async () => {
        const logic = llmAnalyticsReviewQueuesLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.selectQueue('queue_99')
        }).toFinishAllListeners()

        expect(mockReviewQueuesApi.getQueue).toHaveBeenCalledWith('queue_99')
        expect(logic.values.selectedQueueId).toBe('queue_99')
        expect(logic.values.activeQueue?.id).toBe('queue_99')
        expect(logic.values.activeQueue?.name).toBe('Escalations')
        expect(logic.values.visibleQueues.map((queue) => queue.id)).toEqual(['queue_99', 'queue_1', 'queue_2'])

        await expectLogic(logic, () => {
            logic.actions.loadQueuesSuccess({
                count: 2,
                next: null,
                previous: null,
                results: [
                    {
                        id: 'queue_1',
                        name: 'Support',
                        pending_item_count: 2,
                        created_at: '2026-03-13T12:00:00Z',
                        updated_at: '2026-03-13T12:00:00Z',
                        created_by: MOCK_CREATED_BY,
                        team: MOCK_DEFAULT_TEAM.id,
                    },
                    {
                        id: 'queue_2',
                        name: 'Billing',
                        pending_item_count: 1,
                        created_at: '2026-03-13T12:00:00Z',
                        updated_at: '2026-03-13T12:00:00Z',
                        created_by: MOCK_CREATED_BY,
                        team: MOCK_DEFAULT_TEAM.id,
                    },
                ],
            })
        }).toFinishAllListeners()

        expect(logic.values.selectedQueueId).toBe('queue_99')
        expect(logic.values.activeQueue?.id).toBe('queue_99')
        expect(logic.values.activeQueue?.name).toBe('Escalations')
        expect(logic.values.visibleQueues.map((queue) => queue.id)).toEqual(['queue_99', 'queue_1', 'queue_2'])
    })

    it('prefers queue_id from the URL during the initial page load', async () => {
        const reviewsUrl = combineUrl(urls.llmAnalyticsReviews(), { queue_id: 'queue_99' })
        router.actions.push(addProjectIdIfMissing(reviewsUrl.url, MOCK_TEAM_ID))

        const logic = llmAnalyticsReviewQueuesLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.selectedQueueId).toBe('queue_99')
        expect(logic.values.activeQueue?.id).toBe('queue_99')
        expect(logic.values.activeQueue?.name).toBe('Escalations')
        expect(logic.values.visibleQueues.map((queue) => queue.id)).toEqual(['queue_99', 'queue_1', 'queue_2'])
        expect(mockReviewQueuesApi.listQueueItems).toHaveBeenCalledWith({
            queue_id: 'queue_99',
            search: undefined,
            order_by: 'created_at',
            offset: 0,
            limit: REVIEW_QUEUE_ITEMS_PER_PAGE,
        })
    })
})
