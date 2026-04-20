import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl, router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { signalSourcesLogic } from 'scenes/inbox/signalSourcesLogic'
import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from 'scenes/inbox/types'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { MaxContextInput, createMaxContextHelpers } from '~/scenes/max/maxTypes'
import { Breadcrumb } from '~/types'

import { parseTrialProviderKeyId } from '../ModelPicker'
import { LLMProviderKey, llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import { isUnhealthyProviderKeyState } from '../settings/providerKeyStateUtils'
import { queryEvaluationRuns } from '../utils'
import { evaluationErrorMessage } from './apiErrors'
import { EVALUATION_SUMMARY_MAX_RUNS } from './constants'
import { buildDeliveryTargets, evaluationReportLogic } from './evaluationReportLogic'
import type { llmEvaluationLogicType } from './llmEvaluationLogicType'
import { EvaluationTemplateKey, defaultEvaluationTemplates } from './templates'
import {
    EvaluationConditionSet,
    EvaluationConfig,
    EvaluationRun,
    EvaluationSummary,
    EvaluationSummaryFilter,
    EvaluationType,
    HogTestResult,
    ModelConfiguration,
} from './types'

export const DEFAULT_HOG_SOURCE = `// Check that the output is not empty
let result := length(output) > 0
if (not result) {
    print('Output is empty')
}
return result`

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
            ['providerKeys', 'providerKeysLoading', 'isTrialLimitReached'],
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
        setEvaluationType: (evaluationType: EvaluationType) => ({ evaluationType }),
        setHogSource: (source: string) => ({ source }),

        // Signal emission
        setSignalEmission: (enabled: boolean) => ({ enabled }),

        // Tab navigation
        setActiveTab: (tab: string) => ({ tab }),

        // Evaluation management actions
        saveEvaluation: true,
        saveEvaluationSuccess: (evaluation: EvaluationConfig) => ({ evaluation }),
        saveEvaluationFailure: (error: string) => ({ error }),
        loadEvaluation: true,
        loadEvaluationSuccess: (evaluation: EvaluationConfig | null) => ({ evaluation }),
        resetEvaluation: true,

        // Evaluation runs actions
        refreshEvaluationRuns: true,

        // Model selection actions
        selectModelFromPicker: (modelId: string, providerKeyId: string) => ({ modelId, providerKeyId }),

        // Hog test actions
        clearHogTestResults: true,

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
        hogTestResults: [
            null as HogTestResult[] | null,
            {
                testHogOnSample: async (): Promise<HogTestResult[] | null> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    const evaluation = values.evaluation
                    if (!evaluation || evaluation.evaluation_type !== 'hog') {
                        return null
                    }
                    try {
                        const conditions = evaluation.conditions
                            .filter((c) => c.properties && c.properties.length > 0)
                            .map((c) => ({ properties: c.properties }))
                        const response = await api.create(`/api/environments/${teamId}/evaluations/test_hog/`, {
                            source: evaluation.evaluation_config.source,
                            sample_count: 5,
                            allows_na: evaluation.output_config?.allows_na ?? false,
                            conditions,
                        })
                        return response.results
                    } catch (e: unknown) {
                        const message = e instanceof Error ? e.message : typeof e === 'string' ? e : 'Unknown error'
                        return [
                            {
                                event_uuid: 'error',
                                input_preview: '',
                                output_preview: '',
                                result: null,
                                reasoning: '',
                                error: typeof message === 'string' ? message : JSON.stringify(message),
                            },
                        ]
                    }
                },
            },
        ],
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
                    state && state.evaluation_type === 'llm_judge'
                        ? { ...state, evaluation_config: { ...state.evaluation_config, prompt } }
                        : state,
                setEvaluationEnabled: (state, { enabled }) => (state ? { ...state, enabled } : null),
                setAllowsNA: (state, { allowsNA }) =>
                    state ? { ...state, output_config: { ...state.output_config, allows_na: allowsNA } } : null,
                setTriggerConditions: (state, { conditions }) => (state ? { ...state, conditions } : null),
                setModelConfiguration: (state, { modelConfiguration }) =>
                    state ? { ...state, model_configuration: modelConfiguration } : null,
                setEvaluationType: (state, { evaluationType }) => {
                    if (!state) {
                        return null
                    }
                    if (evaluationType === 'hog') {
                        return {
                            ...state,
                            evaluation_type: 'hog',
                            evaluation_config: { source: DEFAULT_HOG_SOURCE },
                            model_configuration: null,
                            output_config: { ...state.output_config, allows_na: false },
                        }
                    }
                    return {
                        ...state,
                        evaluation_type: 'llm_judge',
                        evaluation_config: { prompt: '' },
                    }
                },
                setHogSource: (state, { source }) =>
                    state && state.evaluation_type === 'hog'
                        ? { ...state, evaluation_config: { ...state.evaluation_config, source } }
                        : state,
                loadEvaluationSuccess: (_, { evaluation }) => evaluation,
                saveEvaluationSuccess: (_, { evaluation }) => evaluation,
            },
        ],
        hogTestResults: {
            clearHogTestResults: () => null,
            setHogSource: () => null,
        },
        selectedModel: [
            '' as string,
            {
                selectModelFromPicker: (_, { modelId }) => modelId,
                setModelConfiguration: (_, { modelConfiguration }) => modelConfiguration?.model || '',
                loadEvaluationSuccess: (_, { evaluation }) => evaluation?.model_configuration?.model || '',
            },
        ],
        selectedPickerProviderKeyId: [
            null as string | null,
            {
                selectModelFromPicker: (_, { providerKeyId }) => providerKeyId,
                setModelConfiguration: (_, { modelConfiguration }) => modelConfiguration?.provider_key_id || null,
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
                saveEvaluationFailure: () => false,
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
                setEvaluationType: () => true,
                setHogSource: () => true,
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
        activeTab: [
            'configuration' as string,
            {
                setActiveTab: (_, { tab }) => tab,
                // Show runs tab for existing evaluations, configuration for new
                loadEvaluationSuccess: (_, { evaluation }) => (evaluation?.id ? 'runs' : 'configuration'),
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

                const baseFields = {
                    id: '',
                    name: template?.name || '',
                    description: template?.description || '',
                    enabled: true,
                    status: 'active' as const,
                    status_reason: null,
                    output_type: 'boolean' as const,
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
                const newEvaluation: EvaluationConfig =
                    template?.evaluation_type === 'hog'
                        ? {
                              ...baseFields,
                              evaluation_type: 'hog' as const,
                              evaluation_config: { source: template.source, bytecode: [] },
                          }
                        : {
                              ...baseFields,
                              evaluation_type: 'llm_judge' as const,
                              evaluation_config: {
                                  prompt: template && 'prompt' in template ? template.prompt : '',
                              },
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
                    status: 'active',
                    status_reason: null,
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
                    // Create the pending report before navigating away. The 'new'-keyed
                    // evaluationReportLogic unmounts when the component tears down, so
                    // snapshot its draft now and fire the create directly.
                    if (response?.id) {
                        const draft = evaluationReportLogic({ evaluationId: 'new' }).values.configDraft
                        const targets = buildDeliveryTargets(draft)
                        if (draft.enabled && (targets.length > 0 || draft.reportPromptGuidance.trim().length > 0)) {
                            const body: Record<string, unknown> = {
                                evaluation: response.id,
                                frequency: draft.frequency,
                                delivery_targets: targets,
                                report_prompt_guidance: draft.reportPromptGuidance,
                                enabled: true,
                            }
                            if (draft.frequency === 'scheduled') {
                                body.rrule = draft.rrule
                                body.starts_at = draft.startsAt
                                body.timezone_name = draft.timezoneName
                            }
                            if (draft.frequency === 'every_n') {
                                body.trigger_threshold = draft.triggerThreshold
                            }
                            try {
                                await api.create(`api/environments/${teamId}/llm_analytics/evaluation_reports/`, body)
                            } catch (reportError) {
                                // Don't block navigation if the (optional) pending report fails
                                posthog.captureException(reportError, { tag: 'eval-report-pending-create' })
                            }
                        }
                    }
                } else {
                    const response = await api.update(
                        `/api/environments/${teamId}/evaluations/${props.evaluationId}/`,
                        values.evaluation!
                    )
                    actions.saveEvaluationSuccess(response)
                }
                router.actions.push(urls.llmAnalyticsEvaluations(), router.values.searchParams)
            } catch (error) {
                const message = evaluationErrorMessage(error, 'Failed to save evaluation')
                lemonToast.error(message)
                actions.saveEvaluationFailure(message)
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
                const hasValidName = evaluation.name.length > 0
                const hasValidConditions =
                    evaluation.conditions.length > 0 &&
                    evaluation.conditions.every((c) => c.rollout_percentage > 0 && c.rollout_percentage <= 100)

                let hasValidConfig = false
                if (evaluation.evaluation_type === 'hog') {
                    hasValidConfig = evaluation.evaluation_config.source.trim().length > 0
                } else {
                    hasValidConfig = evaluation.evaluation_config.prompt.length > 0
                }

                return hasValidName && hasValidConfig && hasValidConditions
            },
        ],

        canEnable: [
            (s) => [s.evaluation, s.isTrialLimitReached],
            (evaluation: EvaluationConfig | null, isTrialLimitReached: boolean): boolean => {
                if (!evaluation || !isTrialLimitReached) {
                    return true
                }
                // Can enable if the evaluation has a BYOK key
                return !!evaluation.model_configuration?.provider_key_id
            },
        ],

        canEnableReason: [
            (s) => [s.canEnable],
            (canEnable: boolean): string | null => {
                if (canEnable) {
                    return null
                }
                return 'Trial evaluation limit reached. Add a provider API key to re-enable this evaluation.'
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

        maxContext: [
            (s) => [s.evaluation],
            (evaluation: EvaluationConfig | null): MaxContextInput[] => {
                if (!evaluation) {
                    return []
                }
                return [
                    createMaxContextHelpers.evaluation({
                        id: evaluation.id || 'new',
                        name: evaluation.name,
                        description: evaluation.description,
                        evaluation_type: evaluation.evaluation_type,
                        hog_source: evaluation.evaluation_type === 'hog' ? evaluation.evaluation_config.source : null,
                    }),
                ]
            },
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
