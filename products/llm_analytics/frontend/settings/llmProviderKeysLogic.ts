import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { llmProviderKeysLogicType } from './llmProviderKeysLogicType'

export type LLMProviderKeyState = 'unknown' | 'ok' | 'invalid' | 'error'
export type LLMProvider =
    | 'openai'
    | 'anthropic'
    | 'gemini'
    | 'openrouter'
    | 'fireworks'
    | 'azure_openai'
    | 'together_ai'

/** Default Azure OpenAI API version — keep in sync with backend DEFAULT_API_VERSION. */
export const DEFAULT_AZURE_API_VERSION = '2024-10-21'

export const LLM_PROVIDER_LABELS: Record<LLMProvider, string> = {
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    gemini: 'Google Gemini',
    openrouter: 'OpenRouter',
    fireworks: 'Fireworks',
    azure_openai: 'Azure OpenAI',
    together_ai: 'Together AI',
}

const LLM_PROVIDERS = new Set<string>(Object.keys(LLM_PROVIDER_LABELS))

export function isLLMProvider(value: string): value is LLMProvider {
    return LLM_PROVIDERS.has(value)
}

/** Normalize a raw provider string to an LLMProvider, or null if unrecognized. */
export function toLLMProvider(raw: string): LLMProvider | null {
    const normalized = raw.toLowerCase()
    if (isLLMProvider(normalized)) {
        return normalized
    }
    console.error(`[LLM Analytics] Unknown LLM provider: "${raw}"`)
    return null
}

const PROVIDER_ORDER = Object.keys(LLM_PROVIDER_LABELS) as LLMProvider[]

/** Sort index for a provider string. Unknown providers sort last. */
export function providerSortIndex(provider: string): number {
    const normalized = toLLMProvider(provider)
    return normalized ? PROVIDER_ORDER.indexOf(normalized) : PROVIDER_ORDER.length
}

/** Normalize provider aliases from traces/config into canonical LLMProvider keys. */
export function normalizeLLMProvider(provider: string | undefined): LLMProvider | null {
    if (!provider) {
        return null
    }

    const normalized = provider.trim().toLowerCase()
    if (normalized === 'google' || normalized === 'google-ai-studio') {
        return 'gemini'
    }
    if (normalized === 'azure_openai' || normalized === 'azure-openai' || normalized === 'azure openai') {
        return 'azure_openai'
    }
    if (normalized === 'together' || normalized === 'together ai' || normalized === 'together-ai') {
        return 'together_ai'
    }

    return normalized in LLM_PROVIDER_LABELS ? (normalized as LLMProvider) : null
}

