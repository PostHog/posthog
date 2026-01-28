import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { llmProviderKeysLogicType } from './llmProviderKeysLogicType'

export type LLMProviderKeyState = 'unknown' | 'ok' | 'invalid' | 'error'
export type LLMProvider = 'openai' | 'anthropic' | 'gemini'

export const LLM_PROVIDER_LABELS: Record<LLMProvider, string> = {
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    gemini: 'Google Gemini',
}

export interface LLMProviderKey {
    id: string
    provider: LLMProvider
    name: string
    state: LLMProviderKeyState
    error_message: string | null
    api_key_masked: string
    created_at: string
    created_by: {
        id: number
        uuid: string
        distinct_id: string
        first_name: string
        last_name: string
        email: string
    } | null
    last_used_at: string | null
}

export interface EvaluationConfig {
    trial_eval_limit: number
    trial_evals_used: number
    trial_evals_remaining: number
    active_provider_key: LLMProviderKey | null
    created_at: string
    updated_at: string
}

export interface CreateLLMProviderKeyPayload {
    provider: LLMProvider
    name: string
    api_key: string
}

export interface UpdateLLMProviderKeyPayload {
    name?: string
    api_key?: string
}

export interface KeyValidationResult {
    state: LLMProviderKeyState
    error_message: string | null
}

export const llmProviderKeysLogic = kea<llmProviderKeysLogicType>([
    path(['products', 'llm_analytics', 'settings', 'llmProviderKeysLogic']),

    actions({
        clearPreValidation: true,
        setNewKeyModalOpen: (open: boolean) => ({ open }),
        setEditingKey: (key: LLMProviderKey | null) => ({ key }),
    }),

    reducers({
        newKeyModalOpen: [
            false,
            {
                setNewKeyModalOpen: (_, { open }) => open,
            },
        ],
        editingKey: [
            null as LLMProviderKey | null,
            {
                setEditingKey: (_, { key }) => key,
            },
        ],
        validatingKeyId: [
            null as string | null,
            {
                validateProviderKey: (_, { id }) => id,
                validateProviderKeySuccess: () => null,
                validateProviderKeyFailure: () => null,
            },
        ],
        preValidationResult: [
            null as KeyValidationResult | null,
            {
                preValidateKeySuccess: (_, { preValidationResult }) => preValidationResult,
                preValidateKeyFailure: () => ({ state: 'error' as const, error_message: 'Validation request failed' }),
                clearPreValidation: () => null,
                setNewKeyModalOpen: () => null,
                setEditingKey: () => null,
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        preValidationResult: [
            null as KeyValidationResult | null,
            {
                preValidateKey: async ({
                    apiKey,
                    provider,
                }: {
                    apiKey: string
                    provider: LLMProvider
                }): Promise<KeyValidationResult> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return { state: 'error', error_message: 'No team selected' }
                    }
                    const response = await api.create(
                        `/api/environments/${teamId}/llm_analytics/provider_key_validations/`,
                        { api_key: apiKey, provider }
                    )
                    return response
                },
            },
        ],
        evaluationConfig: [
            null as EvaluationConfig | null,
            {
                loadEvaluationConfig: async (): Promise<EvaluationConfig | null> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    return await api.get(`/api/environments/${teamId}/llm_analytics/evaluation_config/`)
                },
            },
        ],
        providerKeys: [
            [] as LLMProviderKey[],
            {
                loadProviderKeys: async (): Promise<LLMProviderKey[]> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return []
                    }
                    const response = await api.get(`/api/environments/${teamId}/llm_analytics/provider_keys/`)
                    return response.results
                },
                createProviderKey: async ({
                    payload,
                }: {
                    payload: CreateLLMProviderKeyPayload
                }): Promise<LLMProviderKey[]> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return values.providerKeys
                    }
                    const response = await api.create(
                        `/api/environments/${teamId}/llm_analytics/provider_keys/`,
                        payload
                    )
                    actions.setNewKeyModalOpen(false)
                    return [...values.providerKeys, response]
                },
                updateProviderKey: async ({
                    id,
                    payload,
                }: {
                    id: string
                    payload: UpdateLLMProviderKeyPayload
                }): Promise<LLMProviderKey[]> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return values.providerKeys
                    }
                    const response = await api.update(
                        `/api/environments/${teamId}/llm_analytics/provider_keys/${id}/`,
                        payload
                    )
                    actions.setEditingKey(null)
                    return values.providerKeys.map((key: LLMProviderKey) => (key.id === id ? response : key))
                },
                deleteProviderKey: async ({ id }: { id: string }): Promise<LLMProviderKey[]> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return values.providerKeys
                    }
                    await api.delete(`/api/environments/${teamId}/llm_analytics/provider_keys/${id}/`)
                    // If deleted key was active, reload config to reflect change
                    if (values.evaluationConfig?.active_provider_key?.id === id) {
                        actions.loadEvaluationConfig()
                    }
                    return values.providerKeys.filter((key: LLMProviderKey) => key.id !== id)
                },
                validateProviderKey: async ({ id }: { id: string }): Promise<LLMProviderKey[]> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return values.providerKeys
                    }
                    const response = await api.create(
                        `/api/environments/${teamId}/llm_analytics/provider_keys/${id}/validate/`,
                        {}
                    )
                    if (response.state !== 'ok') {
                        lemonToast.error(`Key validation failed: ${response.error_message || 'Unknown error'}`)
                    }
                    return values.providerKeys.map((key: LLMProviderKey) => (key.id === id ? response : key))
                },
            },
        ],
    })),

    selectors({
        trialEvalsUsed: [
            (s) => [s.evaluationConfig],
            (evaluationConfig: EvaluationConfig | null) => evaluationConfig?.trial_evals_used ?? 0,
        ],
        trialEvalLimit: [
            (s) => [s.evaluationConfig],
            (evaluationConfig: EvaluationConfig | null) => evaluationConfig?.trial_eval_limit ?? 100,
        ],
        trialEvalsRemaining: [
            (s) => [s.evaluationConfig],
            (evaluationConfig: EvaluationConfig | null) => evaluationConfig?.trial_evals_remaining ?? 0,
        ],
        isTrialLimitReached: [
            (s) => [s.evaluationConfig],
            (evaluationConfig: EvaluationConfig | null) =>
                evaluationConfig !== null &&
                evaluationConfig.active_provider_key === null &&
                evaluationConfig.trial_evals_remaining <= 0,
        ],
    }),

    listeners(() => ({
        loadProviderKeysFailure: ({ error }) => {
            lemonToast.error(`Failed to load API keys: ${error || 'Unknown error'}`)
        },
        loadEvaluationConfigFailure: ({ error }) => {
            lemonToast.error(`Failed to load evaluation config: ${error || 'Unknown error'}`)
        },
        createProviderKeyFailure: ({ error }) => {
            lemonToast.error(`Failed to create API key: ${error || 'Unknown error'}`)
        },
        updateProviderKeyFailure: ({ error }) => {
            lemonToast.error(`Failed to update API key: ${error || 'Unknown error'}`)
        },
        deleteProviderKeyFailure: ({ error }) => {
            lemonToast.error(`Failed to delete API key: ${error || 'Unknown error'}`)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadProviderKeys()
        actions.loadEvaluationConfig()
    }),
])
