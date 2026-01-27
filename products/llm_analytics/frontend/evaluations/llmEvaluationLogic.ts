import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { LLMProvider, LLMProviderKey, llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import { queryEvaluationRuns } from '../utils'
import type { llmEvaluationLogicType } from './llmEvaluationLogicType'
import { EvaluationTemplateKey, defaultEvaluationTemplates } from './templates'
import { EvaluationConditionSet, EvaluationConfig, EvaluationRun, ModelConfiguration } from './types'

export interface AvailableModel {
    id: string
    posthog_available: boolean
}

export interface LLMEvaluationLogicProps {
    evaluationId: string
    templateKey?: EvaluationTemplateKey
}

export const llmEvaluationLogic = kea<llmEvaluationLogicType>([
    path(['products', 'llm_analytics', 'evaluations', 'llmEvaluationLogic']),
    props({} as LLMEvaluationLogicProps),
    key((props) => `${props.evaluationId || 'new'}${props.templateKey ? `-${props.templateKey}` : ''}`),

    connect({
        values: [llmProviderKeysLogic, ['providerKeys', 'providerKeysLoading']],
        actions: [llmProviderKeysLogic, ['loadProviderKeys', 'loadProviderKeysSuccess']],
    }),

    actions({
        // Evaluation configuration actions
        setEvaluationName: (name: string) => ({ name }),
        setEvaluationDescription: (description: string) => ({ description }),
        setEvaluationPrompt: (prompt: string) => ({ prompt }),
        setEvaluationEnabled: (enabled: boolean) => ({ enabled }),
        setAllowsNA: (allowsNA: boolean) => ({ allowsNA }),
        setTriggerConditions: (conditions: EvaluationConditionSet[]) => ({ conditions }),
        setModelConfiguration: (modelConfiguration: ModelConfiguration | null) => ({ modelConfiguration }),

        // Evaluation management actions
        saveEvaluation: true,
        saveEvaluationSuccess: (evaluation: EvaluationConfig) => ({ evaluation }),
        loadEvaluation: true,
        loadEvaluationSuccess: (evaluation: EvaluationConfig | null) => ({ evaluation }),
        resetEvaluation: true,

        // Evaluation runs actions
        refreshEvaluationRuns: true,

        // Model selection actions
        setSelectedProvider: (provider: LLMProvider) => ({ provider }),
        setSelectedKeyId: (keyId: string | null) => ({ keyId }),
        setSelectedModel: (model: string) => ({ model }),
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
        availableModels: [
            [] as AvailableModel[],
            {
                loadAvailableModels: async ({
                    provider,
                    keyId,
                }: {
                    provider: LLMProvider
                    keyId: string | null
                }): Promise<AvailableModel[]> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return []
                    }
                    const params = new URLSearchParams({ provider })
                    if (keyId) {
                        params.append('key_id', keyId)
                    }
                    const response = await api.get(
                        `/api/environments/${teamId}/llm_analytics/models/?${params.toString()}`
                    )
                    return response.models
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
        selectedProvider: [
            'openai' as LLMProvider,
            {
                setSelectedProvider: (_, { provider }) => provider,
                loadEvaluationSuccess: (_, { evaluation }) => evaluation?.model_configuration?.provider || 'openai',
            },
        ],
        selectedKeyId: [
            null as string | null,
            {
                setSelectedKeyId: (_, { keyId }) => keyId,
                loadEvaluationSuccess: (_, { evaluation }) => evaluation?.model_configuration?.provider_key_id || null,
            },
        ],
        selectedModel: [
            '' as string,
            {
                setSelectedModel: (_, { model }) => model,
                loadEvaluationSuccess: (_, { evaluation }) => evaluation?.model_configuration?.model || '',
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

        loadEvaluationSuccess: ({ evaluation }) => {
            // Load available models for the current provider/key combination
            if (evaluation) {
                const provider = evaluation.model_configuration?.provider || 'openai'
                let keyId = evaluation.model_configuration?.provider_key_id || null

                // For new evals without a key, auto-select user's first key if available
                if (!keyId && !evaluation.id) {
                    const keysForProvider = values.providerKeysByProvider[provider] || []
                    if (keysForProvider.length > 0) {
                        keyId = keysForProvider[0].id
                        actions.setSelectedKeyId(keyId)
                    }
                }

                actions.loadAvailableModels({ provider, keyId })
            }
        },

        loadProviderKeysSuccess: () => {
            // When provider keys finish loading after evaluation, auto-select key for new evals
            const evaluation = values.evaluation
            if (evaluation && !evaluation.id && !values.selectedKeyId) {
                const keysForProvider = values.providerKeysByProvider[values.selectedProvider] || []
                if (keysForProvider.length > 0) {
                    const keyId = keysForProvider[0].id
                    actions.setSelectedKeyId(keyId)
                    actions.loadAvailableModels({ provider: values.selectedProvider, keyId })
                }
            }
        },

        refreshEvaluationRuns: () => {
            actions.loadEvaluationRuns()
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

        saveEvaluation: async () => {
            try {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }

                if (props.evaluationId === 'new') {
                    const response = await api.create(`/api/environments/${teamId}/evaluations/`, values.evaluation!)
                    actions.saveEvaluationSuccess(response)
                } else {
                    const response = await api.update(
                        `/api/environments/${teamId}/evaluations/${props.evaluationId}/`,
                        values.evaluation!
                    )
                    actions.saveEvaluationSuccess(response)
                }
                router.actions.push(urls.llmAnalyticsEvaluations())
            } catch (error) {
                console.error('Failed to save evaluation:', error)
            }
        },

        setSelectedProvider: ({ provider }) => {
            // When provider changes, auto-select user's first key if they have one, otherwise use PostHog default
            const keysForProvider = values.providerKeysByProvider[provider] || []
            const keyId = keysForProvider.length > 0 ? keysForProvider[0].id : null
            actions.loadAvailableModels({ provider, keyId })
            actions.setSelectedKeyId(keyId)
            actions.setSelectedModel('')
        },

        setSelectedKeyId: ({ keyId }) => {
            // When key changes, reload available models and reset model selection
            const provider = values.selectedProvider
            actions.loadAvailableModels({ provider, keyId })
            actions.setSelectedModel('')
        },

        setSelectedModel: ({ model }) => {
            // When model is selected, update the model configuration
            if (model) {
                const modelConfig: ModelConfiguration = {
                    provider: values.selectedProvider,
                    model,
                    provider_key_id: values.selectedKeyId,
                }
                actions.setModelConfiguration(modelConfig)
            } else {
                actions.setModelConfiguration(null)
            }
        },

        loadAvailableModelsSuccess: ({ availableModels }) => {
            // If the currently selected model is not in the available models, reset it
            if (values.selectedModel && !availableModels.some((m: AvailableModel) => m.id === values.selectedModel)) {
                actions.setSelectedModel('')
            }
            // Auto-select the first available model if none selected
            if (!values.selectedModel && availableModels.length > 0) {
                // When using PostHog key (no selectedKeyId), pick first PostHog-available model
                if (!values.selectedKeyId) {
                    const firstPostHogModel = availableModels.find((m: AvailableModel) => m.posthog_available)
                    if (firstPostHogModel) {
                        actions.setSelectedModel(firstPostHogModel.id)
                    }
                } else {
                    actions.setSelectedModel(availableModels[0].id)
                }
            }
        },
    })),

    selectors({
        isNewEvaluation: [(_, props) => [props.evaluationId], (evaluationId: string) => evaluationId === 'new'],

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

        providerKeysByProvider: [
            (s) => [s.providerKeys],
            (providerKeys: LLMProviderKey[]) => {
                const byProvider: Record<LLMProvider, LLMProviderKey[]> = {
                    openai: [],
                    anthropic: [],
                    gemini: [],
                }
                for (const key of providerKeys) {
                    if (key.provider in byProvider) {
                        byProvider[key.provider as LLMProvider].push(key)
                    }
                }
                return byProvider
            },
        ],

        keysForSelectedProvider: [
            (s) => [s.providerKeysByProvider, s.selectedProvider],
            (providerKeysByProvider: Record<LLMProvider, LLMProviderKey[]>, selectedProvider: LLMProvider) =>
                providerKeysByProvider[selectedProvider] || [],
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

        breadcrumbs: [
            (s) => [s.evaluation],
            (evaluation): Breadcrumb[] => [
                {
                    name: 'LLM Analytics',
                    path: urls.llmAnalyticsDashboard(),
                    key: 'LLMAnalytics',
                    iconType: 'llm_analytics',
                },
                {
                    name: 'Evaluations',
                    path: urls.llmAnalyticsEvaluations(),
                    key: 'LLMAnalyticsEvaluations',
                    iconType: 'llm_analytics',
                },
                {
                    name: evaluation?.name || 'New Evaluation',
                    key: 'LLMAnalyticsEvaluationEdit',
                },
            ],
        ],
    }),

    urlToAction(({ actions, props }) => ({
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
        actions.loadEvaluation()
        if (props.evaluationId !== 'new') {
            actions.loadEvaluationRuns()
        }
    }),
])
