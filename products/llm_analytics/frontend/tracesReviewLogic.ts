import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'

import type { tracesReviewLogicType } from './tracesReviewLogicType'

export interface TraceReviewData {
    id: string
    reviewed_by: {
        id: number
        email: string
        first_name: string
    }
    reviewed_at: string
}

export interface TracesReviewLogicProps {}

export const tracesReviewLogic = kea<tracesReviewLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'tracesReviewLogic']),

    actions({
        loadBatchReviewStatuses: (traceIds: string[]) => ({ traceIds }),
        setBatchReviewStatuses: (statuses: Record<string, TraceReviewData>) => ({ statuses }),
        clearReviewStatus: (traceId: string) => ({ traceId }),
        setReviewStatus: (traceId: string, reviewData: TraceReviewData) => ({ traceId, reviewData }),
    }),

    reducers({
        batchReviewStatuses: [
            {} as Record<string, TraceReviewData>,
            {
                setBatchReviewStatuses: (state, { statuses }) => ({
                    ...state,
                    ...statuses,
                }),
                clearReviewStatus: (state, { traceId }) => {
                    const newState = { ...state }
                    delete newState[traceId]
                    return newState
                },
                setReviewStatus: (state, { traceId, reviewData }) => ({
                    ...state,
                    [traceId]: reviewData,
                }),
            },
        ],
        isLoading: [
            false,
            {
                loadBatchReviewStatuses: () => true,
                setBatchReviewStatuses: () => false,
            },
        ],
    }),

    selectors({
        getReviewStatus: [
            (s) => [s.batchReviewStatuses],
            (reviewStatuses) => (traceId: string) => reviewStatuses[traceId] || null,
        ],
        isTraceReviewed: [
            (s) => [s.batchReviewStatuses],
            (reviewStatuses) => (traceId: string) => !!reviewStatuses[traceId],
        ],
    }),

    listeners(({ actions }) => ({
        loadBatchReviewStatuses: async ({ traceIds }) => {
            if (traceIds.length === 0) {
                actions.setBatchReviewStatuses({})
                return
            }

            try {
                const response = await api.create(
                    `api/environments/${window.POSTHOG_APP_CONTEXT?.current_team?.id}/trace_reviews/batch-status/`,
                    traceIds
                )
                actions.setBatchReviewStatuses(response)
            } catch (error) {
                console.error('Failed to load batch review status:', error)
                actions.setBatchReviewStatuses({})
            }
        },
    })),
])
