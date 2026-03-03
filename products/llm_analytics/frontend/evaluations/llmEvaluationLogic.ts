import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl, router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { signalSourcesLogic } from 'scenes/inbox/signalSourcesLogic'
import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from 'scenes/inbox/types'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { parseTrialProviderKeyId } from '../ModelPicker'
import { LLMProviderKey, llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import { isUnhealthyProviderKeyState } from '../settings/providerKeyStateUtils'
import { queryEvaluationRuns } from '../utils'
import { EVALUATION_SUMMARY_MAX_RUNS } from './constants'
import type { llmEvaluationLogicType } from './llmEvaluationLogicType'
import { llmEvaluationsLogic } from './llmEvaluationsLogic'
import { EvaluationTemplateKey, defaultEvaluationTemplates } from './templates'
import {
    EvaluationConditionSet,
    EvaluationConfig,
    EvaluationRun,
    EvaluationSummary,
    EvaluationSummaryFilter,
    ModelConfiguration,
} from './types'

export interface LLMEvaluationLogicProps {
    evaluationId: string
    templateKey?: EvaluationTemplateKey
    tabId?: string
}

export const llmEvaluationLogic = kea<llmEvaluationLogicType>([
    path(['products', 'llm_analytics', 'evaluations', 'llmEvaluationLogic']),
    props({} as LLMEvaluationLogicProps),
    key(
        (props) =>
            `${props.evaluationId || 'new'}${props.templateKey ? `-${props.templateKey}` : ''}::${props.tabId ?? 'default'}`
    ),

    connect(() => ({
        values: [
            llmProviderKeysLogic,
            ['providerKeys', 'providerKeysLoading'],
            signalSourcesLogic,
            ['sourceConfigs', 'sourceConfigsLoading'],
        ],
        actions: [
            llmProviderKeysLogic,
            ['loadProviderKeys'],
            signalSourcesLogic,
            [
                'loadSourceConfigs',
                'loadSourceConfigsSuccess',
                'toggleSignalSource',
                'toggleSignalSourceSuccess',
                'toggleSignalSourceFailure',
            ],
        ],
    })),

    actions({
        // Evaluation configuration actions
        setEvaluationName: (name: string) => ({ name }),
        setEvaluationDescription: (description: string) => ({ description }),
        setEvaluationPrompt: (prompt: string) => ({ prompt }),
        setEvaluationEnabled: (enabled: boolean) => ({ enabled }),
        setAllowsNA: (allowsNA: boolean) => ({ allowsNA }),
        setTriggerConditions: (conditions: EvaluationConditionSet[]) => ({ conditions }),
        setModelConfiguration: (modelConfiguration: ModelConfiguration | null) => ({ modelConfiguration }),

        // Signal emission
        setSignalEmission: (enabled: boolean) => ({ enabled }),

        // Evaluation management actions
        saveEvaluation: true,
        saveEvaluationSuccess: (evaluation: EvaluationConfig) => ({ evaluation }),
        loadEvaluation: true,
        loadEvaluationSuccess: (evaluation: EvaluationConfig | null) => ({ evaluation }),
        resetEvaluation: true,

        // Evaluation runs actions
        refreshEvaluationRuns: true,

        // Model selection actions
        selectModelFromPicker: (modelId: string, providerKeyId: string) => ({ modelId, providerKeyId }),

        // Evaluation summary actions
        setEvaluationSummaryFilter: (filter: EvaluationSummaryFilter, previousFilter: EvaluationSummaryFilter) => ({
            filter,
            previousFilter,
        }),
        toggleSummaryExpanded: true,
        regenerateEvaluationSummary: true,
        trackSummarizeClicked: true,
    }),

    loaders(({ props, values }) => ({
        evaluationRuns: [
            [] as EvaluationRun[],
            {
                loadEvaluationRuns: async () => {
                    if (!props.evaluationId || props.evaluationId === 'new') {
                        return []
                    }

                    return await queryEvaluationRuns({
                        evaluationId: props.evaluationId,
                        forceRefresh: values.isForceRefresh,
                    })
                },
            },
        ],
        evaluationSummary: [
            null as EvaluationSummary | null,
            {
                generateEvaluationSummary: async ({ forceRefresh }: { forceRefresh?: boolean }) => {
                    const shouldRefresh = forceRefresh ?? false
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId || !props.evaluationId || props.evaluationId === 'new') {
                        return null
                    }

                    const requestFilter = values.evaluationSummaryFilter

                    // Backend fetches data server-side by ID - we just pass the filter
                    const response = await api.create(`/api/environments/${teamId}/llm_analytics/evaluation_summary/`, {
                        evaluation_id: props.evaluationId,
                        filter: requestFilter,
                        force_refresh: shouldRefresh,
                    })

                    // Discard if the user changed the filter while the request was in flight
                    if (values.evaluationSummaryFilter !== requestFilter) {
                        return null
                    }

                    return response as EvaluationSummary
                },
            },
        ],
    })),

    reducers({
        originalEvaluation: [
            null as EvaluationConfig | null,
            {
                loadEvaluationSuccess: (_, { evaluation }) => evaluation,
                saveEvaluationSuccess: (_, { evaluation }) => evaluation,
            },
        ],
        evaluation: [
            null as EvaluationConfig | null,
            {
                setEvaluationName: (state, { name }) => (state ? { ...state, name } : null),
                setEvaluationDescription: (state, { description }) => (state ? { ...state, description } : null),
                setEvaluationPrompt: (state, { prompt }) =>
                    state ? { ...state, evaluation_config: { ...state.evaluation_config, prompt } } : null,
                setEvaluationEnabled: (state, { enabled }) => (state ? { ...state, enabled } : null),
                setAllowsNA: (state, { allowsNA }) =>
                    state ? { ...state, output_config: { ...state.output_config, allows_na: allowsNA } } : null,
                setTriggerConditions: (state, { conditions }) => (state ? { ...state, conditions } : null),
                setModelConfiguration: (state, { modelConfiguration }) =>
                    state ? { ...state, model_configuration: modelConfiguration } : null,
                loadEvaluationSuccess: (_, { evaluation }) => evaluation,
                saveEvaluationSuccess: (_, { evaluation }) => evaluation,
            },
        ],
        selectedModel: [
            '' as string,
            {
                selectModelFromPicker: (_, { modelId }) => modelId,
                loadEvaluationSuccess: (_, { evaluation }) => evaluation?.model_configuration?.model || '',
            },
        ],
        selectedPickerProviderKeyId: [
            null as string | null,
            {
                selectModelFromPicker: (_, { providerKeyId }) => providerKeyId,
                loadEvaluationSuccess: (_, { evaluation }) => evaluation?.model_configuration?.provider_key_id || null,
            },
        ],
        isForceRefresh: [
            false,
            {
                refreshEvaluationRuns: () => true,
                loadEvaluationRunsSuccess: () => false,
                loadEvaluationRunsFailure: () => false,
            },
        ],
        evaluationLoading: [
            false,
            {
                loadEvaluation: () => true,
                loadEvaluationSuccess: () => false,
            },
        ],
        evaluationFormSubmitting: [
            false,
            {
                saveEvaluation: () => true,
                saveEvaluationSuccess: () => false,
            },
        ],
        signalEmissionOptimistic: [
            null as boolean | null,
            {
                setSignalEmission: (_, { enabled }) => enabled,
                loadSourceConfigsSuccess: () => null,
                toggleSignalSourceFailure: () => null,
            },
        ],
        hasUnsavedChanges: [
            false,
            {
                setEvaluationName: () => true,
                setEvaluationDescription: () => true,
                setEvaluationPrompt: () => true,
                setEvaluationEnabled: () => true,
                setAllowsNA: () => true,
                setTriggerConditions: () => true,
                setModelConfiguration: () => true,
                saveEvaluationSuccess: () => false,
                loadEvaluationSuccess: () => false,
                resetEvaluation: () => false,
            },
        ],
        evaluationSummaryFilter: [
            'all' as EvaluationSummaryFilter,
            {
                setEvaluationSummaryFilter: (_, { filter }) => filter,
            },
        ],
        // Clear summary when filter changes so stale summary doesn't mismatch current filter
        evaluationSummary: {
            setEvaluationSummaryFilter: () => null,
        },
        evaluationSummaryError: [
            false,
            {
                generateEvaluationSummary: () => false,
                generateEvaluationSummarySuccess: () => false,
                generateEvaluationSummaryFailure: () => true,
                setEvaluationSummaryFilter: () => false,
            },
        ],
        summaryExpanded: [
            true,
            {
                toggleSummaryExpanded: (state) => !state,
                generateEvaluationSummarySuccess: () => true,
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        loadEvaluation: async () => {
            if (props.evaluationId && props.evaluationId !== 'new') {
                try {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return
                    }

                    const evaluation = await api.get(`/api/environments/${teamId}/evaluations/${props.evaluationId}/`)
                    actions.loadEvaluationSuccess(evaluation)
                } catch (error) {
                    console.error('Failed to load evaluation:', error)
                    actions.loadEvaluationSuccess(null)
                }
            } else if (props.evaluationId === 'new') {
                // Initialize new evaluation
                // Check if we should pre-fill from a template
                const template = props.templateKey
                    ? defaultEvaluationTemplates.find((t) => t.key === props.templateKey)
                    : undefined

                const newEvaluation: EvaluationConfig = {
                    id: '',
                    name: template?.name || '',
                    description: template?.description || '',
                    enabled: true,
                    evaluation_type: 'llm_judge',
                    evaluation_config: {
                        prompt: template?.prompt || '',
                    },
                    output_type: 'boolean',
                    output_config: {},
                    conditions: [
                        {
                            id: `cond-${Date.now()}`,
                            rollout_percentage: 0,
                            properties: [],
                        },
                    ],
                    model_configuration: null,
                    total_runs: 0,
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                }
                actions.loadEvaluationSuccess(newEvaluation)
            }
        },

        refreshEvaluationRuns: () => {
            actions.loadEvaluationRuns()
        },

        regenerateEvaluationSummary: () => {
            posthog.capture('llma evaluation regenerate clicked', {
                filter: values.evaluationSummaryFilter,
                runs_to_summarize: values.runsToSummarizeCount,
            })
            actions.generateEvaluationSummary({ forceRefresh: true })
        },

        trackSummarizeClicked: () => {
            posthog.capture('llma evaluation summarize clicked', {
                filter: values.evaluationSummaryFilter,
                runs_to_summarize: values.runsToSummarizeCount,
            })
        },

        setEvaluationSummaryFilter: ({ filter, previousFilter }) => {
            posthog.capture('llma evaluation summary filter changed', {
                filter,
                previous_filter: previousFilter,
            })
        },

        toggleSummaryExpanded: () => {
            posthog.capture('llma evaluation summary toggled', {
                expanded: values.summaryExpanded,
                filter: values.evaluationSummaryFilter,
            })
        },

        resetEvaluation: () => {
            if (props.evaluationId === 'new') {
                const newEvaluation: EvaluationConfig = {
                    id: '',
                    name: '',
                    description: '',
                    enabled: true,
                    evaluation_type: 'llm_judge',
                    evaluation_config: {
                        prompt: '',
                    },
                    output_type: 'boolean',
                    output_config: {},
                    conditions: [
                        {
                            id: `cond-${Date.now()}`,
                            rollout_percentage: 0,
                            properties: [],
                        },
                    ],
                    model_configuration: null,
                    total_runs: 0,
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                }
                actions.loadEvaluationSuccess(newEvaluation)
            } else {
                actions.loadEvaluationSuccess(values.originalEvaluation)
            }
        },

        setSignalEmission: ({ enabled }) => {
            const configs: SignalSourceConfig[] = values.sourceConfigs ?? []
            const existing = configs.find(
                (c) =>
                    c.source_product === SignalSourceProduct.LLM_ANALYTICS &&
                    c.source_type === SignalSourceType.EVALUATION
            )

            const currentIds: string[] = existing?.config?.evaluation_ids ?? []
            const newIds = enabled
                ? [...new Set([...currentIds, props.evaluationId])]
                : currentIds.filter((id: string) => id !== props.evaluationId)

            actions.toggleSignalSource({
                sourceProduct: SignalSourceProduct.LLM_ANALYTICS,
                sourceType: SignalSourceType.EVALUATION,
                enabled: true,
                config: { ...existing?.config, evaluation_ids: newIds },
            })
        },

        saveEvaluation: async () => {
            try {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }

                if (props.evaluationId === 'new') {
                    const response = await api.create(`/api/environments/${teamId}/evaluations/`, values.evaluation!)
                    actions.saveEvaluationSuccess(response)
                    llmEvaluationsLogic.findMounted()?.actions.loadEvaluations()
                } else {
                    const response = await api.update(
                        `/api/environments/${teamId}/evaluations/${props.evaluationId}/`,
                        values.evaluation!
                    )
                    actions.saveEvaluationSuccess(response)
                }
                router.actions.push(urls.llmAnalyticsEvaluations(), router.values.searchParams)
            } catch (error) {
                console.error('Failed to save evaluation:', error)
            }
        },

        selectModelFromPicker: ({ modelId, providerKeyId }) => {
            if (!modelId) {
                return
            }
            const trialProvider = parseTrialProviderKeyId(providerKeyId)
            if (trialProvider) {
                actions.setModelConfiguration({
                    provider: trialProvider,
                    model: modelId,
                    provider_key_id: null,
                })
                return
            }
            const key = values.providerKeys.find((k: LLMProviderKey) => k.id === providerKeyId)
            if (key) {
                actions.setModelConfiguration({
                    provider: key.provider,
                    model: modelId,
                    provider_key_id: providerKeyId,
                })
            }
        },
    })),

    selectors({
        isNewEvaluation: [(_, props) => [props.evaluationId], (evaluationId: string) => evaluationId === 'new'],

        signalEmissionEnabled: [
            (s, props) => [s.signalEmissionOptimistic, s.sourceConfigs, props.evaluationId],
            (optimistic: boolean | null, sourceConfigs: SignalSourceConfig[] | null, evaluationId: string): boolean => {
                if (optimistic !== null) {
                    return optimistic
                }
                if (!sourceConfigs) {
                    return false
                }
                const llmEvalConfig = sourceConfigs.find(
                    (c) =>
                        c.source_product === SignalSourceProduct.LLM_ANALYTICS &&
                        c.source_type === SignalSourceType.EVALUATION
                )
                const ids: string[] = llmEvalConfig?.config?.evaluation_ids ?? []
                return !!llmEvalConfig?.enabled && ids.includes(evaluationId)
            },
        ],

        formValid: [
            (s) => [s.evaluation],
            (evaluation) => {
                if (!evaluation) {
                    return false
                }
                return (
                    evaluation.name.length > 0 &&
                    evaluation.evaluation_config.prompt.length > 0 &&
                    evaluation.conditions.length > 0 &&
                    evaluation.conditions.every((c) => c.rollout_percentage > 0 && c.rollout_percentage <= 100)
                )
            },
        ],

        evaluationProviderKeyIssue: [
            (s) => [s.evaluation, s.providerKeys],
            (evaluation: EvaluationConfig | null, providerKeys: LLMProviderKey[]): LLMProviderKey | null => {
                const providerKeyId = evaluation?.model_configuration?.provider_key_id
                if (!providerKeyId) {
                    return null
                }

                const providerKey = providerKeys.find((key) => key.id === providerKeyId)
                if (!providerKey || !isUnhealthyProviderKeyState(providerKey.state)) {
                    return null
                }

                return providerKey
            },
        ],

        runsLookup: [
            (s) => [s.evaluationRuns],
            (runs): Record<string, EvaluationRun> => {
                const lookup: Record<string, EvaluationRun> = {}
                for (const run of runs) {
                    lookup[run.generation_id] = run
                }
                return lookup
            },
        ],

        runsSummary: [
            (s) => [s.evaluationRuns],
            (runs) => {
                if (runs.length === 0) {
                    return null
                }

                const successfulRuns = runs.filter((r) => r.result === true).length
                const failedRuns = runs.filter((r) => r.result === false).length
                const errorRuns = runs.filter((r) => r.status === 'failed').length
                // Applicable runs excludes N/A (result === null)
                const applicableRuns = successfulRuns + failedRuns
                const completedRuns = runs.filter((r) => r.status === 'completed').length

                return {
                    total: runs.length,
                    successful: successfulRuns,
                    failed: failedRuns,
                    errors: errorRuns,
                    successRate: applicableRuns > 0 ? Math.round((successfulRuns / applicableRuns) * 100) : 0,
                    applicabilityRate: completedRuns > 0 ? Math.round((applicableRuns / completedRuns) * 100) : 0,
                }
            },
        ],

        filteredEvaluationRuns: [
            (s) => [s.evaluationRuns, s.evaluationSummaryFilter],
            (runs: EvaluationRun[], filter: EvaluationSummaryFilter): EvaluationRun[] => {
                if (filter === 'all') {
                    return runs
                }
                // Only consider completed runs for filtering
                const completedRuns = runs.filter((r) => r.status === 'completed')
                if (filter === 'pass') {
                    return completedRuns.filter((r) => r.result === true)
                }
                if (filter === 'fail') {
                    return completedRuns.filter((r) => r.result === false)
                }
                // na
                return completedRuns.filter((r) => r.result === null)
            },
        ],

        runsToSummarizeCount: [
            (s) => [s.filteredEvaluationRuns, s.evaluationSummaryFilter],
            (filteredRuns: EvaluationRun[], filter: EvaluationSummaryFilter): number => {
                // When 'all', filteredEvaluationRuns includes non-completed runs, but summarization only uses completed
                const count =
                    filter === 'all' ? filteredRuns.filter((r) => r.status === 'completed').length : filteredRuns.length
                return Math.min(count, EVALUATION_SUMMARY_MAX_RUNS)
            },
        ],

        breadcrumbs: [
            (s) => [s.evaluation, router.selectors.searchParams],
            (evaluation: EvaluationConfig | null, searchParams: Record<string, any>): Breadcrumb[] => [
                {
                    name: 'Evaluations',
                    path: combineUrl(urls.llmAnalyticsEvaluations(), searchParams).url,
                    key: 'LLMAnalyticsEvaluations',
                    iconType: 'llm_evaluations',
                },
                {
                    name: evaluation?.name || 'New Evaluation',
                    key: 'LLMAnalyticsEvaluationEdit',
                    iconType: 'llm_evaluations',
                },
            ],
        ],
    }),

    tabAwareUrlToAction(({ actions, props }) => ({
        '/llm-analytics/evaluations/:id': ({ id }, _, __, { method }) => {
            // Only reload when navigating to a different evaluation, not on search param changes (e.g., pagination)
            const newEvaluationId = id && id !== 'new' ? id : 'new'
            if (method === 'PUSH' && newEvaluationId !== props.evaluationId) {
                actions.loadEvaluation()
                if (props.evaluationId !== 'new') {
                    actions.loadEvaluationRuns()
                }
            }
        },
    })),

    afterMount(({ actions, props }) => {
        actions.loadProviderKeys()
        actions.loadSourceConfigs()
        actions.loadEvaluation()
        if (props.evaluationId !== 'new') {
            actions.loadEvaluationRuns()
        }
    }),
])
