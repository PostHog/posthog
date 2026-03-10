import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { traceReviewModalLogicType } from './traceReviewModalLogicType'
import { traceReviewsApi } from './traceReviewsApi'
import type { TraceReview, TraceReviewFormScoreMode, TraceReviewScoreLabel, TraceReviewUpsertPayload } from './types'

export interface TraceReviewModalLogicProps {
    traceId: string
}

function parseErrorMessage(error: unknown): string {
    if (error instanceof Error && error.message) {
        return error.message
    }

    return 'Something went wrong.'
}

export const traceReviewModalLogic = kea<traceReviewModalLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'traceReviews', 'traceReviewModalLogic']),
    props({} as TraceReviewModalLogicProps),
    key((props: TraceReviewModalLogicProps) => props.traceId),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        openModal: true,
        closeModal: true,
        resetForm: true,
        populateForm: (review: TraceReview | null) => ({ review }),
        setScoreMode: (scoreMode: TraceReviewFormScoreMode) => ({ scoreMode }),
        setScoreLabel: (scoreLabel: TraceReviewScoreLabel | null) => ({ scoreLabel }),
        setScoreNumeric: (scoreNumeric: string) => ({ scoreNumeric }),
        setComment: (comment: string) => ({ comment }),
        loadCurrentReview: true,
        loadCurrentReviewSuccess: (review: TraceReview | null) => ({ review }),
        loadCurrentReviewFailure: true,
        saveCurrentReview: true,
        saveCurrentReviewSuccess: (review: TraceReview) => ({ review }),
        saveCurrentReviewFailure: true,
        removeCurrentReview: true,
        removeCurrentReviewSuccess: true,
        removeCurrentReviewFailure: true,
    }),

    reducers({
        isOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],

        currentReview: [
            null as TraceReview | null,
            {
                loadCurrentReviewSuccess: (_, { review }) => review,
                loadCurrentReviewFailure: () => null,
                saveCurrentReviewSuccess: (_, { review }) => review,
                removeCurrentReviewSuccess: () => null,
            },
        ],

        currentReviewLoading: [
            false,
            {
                loadCurrentReview: () => true,
                loadCurrentReviewSuccess: () => false,
                loadCurrentReviewFailure: () => false,
                closeModal: () => false,
            },
        ],

        saving: [
            false,
            {
                saveCurrentReview: () => true,
                saveCurrentReviewSuccess: () => false,
                saveCurrentReviewFailure: () => false,
                closeModal: () => false,
            },
        ],

        removing: [
            false,
            {
                removeCurrentReview: () => true,
                removeCurrentReviewSuccess: () => false,
                removeCurrentReviewFailure: () => false,
                closeModal: () => false,
            },
        ],

        scoreMode: [
            'none' as TraceReviewFormScoreMode,
            {
                resetForm: () => 'none',
                setScoreMode: (_, { scoreMode }) => scoreMode,
                populateForm: (_, { review }) => review?.score_kind ?? 'none',
                removeCurrentReviewSuccess: () => 'none',
            },
        ],

        scoreLabel: [
            null as TraceReviewScoreLabel | null,
            {
                resetForm: () => null,
                setScoreLabel: (_, { scoreLabel }) => scoreLabel,
                setScoreMode: (state, { scoreMode }) => (scoreMode === 'label' ? state : null),
                populateForm: (_, { review }) => review?.score_label ?? null,
                removeCurrentReviewSuccess: () => null,
            },
        ],

        scoreNumeric: [
            '',
            {
                resetForm: () => '',
                setScoreNumeric: (_, { scoreNumeric }) => scoreNumeric,
                setScoreMode: (state, { scoreMode }) => (scoreMode === 'numeric' ? state : ''),
                populateForm: (_, { review }) => review?.score_numeric ?? '',
                removeCurrentReviewSuccess: () => '',
            },
        ],

        comment: [
            '',
            {
                resetForm: () => '',
                setComment: (_, { comment }) => comment,
                populateForm: (_, { review }) => review?.comment ?? '',
                removeCurrentReviewSuccess: () => '',
            },
        ],
    }),

    selectors({
        isFormValid: [
            (s) => [s.scoreMode, s.scoreLabel, s.scoreNumeric],
            (scoreMode, scoreLabel, scoreNumeric): boolean => {
                if (scoreMode === 'label') {
                    return scoreLabel !== null
                }

                if (scoreMode === 'numeric') {
                    return scoreNumeric.trim().length > 0
                }

                return true
            },
        ],

        isBusy: [
            (s) => [s.currentReviewLoading, s.saving, s.removing],
            (currentReviewLoading, saving, removing): boolean => currentReviewLoading || saving || removing,
        ],

        canSave: [(s) => [s.isFormValid, s.isBusy], (isFormValid, isBusy): boolean => isFormValid && !isBusy],

        submitPayload: [
            (s) => [s.scoreMode, s.scoreLabel, s.scoreNumeric, s.comment, (_, props) => props.traceId],
            (scoreMode, scoreLabel, scoreNumeric, comment, traceId): TraceReviewUpsertPayload => ({
                trace_id: traceId,
                score_kind: scoreMode === 'none' ? null : scoreMode,
                score_label: scoreMode === 'label' ? scoreLabel : null,
                score_numeric: scoreMode === 'numeric' ? scoreNumeric.trim() || null : null,
                comment: comment.trim() || null,
            }),
        ],
    }),

    listeners(({ actions, values, props }) => ({
        openModal: async () => {
            actions.resetForm()
            actions.loadCurrentReview()
        },

        loadCurrentReview: async () => {
            if (!values.currentTeamId) {
                actions.loadCurrentReviewFailure()
                return
            }

            try {
                const review = await traceReviewsApi.getByTraceId(props.traceId, values.currentTeamId)
                actions.loadCurrentReviewSuccess(review)
                actions.populateForm(review)
            } catch {
                lemonToast.error('Failed to load the current trace review.')
                actions.loadCurrentReviewFailure()
            }
        },

        saveCurrentReview: async () => {
            if (!values.currentTeamId || !values.isFormValid) {
                actions.saveCurrentReviewFailure()
                return
            }

            try {
                const review = await traceReviewsApi.save(
                    values.submitPayload,
                    values.currentReview,
                    values.currentTeamId
                )
                actions.saveCurrentReviewSuccess(review)
                actions.populateForm(review)
                lemonToast.success('Trace review saved.')
                actions.closeModal()
            } catch (error) {
                lemonToast.error(`Failed to save trace review. ${parseErrorMessage(error)}`)
                actions.saveCurrentReviewFailure()
            }
        },

        removeCurrentReview: async () => {
            if (!values.currentTeamId || !values.currentReview) {
                actions.removeCurrentReviewFailure()
                return
            }

            try {
                await traceReviewsApi.delete(values.currentReview.id, values.currentTeamId)
                actions.removeCurrentReviewSuccess()
                lemonToast.info('Trace review removed.')
                actions.closeModal()
            } catch (error) {
                lemonToast.error(`Failed to remove trace review. ${parseErrorMessage(error)}`)
                actions.removeCurrentReviewFailure()
            }
        },
    })),
])
