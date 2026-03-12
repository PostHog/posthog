import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { llmAnalyticsScoreDefinitionsList } from '../generated/api'
import type { ScoreDefinitionApi } from '../generated/api.schemas'
import type { traceReviewModalLogicType } from './traceReviewModalLogicType'
import { traceReviewsApi } from './traceReviewsApi'
import { traceReviewsLazyLoaderLogic } from './traceReviewsLazyLoaderLogic'
import type { TraceReview, TraceReviewFormScoreValue, TraceReviewUpsertPayload } from './types'
import { getCategoricalConfig } from './utils'

export interface TraceReviewModalLogicProps {
    traceId: string
}

function parseErrorMessage(error: unknown): string {
    if (error instanceof Error && error.message) {
        return error.message
    }

    return 'Something went wrong.'
}

function loadActiveScoreDefinitions(teamId: number): Promise<ScoreDefinitionApi[]> {
    return llmAnalyticsScoreDefinitionsList(String(teamId), {
        archived: false,
        order_by: 'name',
        limit: 1000,
    }).then((response) => response.results)
}

function getCategoricalSelections(value: TraceReviewFormScoreValue | undefined): string[] {
    if (Array.isArray(value)) {
        return value
    }

    if (typeof value === 'string' && value) {
        return [value]
    }

    return []
}

function isCategoricalSelectionValid(
    definition: ScoreDefinitionApi,
    value: TraceReviewFormScoreValue | undefined
): boolean {
    const selections = getCategoricalSelections(value)

    if (selections.length === 0) {
        return true
    }

    const config = getCategoricalConfig(definition.config)

    if ((config.selection_mode || 'single') === 'single') {
        return selections.length === 1
    }

    const minimumSelections = config.min_selections ?? null
    const maximumSelections = config.max_selections ?? null

    if (minimumSelections !== null && selections.length < minimumSelections) {
        return false
    }

    if (maximumSelections !== null && selections.length > maximumSelections) {
        return false
    }

    return true
}

export const traceReviewModalLogic = kea<traceReviewModalLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'traceReviews', 'traceReviewModalLogic']),
    props({} as TraceReviewModalLogicProps),
    key((props: TraceReviewModalLogicProps) => props.traceId),

    connect({
        values: [teamLogic, ['currentTeamId']],
        actions: [traceReviewsLazyLoaderLogic, ['setTraceReview as cacheTraceReview', 'setTraceAsUnreviewed']],
    }),

    actions({
        openModal: true,
        closeModal: true,
        resetForm: true,
        populateForm: (review: TraceReview | null) => ({ review }),
        setScoreValue: (definitionId: string, value: TraceReviewFormScoreValue) => ({ definitionId, value }),
        setComment: (comment: string) => ({ comment }),
        loadModalData: true,
        loadModalDataSuccess: (review: TraceReview | null, definitions: ScoreDefinitionApi[]) => ({
            review,
            definitions,
        }),
        loadModalDataFailure: true,
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
                loadModalDataSuccess: (_, { review }) => review,
                loadModalDataFailure: () => null,
                saveCurrentReviewSuccess: (_, { review }) => review,
                removeCurrentReviewSuccess: () => null,
            },
        ],

        activeDefinitions: [
            [] as ScoreDefinitionApi[],
            {
                loadModalDataSuccess: (_, { definitions }) => definitions,
                closeModal: (state) => state,
            },
        ],

        modalDataLoading: [
            false,
            {
                loadModalData: () => true,
                loadModalDataSuccess: () => false,
                loadModalDataFailure: () => false,
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

        scoreValues: [
            {} as Record<string, TraceReviewFormScoreValue>,
            {
                resetForm: () => ({}),
                setScoreValue: (state, { definitionId, value }) => ({
                    ...state,
                    [definitionId]: value,
                }),
                populateForm: (_, { review }) =>
                    Object.fromEntries(
                        (review?.scores || []).map((score) => [
                            score.definition_id,
                            score.definition_kind === 'categorical'
                                ? score.categorical_values
                                : score.definition_kind === 'numeric'
                                  ? score.numeric_value
                                  : score.boolean_value,
                        ])
                    ),
                removeCurrentReviewSuccess: () => ({}),
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
            (s) => [s.activeDefinitions, s.scoreValues],
            (activeDefinitions, scoreValues): boolean =>
                activeDefinitions.every((definition) => {
                    const value = scoreValues[definition.id]

                    if (definition.kind === 'categorical') {
                        return isCategoricalSelectionValid(definition, value)
                    }

                    if (definition.kind !== 'numeric') {
                        return true
                    }

                    if (value === undefined || value === null || value === '') {
                        return true
                    }

                    return typeof value === 'string' && value.trim() !== '' && !Number.isNaN(Number(value))
                }),
        ],

        isBusy: [
            (s) => [s.modalDataLoading, s.saving, s.removing],
            (modalDataLoading, saving, removing): boolean => modalDataLoading || saving || removing,
        ],

        canSave: [(s) => [s.isFormValid, s.isBusy], (isFormValid, isBusy): boolean => isFormValid && !isBusy],

        submitPayload: [
            (s) => [s.activeDefinitions, s.scoreValues, s.comment, (_, props) => props.traceId],
            (activeDefinitions, scoreValues, comment, traceId): TraceReviewUpsertPayload => ({
                trace_id: traceId,
                comment: comment.trim() || null,
                scores: activeDefinitions.flatMap((definition) => {
                    const value = scoreValues[definition.id]

                    if (definition.kind === 'categorical') {
                        const categoricalValues = getCategoricalSelections(value)
                        return categoricalValues.length > 0
                            ? [{ definition_id: definition.id, categorical_values: categoricalValues }]
                            : []
                    }

                    if (definition.kind === 'numeric') {
                        return typeof value === 'string' && value.trim()
                            ? [{ definition_id: definition.id, numeric_value: value.trim() }]
                            : []
                    }

                    return typeof value === 'boolean' ? [{ definition_id: definition.id, boolean_value: value }] : []
                }),
            }),
        ],
    }),

    listeners(({ actions, values, props }) => ({
        openModal: async () => {
            actions.resetForm()
            actions.loadModalData()
        },

        loadModalData: async () => {
            if (!values.currentTeamId) {
                actions.loadModalDataFailure()
                return
            }

            try {
                const [review, definitions] = await Promise.all([
                    traceReviewsApi.getByTraceId(props.traceId, values.currentTeamId),
                    loadActiveScoreDefinitions(values.currentTeamId),
                ])

                actions.loadModalDataSuccess(review, definitions)
                actions.populateForm(review)

                if (review) {
                    actions.cacheTraceReview(review)
                } else {
                    actions.setTraceAsUnreviewed(props.traceId)
                }
            } catch {
                lemonToast.error('Failed to load the current trace review.')
                actions.loadModalDataFailure()
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
                actions.cacheTraceReview(review)
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
                actions.setTraceAsUnreviewed(props.traceId)
                lemonToast.info('Trace review removed.')
                actions.closeModal()
            } catch (error) {
                lemonToast.error(`Failed to remove trace review. ${parseErrorMessage(error)}`)
                actions.removeCurrentReviewFailure()
            }
        },
    })),
])