export interface LLMProviderKey {
    id: string
    provider: LLMProvider
    name: string
    state: LLMProviderKeyState
    error_message: string | null
    api_key_masked: string
    azure_endpoint_display: string | null
    api_version_display: string | null
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

/** Canonical provider key ordering: provider order, then key name, then id. */
export function sortProviderKeys(keys: LLMProviderKey[]): LLMProviderKey[] {
    return [...keys].sort((a, b) => {
        const providerDiff = providerSortIndex(a.provider) - providerSortIndex(b.provider)
        if (providerDiff !== 0) {
            return providerDiff
        }

        const nameDiff = (a.name ?? '').localeCompare(b.name ?? '', undefined, { sensitivity: 'base' })
        if (nameDiff !== 0) {
            return nameDiff
        }

        return a.id.localeCompare(b.id)
    })
}

export function sortedUsableProviderKeyIds(keys: LLMProviderKey[]): string[] {
    return sortProviderKeys(keys)
        .filter((key) => key.state !== 'invalid')
        .map((key) => key.id)
}

export function firstUsableProviderKeyIdForProvider(
    provider: string | undefined,
    keys: LLMProviderKey[]
): string | null {
    const normalizedProvider = normalizeLLMProvider(provider)
    if (!normalizedProvider) {
        return null
    }

    return (
        sortProviderKeys(keys).find((key) => key.state !== 'invalid' && key.provider === normalizedProvider)?.id ?? null
    )
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
    set_as_active?: boolean
    azure_endpoint?: string
    api_version?: string
}

export interface UpdateLLMProviderKeyPayload {
    name?: string
    api_key?: string
    azure_endpoint?: string
    api_version?: string
}

export interface KeyValidationResult {
    state: LLMProviderKeyState
    error_message: string | null
    // Form field the error should be attributed to in the UI (e.g. 'azure_endpoint', 'api_key').
    // Only set for providers that validate multiple inputs — most providers leave it null.
    error_field?: string | null
}

export interface TrialEvaluation {
    id: string
    name: string
    enabled: boolean
}

export interface DependentEvaluation {
    id: string
    name: string
    model_configuration_id: string
}

export interface AlternativeKey {
    id: string
    name: string
    provider: LLMProvider
}

export interface DependentConfigsResponse {
    evaluations: DependentEvaluation[]
    alternative_keys: AlternativeKey[]
}

export const llmProviderKeysLogic = kea<llmProviderKeysLogicType>([
    path(['products', 'llm_analytics', 'settings', 'llmProviderKeysLogic']),

    actions({
        clearPreValidation: true,
        setNewKeyModalOpen: (open: boolean) => ({ open }),
        setEditingKey: (key: LLMProviderKey | null) => ({ key }),
        setKeyToDelete: (key: LLMProviderKey | null) => ({ key }),
        confirmDelete: (replacementKeyId?: string) => ({ replacementKeyId }),
        setNewlyCreatedKey: (key: LLMProviderKey | null) => ({ key }),
        confirmAssignKey: (evaluationIds: string[], enable: boolean) => ({ evaluationIds, enable }),
        dismissAssignKey: true,
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
                clearPreValidation: () => null,
                setNewKeyModalOpen: () => null,
                setEditingKey: () => null,
            },
        ],
        keyToDelete: [
            null as LLMProviderKey | null,
            {
                setKeyToDelete: (_, { key }) => key,
                deleteProviderKeySuccess: () => null,
            },
        ],
        newlyCreatedKey: [
            null as LLMProviderKey | null,
            {
                setNewlyCreatedKey: (_, { key }) => key,
                dismissAssignKey: () => null,
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        trialEvaluations: [
            [] as TrialEvaluation[],
            {
                loadTrialEvaluations: async ({ provider }: { provider: LLMProvider }): Promise<TrialEvaluation[]> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return []
                    }
                    const response = await api.get(
                        `/api/environments/${teamId}/llm_analytics/provider_keys/trial_evaluations/?provider=${encodeURIComponent(provider)}`
                    )
                    return response.evaluations
                },
            },
        ],
        dependentConfigs: [
            null as DependentConfigsResponse | null,
            {
                loadDependentConfigs: async ({
                    keyId,
                }: {
                    keyId: string
                }): Promise<DependentConfigsResponse | null> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    return await api.get(
                        `/api/environments/${teamId}/llm_analytics/provider_keys/${keyId}/dependent_configs/`
                    )
                },
            },
        ],
        preValidationResult: [
            null as KeyValidationResult | null,
            {
                preValidateKey: async ({
                    apiKey,
                    provider,
                    azure_endpoint,
                    api_version,
                }: {
                    apiKey: string
                    provider: LLMProvider
                    azure_endpoint?: string
                    api_version?: string
                }): Promise<KeyValidationResult> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return { state: 'error', error_message: 'No team selected' }
                    }
                    try {
                        const body: Record<string, string> = { api_key: apiKey, provider }
                        if (azure_endpoint) {
                            body.azure_endpoint = azure_endpoint
                        }
                        if (api_version) {
                            body.api_version = api_version
                        }
                        const response = await api.create(
                            `/api/environments/${teamId}/llm_analytics/provider_key_validations/`,
                            body
                        )
                        return response
                    } catch (error) {
                        if (error instanceof ApiError) {
                            return {
                                state: 'error',
                                error_message: error.detail || error.data?.error || error.message,
                            }
                        }
                        if (error instanceof Error) {
                            return { state: 'error', error_message: error.message }
                        }
                        return { state: 'error', error_message: 'Validation request failed' }
                    }
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
                    actions.loadEvaluationConfig()
                    // Check if there are trial evaluations that could use this key
                    actions.setNewlyCreatedKey(response)
                    actions.loadTrialEvaluations({ provider: response.provider })
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
                deleteProviderKey: async ({
                    id,
                    replacementKeyId,
                }: {
                    id: string
                    replacementKeyId?: string
                }): Promise<LLMProviderKey[]> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return values.providerKeys
                    }
                    const url = replacementKeyId
                        ? `/api/environments/${teamId}/llm_analytics/provider_keys/${id}/?replacement_key_id=${encodeURIComponent(replacementKeyId)}`
                        : `/api/environments/${teamId}/llm_analytics/provider_keys/${id}/`
                    await api.delete(url)
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

    listeners(({ actions, values }) => ({
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
        setKeyToDelete: ({ key }) => {
            if (key) {
                actions.loadDependentConfigs({ keyId: key.id })
            }
        },
        loadTrialEvaluationsSuccess: ({ trialEvaluations }) => {
            // If no trial evaluations found, auto-dismiss the assign key modal
            if (trialEvaluations.length === 0 && values.newlyCreatedKey) {
                actions.setNewlyCreatedKey(null)
            }
        },
        confirmDelete: ({ replacementKeyId }) => {
            if (values.keyToDelete) {
                actions.deleteProviderKey({ id: values.keyToDelete.id, replacementKeyId })
            }
        },
        confirmAssignKey: async ({ evaluationIds, enable }) => {
            const key = values.newlyCreatedKey
            if (!key || evaluationIds.length === 0) {
                actions.setNewlyCreatedKey(null)
                return
            }
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                await api.create(`/api/environments/${teamId}/llm_analytics/provider_keys/${key.id}/assign/`, {
                    evaluation_ids: evaluationIds,
                    enable,
                })
                const count = evaluationIds.length
                lemonToast.success(
                    enable
                        ? `Assigned key and re-enabled ${count} evaluation${count !== 1 ? 's' : ''}`
                        : `Assigned key to ${count} evaluation${count !== 1 ? 's' : ''}`
                )
            } catch {
                lemonToast.error('Failed to assign key to evaluations')
            }
            actions.setNewlyCreatedKey(null)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadProviderKeys()
        actions.loadEvaluationConfig()
    }),
])
