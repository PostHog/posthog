import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { traceReviewLogicType } from './traceReviewLogicType'

export interface TraceReview {
    id: string
    trace_id: string
    reviewed_by: {
        id: number
        first_name: string
        email: string
    }
    reviewed_at: string
    created_at: string
    updated_at: string
    team: number
}

export interface TraceReviewLogicProps {
    traceId: string
}

export const traceReviewLogic = kea<traceReviewLogicType>([
    path(['scenes', 'llm-analytics', 'traceReviewLogic']),
    props({} as TraceReviewLogicProps),

    actions({
        markTraceAsReviewed: true,
        unmarkTraceAsReviewed: true,
        setTraceReview: (traceReview: TraceReview | null) => ({ traceReview }),
    }),

    loaders(({ props }) => ({
        traceReview: [
            null as TraceReview | null,
            {
                loadTraceReview: async () => {
                    try {
                        const response = await api.get(
                            `api/environments/${window.POSTHOG_APP_CONTEXT?.current_team?.id}/trace_reviews/by-trace/${props.traceId}/`
                        )
                        return response
                    } catch (error: any) {
                        if (error.status === 404) {
                            return null
                        }
                        throw error
                    }
                },
                markTraceAsReviewed: async () => {
                    try {
                        const response = await api.create(
                            `api/environments/${window.POSTHOG_APP_CONTEXT?.current_team?.id}/trace_reviews/`,
                            {
                                trace_id: props.traceId,
                            }
                        )
                        lemonToast.success('Trace marked as reviewed')
                        return response
                    } catch (error: any) {
                        if (error.status === 409) {
                            lemonToast.error('This trace has already been reviewed')
                            throw error
                        } else {
                            lemonToast.error('Failed to mark trace as reviewed')
                            throw error
                        }
                    }
                },
                unmarkTraceAsReviewed: async () => {
                    try {
                        await api.delete(
                            `api/environments/${window.POSTHOG_APP_CONTEXT?.current_team?.id}/trace_reviews/by-trace/${props.traceId}/`
                        )
                        lemonToast.success('Review status removed')
                        return null
                    } catch (error: any) {
                        if (error.status === 404) {
                            lemonToast.error('Review not found for this trace')
                        } else {
                            lemonToast.error('Failed to remove review status')
                        }
                        throw error
                    }
                },
            },
        ],
    })),

    reducers({
        traceReview: {
            setTraceReview: (_, { traceReview }) => traceReview,
        },
    }),

    selectors({
        isReviewed: [(s) => [s.traceReview], (traceReview): boolean => !!traceReview],
    }),

    listeners(() => ({
        markTraceAsReviewed: () => {
            // The loader will handle the API call and update the state
        },
        unmarkTraceAsReviewed: () => {
            // The loader will handle the API call and update the state
        },
    })),

    afterMount(({ actions }) => {
        actions.loadTraceReview()
    }),
])
