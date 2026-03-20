import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { LemonDialog } from '@posthog/lemon-ui'

import { Sorting } from 'lib/lemon-ui/LemonTable'

import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { PaginationManual } from '~/lib/lemon-ui/PaginationControl'
import { tabAwareActionToUrl } from '~/lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from '~/lib/logic/scenes/tabAwareUrlToAction'
import { objectsEqual, pluralize } from '~/lib/utils'
import { urls } from '~/scenes/urls'

import type {
    PaginatedReviewQueueItemListApi,
    PaginatedReviewQueueListApi,
    ReviewQueueApi,
    ReviewQueueItemApi,
} from '../generated/api.schemas'
import type { llmAnalyticsReviewQueuesLogicType } from './llmAnalyticsReviewQueuesLogicType'
import { reviewQueuesApi } from './reviewQueuesApi'
import { getApiErrorDetail } from './reviewQueueUtils'

export const REVIEW_QUEUES_PER_PAGE = 15
export const REVIEW_QUEUE_ITEMS_PER_PAGE = 30

export interface ReviewQueueFilters {
    page: number
    search: string
    order_by: string
}

export interface ReviewQueueItemFilters {
    page: number
    search: string
    order_by: string
}

export type ReviewQueueEditorMode = 'create' | 'rename'

export interface LLMAnalyticsReviewQueuesLogicProps {
    tabId?: string
}

const EMPTY_QUEUE_LIST: PaginatedReviewQueueListApi = {
    count: 0,
    next: null,
    previous: null,
    results: [],
}

const EMPTY_QUEUE_ITEM_LIST: PaginatedReviewQueueItemListApi = {
    count: 0,
    next: null,
    previous: null,
    results: [],
}

const ALLOWED_QUEUE_ORDER_BY_VALUES = new Set([
    'name',
    '-name',
    'updated_at',
    '-updated_at',
    'created_at',
    '-created_at',
])
const ALLOWED_QUEUE_ITEM_ORDER_BY_VALUES = new Set(['created_at', '-created_at', 'updated_at', '-updated_at'])

function findQueueById(queues: PaginatedReviewQueueListApi, queueId: string | null): ReviewQueueApi | null {
    if (!queueId) {
        return null
    }

    return queues.results.find((queue) => queue.id === queueId) ?? null
}

function cleanQueueFilters(values: Record<string, unknown>): ReviewQueueFilters {
    const orderByValue = values.queue_order_by ?? values.order_by
    const orderBy =
        typeof orderByValue === 'string' && ALLOWED_QUEUE_ORDER_BY_VALUES.has(orderByValue) ? orderByValue : 'name'

    return {
        page: parseInt(String(values.queue_page ?? values.page)) || 1,
        search: String(values.queue_search ?? values.search ?? ''),
        order_by: orderBy,
    }
}

function cleanQueueItemFilters(values: Record<string, unknown>): ReviewQueueItemFilters {
    const orderByValue = values.queue_item_order_by ?? values.order_by
    const orderBy =
        typeof orderByValue === 'string' && ALLOWED_QUEUE_ITEM_ORDER_BY_VALUES.has(orderByValue)
            ? orderByValue
            : 'created_at'

    return {
        page: parseInt(String(values.queue_item_page ?? values.page)) || 1,
        search: String(values.queue_item_search ?? values.search ?? ''),
        order_by: orderBy,
    }
}

function cleanSelectedQueueId(values: Record<string, unknown>): string | null {
    return typeof values.queue_id === 'string' && values.queue_id ? values.queue_id : null
}

function getQueueUrlFilters(filters: ReviewQueueFilters): Record<string, unknown> {
    return {
        queue_page: filters.page === 1 ? undefined : filters.page,
        queue_search: filters.search || undefined,
        queue_order_by: filters.order_by === 'name' ? undefined : filters.order_by,
    }
}

function getQueueItemUrlFilters(filters: ReviewQueueItemFilters): Record<string, unknown> {
    return {
        queue_item_page: filters.page === 1 ? undefined : filters.page,
        queue_item_search: filters.search || undefined,
        queue_item_order_by: filters.order_by === 'created_at' ? undefined : filters.order_by,
    }
}

function getQueueUrlState(
    queueFilters: ReviewQueueFilters,
    selectedQueueId: string | null,
    queueItemFilters: ReviewQueueItemFilters
): Record<string, unknown> {
    return {
        ...getQueueUrlFilters(queueFilters),
        queue_id: selectedQueueId || undefined,
        ...getQueueItemUrlFilters(queueItemFilters),
        human_reviews_tab: undefined,
    }
}

