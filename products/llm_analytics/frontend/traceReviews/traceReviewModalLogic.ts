import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { ApiConfig } from '~/lib/api'

import { llmAnalyticsScoreDefinitionsList } from '../generated/api'
import type { ScoreDefinitionApi } from '../generated/api.schemas'
import type { traceReviewModalLogicType } from './traceReviewModalLogicType'
import { traceReviewsApi } from './traceReviewsApi'
import { traceReviewsLazyLoaderLogic } from './traceReviewsLazyLoaderLogic'
import type {
    TraceReview,
    TraceReviewFormScoreValue,
    TraceReviewScore,
    TraceReviewScoreUpsertPayload,
    TraceReviewUpsertPayload,
} from './types'
import { getCategoricalConfig, getTraceReviewScores } from './utils'

export interface TraceReviewModalLogicProps {
    traceId: string
}

const DEFINITION_PICKER_PAGE_SIZE = 50

function parseErrorMessage(error: unknown): string {
    if (error instanceof Error && error.message) {
        return error.message
    }

    return 'Something went wrong.'
}

function loadActiveScoreDefinitionsPage(
    teamId: number,
    search: string,
    offset: number
): ReturnType<typeof llmAnalyticsScoreDefinitionsList> {
    return llmAnalyticsScoreDefinitionsList(String(teamId), {
        archived: false,
        order_by: 'name',
        search: search.trim() || undefined,
        offset,
        limit: DEFINITION_PICKER_PAGE_SIZE,
    })
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

function buildScoreDefinitionFromReviewScore(score: TraceReviewScore, teamId: number): ScoreDefinitionApi {
    return {
        id: score.definition_id,
        name: score.definition_name,
        description: score.definition_archived
            ? 'Archived scorer from this review.'
            : 'Saved scorer version from this review.',
        kind: score.definition_kind,
        archived: score.definition_archived,
        current_version: score.definition_version,
        config: score.definition_config,
        created_by: null,
        created_at: score.created_at,
        updated_at: score.updated_at,
        team: teamId,
    }
}

function getExistingScoreLookup(review: TraceReview | null): Record<string, TraceReviewScore> {
    return Object.fromEntries(getTraceReviewScores(review).map((score) => [score.definition_id, score]))
}

function buildScorePayload(
    definition: ScoreDefinitionApi,
    value: TraceReviewFormScoreValue | undefined,
    existingScore: TraceReviewScore | undefined
): TraceReviewScoreUpsertPayload[] {
    const definitionVersionId = existingScore?.definition_version_id ?? undefined
    const basePayload = {
        definition_id: definition.id,
        ...(definitionVersionId ? { definition_version_id: definitionVersionId } : {}),
    }

    if (definition.kind === 'categorical') {
        const categoricalValues = getCategoricalSelections(value)
        return categoricalValues.length > 0 ? [{ ...basePayload, categorical_values: categoricalValues }] : []
    }

    if (definition.kind === 'numeric') {
        return typeof value === 'string' && value.trim() ? [{ ...basePayload, numeric_value: value.trim() }] : []
    }

    return typeof value === 'boolean' ? [{ ...basePayload, boolean_value: value }] : []
}

function mergeDefinitions(
    existingDefinitions: ScoreDefinitionApi[],
    incomingDefinitions: ScoreDefinitionApi[]
): ScoreDefinitionApi[] {
    const mergedDefinitions = [...existingDefinitions]

    for (const incomingDefinition of incomingDefinitions) {
        const existingIndex = mergedDefinitions.findIndex((definition) => definition.id === incomingDefinition.id)

        if (existingIndex === -1) {
            mergedDefinitions.push(incomingDefinition)
            continue
        }

        mergedDefinitions[existingIndex] = incomingDefinition
    }

    return mergedDefinitions
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
        selectDefinition: (definition: ScoreDefinitionApi) => ({ definition }),
        removeSelectedDefinition: (definitionId: string) => ({ definitionId }),
        setComment: (comment: string) => ({ comment }),
        setDefinitionSearch: (search: string) => ({ search }),
        loadDefinitionOptions: (replace: boolean = false) => ({ replace }),
        loadDefinitionOptionsSuccess: (definitions: ScoreDefinitionApi[], totalCount: number, replace: boolean) => ({
            definitions,
            totalCount,
            replace,
        }),
        loadDefinitionOptionsFailure: true,
        loadMoreDefinitions: true,
        loadModalData: true,
        loadModalDataSuccess: (review: TraceReview | null, definitions: ScoreDefinitionApi[], totalCount: number) => ({
            review,
            definitions,
            totalCount,
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

        loadedDefinitions: [
            [] as ScoreDefinitionApi[],
            {
                openModal: () => [],
                setDefinitionSearch: () => [],
                loadModalDataSuccess: (_, { definitions }) => definitions,
                loadDefinitionOptionsSuccess: (state, { definitions, replace }) =>
                    replace ? definitions : mergeDefinitions(state, definitions),
                loadModalDataFailure: () => [],
                closeModal: (state) => state,
            },
        ],

        selectedDefinitionSnapshots: [
            {} as Record<string, ScoreDefinitionApi>,
            {
                resetForm: () => ({}),
                populateForm: (_, { review }) =>
                    Object.fromEntries(
                        getTraceReviewScores(review).map((score) => {
                            const definition = buildScoreDefinitionFromReviewScore(score, review?.team ?? 0)
                            return [definition.id, definition]
                        })
                    ),
                selectDefinition: (state, { definition }) => ({
                    ...state,
                    [definition.id]: definition,
                }),
                removeSelectedDefinition: (state, { definitionId }) => {
                    const nextState = { ...state }
                    delete nextState[definitionId]
                    return nextState
                },
                removeCurrentReviewSuccess: () => ({}),
            },
        ],

        selectedDefinitionIds: [
            [] as string[],
            {
                resetForm: () => [],
                populateForm: (_, { review }) => getTraceReviewScores(review).map((score) => score.definition_id),
                selectDefinition: (state, { definition }) =>
                    state.includes(definition.id) ? state : [...state, definition.id],
                removeSelectedDefinition: (state, { definitionId }) =>
                    state.filter((selectedDefinitionId) => selectedDefinitionId !== definitionId),
                removeCurrentReviewSuccess: () => [],
            },
        ],

        definitionSearch: [
            '',
            {
                openModal: () => '',
                closeModal: () => '',
                setDefinitionSearch: (_, { search }) => search,
            },
        ],

        totalDefinitionCount: [
            0,
            {
                openModal: () => 0,
                setDefinitionSearch: () => 0,
                loadModalDataSuccess: (_, { totalCount }) => totalCount,
                loadDefinitionOptionsSuccess: (_, { totalCount }) => totalCount,
                loadModalDataFailure: () => 0,
            },
        ],

        modalDataLoading: [
            false,
            {
                openModal: () => true,
                loadModalData: () => true,
                loadModalDataSuccess: () => false,
                loadModalDataFailure: () => false,
                closeModal: () => false,
            },
        ],

        definitionOptionsLoading: [
            false,
            {
                setDefinitionSearch: () => true,
                loadDefinitionOptions: () => true,
                loadDefinitionOptionsSuccess: () => false,
                loadDefinitionOptionsFailure: () => false,
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
                        getTraceReviewScores(review).map((score) => [
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
        selectedDefinitions: [
            (s) => [s.loadedDefinitions, s.selectedDefinitionSnapshots, s.selectedDefinitionIds],
            (loadedDefinitions, selectedDefinitionSnapshots, selectedDefinitionIds): ScoreDefinitionApi[] => {
                const loadedDefinitionsById = new Map(
                    loadedDefinitions.map((definition) => [definition.id, definition])
                )

                return selectedDefinitionIds
                    .map(
                        (definitionId) =>
                            loadedDefinitionsById.get(definitionId) ?? selectedDefinitionSnapshots[definitionId]
                    )
                    .filter((definition): definition is ScoreDefinitionApi => !!definition)
            },
        ],

        selectableDefinitions: [
            (s) => [s.loadedDefinitions, s.selectedDefinitionIds],
            (loadedDefinitions, selectedDefinitionIds): ScoreDefinitionApi[] =>
                loadedDefinitions.filter((definition) => !selectedDefinitionIds.includes(definition.id)),
        ],

        hasMoreDefinitions: [
            (s) => [s.loadedDefinitions, s.totalDefinitionCount],
            (loadedDefinitions, totalDefinitionCount): boolean => loadedDefinitions.length < totalDefinitionCount,
        ],

        definitionResultsLabel: [
            (s) => [s.loadedDefinitions, s.totalDefinitionCount, s.definitionSearch],
            (loadedDefinitions, totalDefinitionCount, definitionSearch): string | null => {
                if (totalDefinitionCount === 0) {
                    return null
                }

                const scorerLabel = definitionSearch.trim() ? 'matching scorers' : 'active scorers'

                return loadedDefinitions.length < totalDefinitionCount
                    ? `Showing ${loadedDefinitions.length} of ${totalDefinitionCount} ${scorerLabel}.`
                    : `${totalDefinitionCount} ${scorerLabel} available.`
            },
        ],

        isFormValid: [
            (s) => [s.selectedDefinitions, s.scoreValues],
            (selectedDefinitions, scoreValues): boolean =>
                selectedDefinitions.every((definition) => {
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
            (s) => [s.selectedDefinitions, s.scoreValues, s.comment, s.currentReview, (_, props) => props.traceId],
            (selectedDefinitions, scoreValues, comment, currentReview, traceId): TraceReviewUpsertPayload => {
                const existingScoresByDefinitionId = getExistingScoreLookup(currentReview)

                return {
                    trace_id: traceId,
                    comment: comment.trim() || null,
                    scores: selectedDefinitions.flatMap((definition) => {
                        const value = scoreValues[definition.id]
                        const existingScore = existingScoresByDefinitionId[definition.id]
                        return buildScorePayload(definition, value, existingScore)
                    }),
                }
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        openModal: async () => {
            actions.resetForm()
            actions.loadModalData()
        },

        setDefinitionSearch: async ({ search }, breakpoint) => {
            await breakpoint(300)

            if (search !== values.definitionSearch || !values.isOpen) {
                return
            }

            actions.loadDefinitionOptions(true)
        },

        loadDefinitionOptions: async ({ replace }, breakpoint) => {
            const teamId = values.currentTeamId ?? ApiConfig.getCurrentTeamId()

            if (!teamId) {
                actions.loadDefinitionOptionsFailure()
                return
            }

            try {
                const response = await loadActiveScoreDefinitionsPage(
                    teamId,
                    values.definitionSearch,
                    replace ? 0 : values.loadedDefinitions.length
                )

                breakpoint()
                actions.loadDefinitionOptionsSuccess(response.results, response.count, replace)
            } catch {
                actions.loadDefinitionOptionsFailure()
            }
        },

        loadMoreDefinitions: async () => {
            if (values.definitionOptionsLoading || !values.hasMoreDefinitions) {
                return
            }

            actions.loadDefinitionOptions(false)
        },

        loadModalData: async () => {
            const teamId = values.currentTeamId ?? ApiConfig.getCurrentTeamId()

            if (!teamId) {
                actions.loadModalDataFailure()
                return
            }

            try {
                const [review, definitionsResponse] = await Promise.all([
                    traceReviewsApi.getByTraceId(props.traceId, teamId),
                    loadActiveScoreDefinitionsPage(teamId, '', 0),
                ])

                actions.loadModalDataSuccess(review, definitionsResponse.results, definitionsResponse.count)
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
            const teamId = values.currentTeamId ?? ApiConfig.getCurrentTeamId()

            if (!teamId || !values.isFormValid) {
                actions.saveCurrentReviewFailure()
                return
            }

            try {
                const review = await traceReviewsApi.save(values.submitPayload, values.currentReview, teamId)
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
            const teamId = values.currentTeamId ?? ApiConfig.getCurrentTeamId()

            if (!teamId || !values.currentReview) {
                actions.removeCurrentReviewFailure()
                return
            }

            try {
                await traceReviewsApi.delete(values.currentReview.id, teamId)
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
