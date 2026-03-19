import { ApiConfig } from '~/lib/api'

import {
    llmAnalyticsReviewQueueItemsCreate,
    llmAnalyticsReviewQueueItemsDestroy,
    llmAnalyticsReviewQueueItemsList,
    llmAnalyticsReviewQueueItemsPartialUpdate,
    llmAnalyticsReviewQueuesCreate,
    llmAnalyticsReviewQueuesDestroy,
    llmAnalyticsReviewQueuesList,
    llmAnalyticsReviewQueuesPartialUpdate,
    llmAnalyticsReviewQueuesRetrieve,
} from '../generated/api'
import type {
    LlmAnalyticsReviewQueueItemsListParams,
    LlmAnalyticsReviewQueuesListParams,
    PaginatedReviewQueueItemListApi,
    PaginatedReviewQueueListApi,
    PatchedReviewQueueItemUpdateApi,
    ReviewQueueApi,
    ReviewQueueCreateApi,
    ReviewQueueItemApi,
    ReviewQueueItemCreateApi,
} from '../generated/api.schemas'

function getCurrentProjectId(): string {
    return String(ApiConfig.getCurrentTeamId())
}

export const reviewQueuesApi = {
    listQueues(params?: LlmAnalyticsReviewQueuesListParams): Promise<PaginatedReviewQueueListApi> {
        return llmAnalyticsReviewQueuesList(getCurrentProjectId(), params)
    },

    listQueuePickerOptions(): Promise<PaginatedReviewQueueListApi> {
        return llmAnalyticsReviewQueuesList(getCurrentProjectId(), {
            order_by: 'name',
            limit: 1000,
        })
    },

    createQueue(data: ReviewQueueCreateApi): Promise<ReviewQueueApi> {
        return llmAnalyticsReviewQueuesCreate(getCurrentProjectId(), data)
    },

    getQueue(id: string): Promise<ReviewQueueApi> {
        return llmAnalyticsReviewQueuesRetrieve(getCurrentProjectId(), id)
    },

    updateQueue(id: string, data: ReviewQueueCreateApi): Promise<ReviewQueueApi> {
        return llmAnalyticsReviewQueuesPartialUpdate(getCurrentProjectId(), id, data)
    },

    deleteQueue(id: string): Promise<void> {
        return llmAnalyticsReviewQueuesDestroy(getCurrentProjectId(), id)
    },

    listQueueItems(params?: LlmAnalyticsReviewQueueItemsListParams): Promise<PaginatedReviewQueueItemListApi> {
        return llmAnalyticsReviewQueueItemsList(getCurrentProjectId(), params)
    },

    createQueueItem(data: ReviewQueueItemCreateApi): Promise<ReviewQueueItemApi> {
        return llmAnalyticsReviewQueueItemsCreate(getCurrentProjectId(), data)
    },

    updateQueueItem(id: string, data: PatchedReviewQueueItemUpdateApi): Promise<ReviewQueueItemApi> {
        return llmAnalyticsReviewQueueItemsPartialUpdate(getCurrentProjectId(), id, data)
    },

    deleteQueueItem(id: string): Promise<void> {
        return llmAnalyticsReviewQueueItemsDestroy(getCurrentProjectId(), id)
    },
}