export const llmAnalyticsReviewQueuesLogic = kea<llmAnalyticsReviewQueuesLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'reviewQueues', 'llmAnalyticsReviewQueuesLogic']),
    props({} as LLMAnalyticsReviewQueuesLogicProps),
    key((props) => props.tabId ?? 'default'),

    actions({
        setQueueFilters: (filters: Partial<ReviewQueueFilters>, merge: boolean = true, debounce: boolean = true) => ({
            filters,
            merge,
            debounce,
        }),
        loadQueues: (debounce: boolean = true) => ({ debounce }),
        selectQueue: (queueId: string | null) => ({ queueId }),
        setSelectedQueue: (queue: ReviewQueueApi | null) => ({ queue }),
        setQueueItemFilters: (
            filters: Partial<ReviewQueueItemFilters>,
            merge: boolean = true,
            debounce: boolean = true
        ) => ({
            filters,
            merge,
            debounce,
        }),
        loadQueueItems: (debounce: boolean = true) => ({ debounce }),
        openQueueEditor: (mode: ReviewQueueEditorMode, queue: ReviewQueueApi | null = null) => ({ mode, queue }),
        closeQueueEditor: true,
        setQueueEditorName: (name: string) => ({ name }),
        submitQueueEditor: true,
        submitQueueEditorSuccess: (queue: ReviewQueueApi, mode: ReviewQueueEditorMode) => ({ queue, mode }),
        submitQueueEditorFailure: true,
        requestDeleteQueue: (queue: ReviewQueueApi) => ({ queue }),
        deleteQueue: (queue: ReviewQueueApi) => ({ queue }),
        requestRemoveQueueItem: (item: ReviewQueueItemApi) => ({ item }),
        removeQueueItem: (item: ReviewQueueItemApi) => ({ item }),
    }),

    reducers({
        rawQueueFilters: [
            null as Partial<ReviewQueueFilters> | null,
            {
                setQueueFilters: (state, { filters, merge }) =>
                    cleanQueueFilters({
                        ...(merge ? state || {} : {}),
                        ...filters,
                        ...('page' in filters ? {} : { queue_page: 1 }),
                    }),
            },
        ],
        selectedQueueId: [
            null as string | null,
            {
                selectQueue: (_, { queueId }) => queueId,
            },
        ],
        selectedQueue: [
            null as ReviewQueueApi | null,
            {
                selectQueue: (state, { queueId }) => (state?.id === queueId ? state : null),
                setSelectedQueue: (_, { queue }) => queue,
                submitQueueEditorSuccess: (state, { queue }) => (state?.id === queue.id ? queue : state),
                deleteQueue: (state, { queue }) => (state?.id === queue.id ? null : state),
            },
        ],
        rawQueueItemFilters: [
            null as Partial<ReviewQueueItemFilters> | null,
            {
                setQueueItemFilters: (state, { filters, merge }) =>
                    cleanQueueItemFilters({
                        ...(merge ? state || {} : {}),
                        ...filters,
                        ...('page' in filters ? {} : { queue_item_page: 1 }),
                    }),
            },
        ],
        queueEditorMode: [
            null as ReviewQueueEditorMode | null,
            {
                openQueueEditor: (_, { mode }) => mode,
                closeQueueEditor: () => null,
                submitQueueEditorSuccess: () => null,
            },
        ],
        editingQueue: [
            null as ReviewQueueApi | null,
            {
                openQueueEditor: (_, { queue }) => queue,
                closeQueueEditor: () => null,
                submitQueueEditorSuccess: () => null,
            },
        ],
        queueEditorName: [
            '',
            {
                openQueueEditor: (_, { queue }) => queue?.name || '',
                closeQueueEditor: () => '',
                setQueueEditorName: (_, { name }) => name,
                submitQueueEditorSuccess: () => '',
            },
        ],
        queueEditorSubmitting: [
            false,
            {
                submitQueueEditor: () => true,
                submitQueueEditorSuccess: () => false,
                submitQueueEditorFailure: () => false,
                closeQueueEditor: () => false,
            },
        ],
        hasLoadedQueuesOnce: [
            false,
            {
                loadQueuesSuccess: () => true,
                loadQueuesFailure: () => true,
            },
        ],
    }),

    loaders(({ values }) => ({
        queues: [
            EMPTY_QUEUE_LIST,
            {
                loadQueues: async ({ debounce }, breakpoint) => {
                    if (debounce && values.queues.results.length > 0) {
                        await breakpoint(300)
                    }

                    const { queueFilters } = values

                    return reviewQueuesApi.listQueues({
                        search: queueFilters.search || undefined,
                        order_by: queueFilters.order_by,
                        offset: Math.max(0, (queueFilters.page - 1) * REVIEW_QUEUES_PER_PAGE),
                        limit: REVIEW_QUEUES_PER_PAGE,
                    })
                },
            },
        ],
        queueItems: [
            EMPTY_QUEUE_ITEM_LIST,
            {
                loadQueueItems: async ({ debounce }, breakpoint) => {
                    const { selectedQueueId, queueItemFilters, queueItems } = values

                    if (!selectedQueueId) {
                        return EMPTY_QUEUE_ITEM_LIST
                    }

                    if (debounce && queueItems.results.length > 0) {
                        await breakpoint(300)
                    }

                    return reviewQueuesApi.listQueueItems({
                        queue_id: selectedQueueId,
                        search: queueItemFilters.search || undefined,
                        order_by: queueItemFilters.order_by,
                        offset: Math.max(0, (queueItemFilters.page - 1) * REVIEW_QUEUE_ITEMS_PER_PAGE),
                        limit: REVIEW_QUEUE_ITEMS_PER_PAGE,
                    })
                },
            },
        ],
    })),

    selectors({
        queueFilters: [
            (s) => [s.rawQueueFilters],
            (rawQueueFilters: Partial<ReviewQueueFilters> | null): ReviewQueueFilters =>
                cleanQueueFilters(rawQueueFilters || {}),
        ],
        queueItemFilters: [
            (s) => [s.rawQueueItemFilters],
            (rawQueueItemFilters: Partial<ReviewQueueItemFilters> | null): ReviewQueueItemFilters =>
                cleanQueueItemFilters(rawQueueItemFilters || {}),
        ],
        activeQueue: [
            (s) => [s.queues, s.selectedQueueId, s.selectedQueue],
            (
                queues: PaginatedReviewQueueListApi,
                selectedQueueId: string | null,
                selectedQueue: ReviewQueueApi | null
            ): ReviewQueueApi | null =>
                findQueueById(queues, selectedQueueId) ??
                (selectedQueue?.id === selectedQueueId ? selectedQueue : null),
        ],
        visibleQueues: [
            (s) => [s.queues, s.activeQueue],
            (queues: PaginatedReviewQueueListApi, activeQueue: ReviewQueueApi | null): ReviewQueueApi[] =>
                activeQueue && !queues.results.some((queue) => queue.id === activeQueue.id)
                    ? [activeQueue, ...queues.results]
                    : queues.results,
        ],
        queueSorting: [
            (s) => [s.queueFilters],
            (queueFilters: ReviewQueueFilters): Sorting | null =>
                queueFilters.order_by.startsWith('-')
                    ? { columnKey: queueFilters.order_by.slice(1), order: -1 }
                    : { columnKey: queueFilters.order_by, order: 1 },
        ],
        queuePagination: [
            (s) => [s.queueFilters, s.queues],
            (queueFilters: ReviewQueueFilters, queues: PaginatedReviewQueueListApi): PaginationManual => ({
                controlled: true,
                pageSize: REVIEW_QUEUES_PER_PAGE,
                currentPage: queueFilters.page,
                entryCount: queues.count,
            }),
        ],
        queueItemSorting: [
            (s) => [s.queueItemFilters],
            (queueItemFilters: ReviewQueueItemFilters): Sorting | null =>
                queueItemFilters.order_by.startsWith('-')
                    ? { columnKey: queueItemFilters.order_by.slice(1), order: -1 }
                    : { columnKey: queueItemFilters.order_by, order: 1 },
        ],
        queueItemPagination: [
            (s) => [s.queueItemFilters, s.queueItems],
            (
                queueItemFilters: ReviewQueueItemFilters,
                queueItems: PaginatedReviewQueueItemListApi
            ): PaginationManual => ({
                controlled: true,
                pageSize: REVIEW_QUEUE_ITEMS_PER_PAGE,
                currentPage: queueItemFilters.page,
                entryCount: queueItems.count,
            }),
        ],
        queueCountLabel: [
            (s) => [s.queues, s.queueFilters, s.queuesLoading],
            (queues: PaginatedReviewQueueListApi, queueFilters: ReviewQueueFilters, queuesLoading: boolean): string => {
                if (queuesLoading) {
                    return ''
                }

                const start = (queueFilters.page - 1) * REVIEW_QUEUES_PER_PAGE + 1
                const end = Math.min(queueFilters.page * REVIEW_QUEUES_PER_PAGE, queues.count)

                return queues.count === 0 ? '0 queues' : `${start}-${end} of ${pluralize(queues.count, 'queue')}`
            },
        ],
        queueItemCountLabel: [
            (s) => [s.queueItems, s.queueItemFilters, s.queueItemsLoading],
            (
                queueItems: PaginatedReviewQueueItemListApi,
                queueItemFilters: ReviewQueueItemFilters,
                queueItemsLoading: boolean
            ): string => {
                if (queueItemsLoading) {
                    return ''
                }

                const start = (queueItemFilters.page - 1) * REVIEW_QUEUE_ITEMS_PER_PAGE + 1
                const end = Math.min(queueItemFilters.page * REVIEW_QUEUE_ITEMS_PER_PAGE, queueItems.count)

                return queueItems.count === 0
                    ? '0 pending traces'
                    : `${start}-${end} of ${pluralize(queueItems.count, 'pending trace')}`
            },
        ],
        queueEditorTitle: [
            (s) => [s.queueEditorMode],
            (queueEditorMode): string => (queueEditorMode === 'rename' ? 'Rename queue' : 'New queue'),
        ],
    }),

    listeners(({ actions, asyncActions, values, selectors }) => ({
        setQueueFilters: async ({ debounce }, _, __, previousState) => {
            const oldFilters = selectors.queueFilters(previousState)

            if (!objectsEqual(oldFilters, values.queueFilters)) {
                await asyncActions.loadQueues(debounce)
            }
        },

        setQueueItemFilters: async ({ debounce }, _, __, previousState) => {
            const oldFilters = selectors.queueItemFilters(previousState)

            if (!objectsEqual(oldFilters, values.queueItemFilters) && values.selectedQueueId) {
                await asyncActions.loadQueueItems(debounce)
            }
        },

        selectQueue: async ({ queueId }, _, __, previousState) => {
            const oldSelectedQueueId = previousState?.selectedQueueId

            if (oldSelectedQueueId === queueId) {
                return
            }

            if (!queueId) {
                actions.setSelectedQueue(null)
                await asyncActions.loadQueueItems(false)
                return
            }

            const selectedQueue = findQueueById(values.queues, queueId)

            if (selectedQueue) {
                actions.setSelectedQueue(selectedQueue)
            } else {
                try {
                    actions.setSelectedQueue(await reviewQueuesApi.getQueue(queueId))
                } catch {
                    actions.setSelectedQueue(null)
                }
            }

            if (values.queueItemFilters.page !== 1) {
                actions.setQueueItemFilters({ page: 1 }, true, false)
            } else {
                await asyncActions.loadQueueItems(false)
            }
        },

        loadQueuesSuccess: async ({ queues }) => {
            const urlSelectedQueueId = cleanSelectedQueueId(router.values.searchParams)
            const targetQueueId = values.selectedQueueId ?? urlSelectedQueueId

            if (queues.results.length === 0) {
                if (targetQueueId) {
                    actions.selectQueue(null)
                }
                return
            }

            if (targetQueueId && values.selectedQueueId !== targetQueueId) {
                actions.selectQueue(targetQueueId)
                return
            }

            if (!targetQueueId) {
                actions.selectQueue(queues.results[0].id)
                return
            }

            const selectedQueue = findQueueById(queues, targetQueueId)

            if (selectedQueue) {
                actions.setSelectedQueue(selectedQueue)
                return
            }

            if (values.selectedQueue?.id === targetQueueId) {
                return
            }

            try {
                actions.setSelectedQueue(await reviewQueuesApi.getQueue(targetQueueId))
            } catch {
                actions.setSelectedQueue(null)
            }
        },

        submitQueueEditor: async () => {
            const trimmedName = values.queueEditorName.trim()

            if (!trimmedName) {
                actions.submitQueueEditorFailure()
                lemonToast.error('Queue name is required.')
                return
            }

            const mode = values.queueEditorMode
            if (!mode) {
                actions.submitQueueEditorFailure()
                return
            }

            try {
                const queue =
                    mode === 'create'
                        ? await reviewQueuesApi.createQueue({ name: trimmedName })
                        : values.editingQueue
                          ? await reviewQueuesApi.updateQueue(values.editingQueue.id, { name: trimmedName })
                          : null

                if (!queue) {
                    throw new Error('Queue not found.')
                }

                actions.submitQueueEditorSuccess(queue, mode)

                if (mode === 'create') {
                    actions.setQueueFilters({ search: '', page: 1 }, true, false)
                    actions.selectQueue(queue.id)
                    lemonToast.success(`Created review queue "${queue.name}".`)
                } else {
                    lemonToast.success(`Renamed review queue to "${queue.name}".`)
                }

                await asyncActions.loadQueues(false)
            } catch (error) {
                actions.submitQueueEditorFailure()
                lemonToast.error(getApiErrorDetail(error) || 'Failed to save review queue.')
            }
        },

        requestDeleteQueue: ({ queue }) => {
            LemonDialog.open({
                title: `Delete "${queue.name}"?`,
                description: 'This removes the queue and any pending traces assigned to it.',
                primaryButton: {
                    children: 'Delete queue',
                    status: 'danger',
                    onClick: () => actions.deleteQueue(queue),
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        },

        deleteQueue: async ({ queue }) => {
            try {
                await reviewQueuesApi.deleteQueue(queue.id)
                lemonToast.success(`Deleted review queue "${queue.name}".`)

                if (values.selectedQueueId === queue.id) {
                    actions.selectQueue(null)
                }

                await asyncActions.loadQueues(false)
            } catch (error) {
                lemonToast.error(getApiErrorDetail(error) || 'Failed to delete review queue.')
            }
        },

        requestRemoveQueueItem: ({ item }) => {
            LemonDialog.open({
                title: `Remove ${item.trace_id} from "${item.queue_name}"?`,
                description: 'The trace will leave this review queue until it is added again.',
                primaryButton: {
                    children: 'Remove trace',
                    status: 'danger',
                    onClick: () => actions.removeQueueItem(item),
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        },

        removeQueueItem: async ({ item }) => {
            try {
                await reviewQueuesApi.deleteQueueItem(item.id)
                lemonToast.success(`Removed ${item.trace_id} from "${item.queue_name}".`)
                await asyncActions.loadQueueItems(false)
                await asyncActions.loadQueues(false)
            } catch (error) {
                lemonToast.error(getApiErrorDetail(error) || 'Failed to remove trace from the queue.')
            }
        },
    })),

    tabAwareActionToUrl(({ values }) => ({
        setQueueFilters: () => {
            const nextValues = getQueueUrlState(values.queueFilters, values.selectedQueueId, values.queueItemFilters)
            const urlValues = getQueueUrlState(
                cleanQueueFilters(router.values.searchParams),
                cleanSelectedQueueId(router.values.searchParams),
                cleanQueueItemFilters(router.values.searchParams)
            )

            if (!objectsEqual(nextValues, urlValues)) {
                return [urls.llmAnalyticsReviews(), nextValues, {}, { replace: true }]
            }
        },
        selectQueue: () => {
            const nextValues = getQueueUrlState(values.queueFilters, values.selectedQueueId, values.queueItemFilters)
            const urlValues = getQueueUrlState(
                cleanQueueFilters(router.values.searchParams),
                cleanSelectedQueueId(router.values.searchParams),
                cleanQueueItemFilters(router.values.searchParams)
            )

            if (!objectsEqual(nextValues, urlValues)) {
                return [urls.llmAnalyticsReviews(), nextValues, {}, { replace: true }]
            }
        },
        setQueueItemFilters: () => {
            const nextValues = getQueueUrlState(values.queueFilters, values.selectedQueueId, values.queueItemFilters)
            const urlValues = getQueueUrlState(
                cleanQueueFilters(router.values.searchParams),
                cleanSelectedQueueId(router.values.searchParams),
                cleanQueueItemFilters(router.values.searchParams)
            )

            if (!objectsEqual(nextValues, urlValues)) {
                return [urls.llmAnalyticsReviews(), nextValues, {}, { replace: true }]
            }
        },
    })),

    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.llmAnalyticsReviews()]: (_, searchParams, __, { method }) => {
            if (searchParams.human_reviews_tab === 'reviews' || searchParams.human_reviews_tab === 'scorers') {
                return
            }

            const newQueueFilters = cleanQueueFilters(searchParams)
            const newQueueItemFilters = cleanQueueItemFilters(searchParams)
            const newSelectedQueueId = cleanSelectedQueueId(searchParams)

            const hasQueueFilterChanges = !objectsEqual(values.queueFilters, newQueueFilters)
            const hasQueueItemFilterChanges = !objectsEqual(values.queueItemFilters, newQueueItemFilters)
            const hasSelectedQueueChange = values.selectedQueueId !== newSelectedQueueId

            if (hasQueueFilterChanges) {
                actions.setQueueFilters(newQueueFilters, false)
            }

            if (hasQueueItemFilterChanges) {
                actions.setQueueItemFilters(newQueueItemFilters, false)
            }

            if (hasSelectedQueueChange) {
                actions.selectQueue(newSelectedQueueId)
            } else if (!hasQueueFilterChanges && !hasQueueItemFilterChanges && method !== 'REPLACE') {
                actions.loadQueues(false)

                if (values.selectedQueueId) {
                    actions.loadQueueItems(false)
                }
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadQueues(false)
    }),
])
