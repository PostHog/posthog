import { ApiConfig } from '~/lib/api'

import {
    llmAnalyticsReviewQueueItemsCreate,
    llmAnalyticsReviewQueueItemsDestroy,
    llmAnalyticsReviewQueueItemsList,
    llmAnalyticsReviewQueuesCreate,
    llmAnalyticsReviewQueuesDestroy,
    llmAnalyticsReviewQueuesList,
    llmAnalyticsReviewQueuesPartialUpdate,
} from '../generated/api'
import type {
    LlmAnalyticsReviewQueueItemsListParams,
    LlmAnalyticsReviewQueuesListParams,
    PaginatedReviewQueueItemListApi,
    PaginatedReviewQueueListApi,
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

    deleteQueueItem(id: string): Promise<void> {
        return llmAnalyticsReviewQueueItemsDestroy(getCurrentProjectId(), id)
    },
}
