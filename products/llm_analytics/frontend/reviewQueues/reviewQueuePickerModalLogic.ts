import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { pluralize } from '~/lib/utils'

import type { PaginatedReviewQueueListApi, ReviewQueueApi, ReviewQueueItemApi } from '../generated/api.schemas'
import type { reviewQueuePickerModalLogicType } from './reviewQueuePickerModalLogicType'
import { reviewQueuesApi } from './reviewQueuesApi'
import { formatTraceIdsInput, getApiErrorDetail, parseTraceIdsInput } from './reviewQueueUtils'

export interface ReviewQueuePickerModalProps {
    defaultQueueId?: string | null
    initialTraceIds?: string[]
    mode?: 'add'
    onClose?: () => void
    onSuccess?: (result: { queueId: string; createdQueue: boolean }) => void
    title?: string
    confirmLabel?: string
}

const EMPTY_QUEUE_LIST: PaginatedReviewQueueListApi = {
    count: 0,
    next: null,
    previous: null,
    results: [],
}

export const reviewQueuePickerModalLogic = kea<reviewQueuePickerModalLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'reviewQueues', 'reviewQueuePickerModalLogic']),
    props({} as ReviewQueuePickerModalProps),
    key((props) => `${props.defaultQueueId || 'none'}-${(props.initialTraceIds || []).join(',')}`),

    actions({
        loadQueues: true,
        setSelectedQueueKey: (queueKey: string | null) => ({ queueKey }),
        setTraceIdsInput: (traceIdsInput: string) => ({ traceIdsInput }),
        submit: true,
        submitSuccess: (queueId: string, createdQueue: boolean) => ({ queueId, createdQueue }),
        submitFailure: true,
    }),

    reducers({
        selectedQueueKey: [
            null as string | null,
            {
                setSelectedQueueKey: (_, { queueKey }) => queueKey,
            },
        ],
        traceIdsInput: [
            '',
            {
                setTraceIdsInput: (_, { traceIdsInput }) => traceIdsInput,
            },
        ],
        isSubmitting: [
            false,
            {
                submit: () => true,
                submitSuccess: () => false,
                submitFailure: () => false,
            },
        ],
    }),

    loaders(() => ({
        queues: [
            EMPTY_QUEUE_LIST,
            {
                loadQueues: async () => reviewQueuesApi.listQueuePickerOptions(),
            },
        ],
    })),

    selectors({
        parsedTraceIds: [
            (s) => [s.traceIdsInput],
            (traceIdsInput: string): string[] => parseTraceIdsInput(traceIdsInput),
        ],
        selectedQueueValue: [
            (s) => [s.selectedQueueKey],
            (selectedQueueKey: string | null): string[] | null => (selectedQueueKey ? [selectedQueueKey] : null),
        ],
        selectedQueue: [
            (s) => [s.queues, s.selectedQueueKey],
            (queues: PaginatedReviewQueueListApi, selectedQueueKey: string | null): ReviewQueueApi | null =>
                queues.results.find((queue) => queue.id === selectedQueueKey) ?? null,
        ],
        isCreatingQueue: [
            (s) => [s.selectedQueueKey, s.selectedQueue],
            (selectedQueueKey: string | null, selectedQueue: ReviewQueueApi | null): boolean =>
                !!selectedQueueKey && !selectedQueue,
        ],
    }),

    listeners(({ actions, values, props }) => ({
        loadQueuesSuccess: ({ queues }) => {
            const defaultQueueId = props.defaultQueueId || null
            const hasSelectedQueue = values.selectedQueueKey
                ? queues.results.some((queue) => queue.id === values.selectedQueueKey)
                : false

            if (hasSelectedQueue) {
                return
            }

            if (defaultQueueId && queues.results.some((queue) => queue.id === defaultQueueId)) {
                actions.setSelectedQueueKey(defaultQueueId)
                return
            }

            if (!values.selectedQueueKey && queues.results.length === 1) {
                actions.setSelectedQueueKey(queues.results[0].id)
            }
        },

        submit: async () => {
            const selectedQueueKey = values.selectedQueueKey?.trim() || ''
            const traceIds = values.parsedTraceIds

            if (!selectedQueueKey) {
                actions.submitFailure()
                lemonToast.error('Select a queue or type a new queue name.')
                return
            }

            if (traceIds.length === 0) {
                actions.submitFailure()
                lemonToast.error('Add at least one trace ID.')
                return
            }

            try {
                let queueId = selectedQueueKey
                let queueName = values.selectedQueue?.name || selectedQueueKey
                let createdQueue = false

                if (!values.selectedQueue) {
                    const queue = await reviewQueuesApi.createQueue({ name: selectedQueueKey })
                    queueId = queue.id
                    queueName = queue.name
                    createdQueue = true
                    actions.setSelectedQueueKey(queue.id)
                    actions.loadQueues()
                }

                const results = await Promise.allSettled(
                    traceIds.map((traceId) => reviewQueuesApi.createQueueItem({ queue_id: queueId, trace_id: traceId }))
                )

                const succeeded = results.filter(
                    (result): result is PromiseFulfilledResult<ReviewQueueItemApi> => result.status === 'fulfilled'
                )
                const failed = results.filter((result): result is PromiseRejectedResult => result.status === 'rejected')

                if (succeeded.length === 0) {
                    throw failed[0]?.reason || new Error('Failed to add traces to the queue.')
                }

                if (failed.length > 0) {
                    lemonToast.success(`Added ${succeeded.length} of ${traceIds.length} traces to "${queueName}".`)
                    lemonToast.error(
                        getApiErrorDetail(failed[0].reason) || 'Some traces could not be added to the queue.'
                    )
                } else {
                    lemonToast.success(`Added ${pluralize(succeeded.length, 'trace')} to "${queueName}".`)
                }

                actions.submitSuccess(queueId, createdQueue)
            } catch (error) {
                actions.submitFailure()
                lemonToast.error(getApiErrorDetail(error) || 'Failed to add traces to a review queue.')
            }
        },

        submitSuccess: ({ queueId, createdQueue }) => {
            props.onSuccess?.({ queueId, createdQueue })
            props.onClose?.()
        },
    })),

    afterMount(({ actions, props }) => {
        actions.setTraceIdsInput(formatTraceIdsInput(props.initialTraceIds || []))
        actions.loadQueues()
    }),
])
