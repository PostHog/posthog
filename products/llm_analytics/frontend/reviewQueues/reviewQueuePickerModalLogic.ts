import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'

import type { PaginatedReviewQueueListApi, ReviewQueueApi } from '../generated/api.schemas'
import type { reviewQueuePickerModalLogicType } from './reviewQueuePickerModalLogicType'
import { reviewQueuesApi } from './reviewQueuesApi'
import { getApiErrorDetail } from './reviewQueueUtils'

export interface ReviewQueuePickerModalProps {
    defaultQueueId?: string | null
    queueItemId?: string | null
    traceId: string
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
    key((props) => `${props.traceId}-${props.queueItemId || 'new'}-${props.defaultQueueId || 'none'}`),

    actions({
        loadQueues: true,
        setSelectedQueueKey: (queueKey: string | null) => ({ queueKey }),
        submit: (queueKey: string | null = null) => ({ queueKey }),
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

        submit: async ({ queueKey }) => {
            const selectedQueueKey = queueKey?.trim() || values.selectedQueueKey?.trim() || ''

            if (!selectedQueueKey) {
                actions.submitFailure()
                lemonToast.error('Select a queue or type a new queue name.')
                return
            }

            try {
                const selectedQueue = values.queues.results.find((queue) => queue.id === selectedQueueKey) ?? null
                let queueId = selectedQueueKey
                let queueName = selectedQueue?.name || selectedQueueKey
                let createdQueue = false

                if (!selectedQueue) {
                    const queue = await reviewQueuesApi.createQueue({ name: selectedQueueKey })
                    queueId = queue.id
                    queueName = queue.name
                    createdQueue = true
                    actions.setSelectedQueueKey(queue.id)
                    actions.loadQueues()
                }

                if (props.queueItemId) {
                    await reviewQueuesApi.updateQueueItem(props.queueItemId, { queue_id: queueId })
                    lemonToast.success(`Moved to "${queueName}".`)
                } else {
                    await reviewQueuesApi.createQueueItem({ queue_id: queueId, trace_id: props.traceId })
                    lemonToast.success(`Added to "${queueName}".`)
                }

                actions.submitSuccess(queueId, createdQueue)
            } catch (error) {
                actions.submitFailure()
                lemonToast.error(getApiErrorDetail(error) || 'Failed to update the trace queue.')
            }
        },

        submitSuccess: ({ queueId, createdQueue }) => {
            props.onSuccess?.({ queueId, createdQueue })
            props.onClose?.()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadQueues()
    }),
])
