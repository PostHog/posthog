import { afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { modelPickerLogicType } from './modelPickerLogicType'
import {
    type LLMProvider,
    LLMProviderKey,
    LLM_PROVIDER_LABELS,
    llmProviderKeysLogic,
    providerSortIndex,
    toLLMProvider,
} from './settings/llmProviderKeysLogic'
import { isUnhealthyProviderKeyState, providerKeyStateSuffix } from './settings/providerKeyStateUtils'

export interface ModelOption {
    id: string
    name: string
    provider: string
    description: string
    providerKeyId?: string
    isRecommended?: boolean
}

export interface ProviderModelGroup {
    provider: LLMProvider
    providerKeyId: string
    label: string
    models: ModelOption[]
    disabled?: boolean
}

export function buildTrialProviderModelGroups(models: ModelOption[]): ProviderModelGroup[] {
    const byProvider: Record<string, ModelOption[]> = {}
    for (const model of models) {
        const provider = model.provider || 'Unknown'
        if (!byProvider[provider]) {
            byProvider[provider] = []
        }
        byProvider[provider].push(model)
    }
    return Object.entries(byProvider)
        .sort(([a], [b]) => providerSortIndex(a) - providerSortIndex(b))
        .flatMap(([provider, providerModels]) => {
            const llmProvider = toLLMProvider(provider)
            if (!llmProvider) {
                return []
            }
            return [
                {
                    provider: llmProvider,
                    providerKeyId: `trial:${llmProvider}`,
                    label: LLM_PROVIDER_LABELS[llmProvider] ?? provider,
                    models: providerModels,
                },
            ]
        })
}

export const modelPickerLogic = kea<modelPickerLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'modelPickerLogic']),

    connect(() => ({
        values: [llmProviderKeysLogic, ['providerKeys', 'providerKeysLoading']],
        actions: [
            llmProviderKeysLogic,
            ['loadProviderKeysSuccess', 'createProviderKeySuccess', 'updateProviderKeySuccess'],
        ],
    })),

    loaders(({ values }) => ({
        byokModels: {
            __default: [] as ModelOption[],
            loadByokModels: async (): Promise<ModelOption[]> => {
                const validKeys = values.providerKeys.filter((k: LLMProviderKey) => k.state === 'ok')
                if (validKeys.length === 0) {
                    return []
                }
                const results = await Promise.all(
                    validKeys.map(async (key: LLMProviderKey) => {
                        try {
                            const rawModels = (await api.get(
                                `/api/llm_proxy/models/?provider_key_id=${encodeURIComponent(key.id)}`
                            )) as (Omit<ModelOption, 'providerKeyId' | 'isRecommended'> & {
                                is_recommended?: boolean
                            })[]
                            return rawModels.map((m) => ({
                                id: m.id,
                                name: m.name,
                                provider: m.provider,
                                description: m.description,
                                isRecommended: m.is_recommended ?? false,
                                providerKeyId: key.id,
                            }))
                        } catch {
                            return []
                        }
                    })
                )
                const dedupedModels = new Map<string, ModelOption>()
                for (const models of results) {
                    for (const model of models) {
                        const dedupeKey = `${model.providerKeyId ?? ''}::${model.id}`
                        if (!dedupedModels.has(dedupeKey)) {
                            dedupedModels.set(dedupeKey, model)
                        }
                    }
                }
                return Array.from(dedupedModels.values())
            },
        },
        trialModels: {
            __default: [] as ModelOption[],
            loadTrialModels: async (): Promise<ModelOption[]> => {
                const rawModels = (await api.get('/api/llm_proxy/models/')) as (Omit<ModelOption, 'isRecommended'> & {
                    is_recommended?: boolean
                })[]
                return (rawModels ?? []).map((m) => ({
                    id: m.id,
                    name: m.name,
                    provider: m.provider,
                    description: m.description,
                    isRecommended: m.is_recommended ?? false,
                }))
            },
        },
    })),

    listeners(({ actions }) => ({
        // Refresh BYOK models whenever provider keys change so the
        // model picker immediately reflects newly valid options.
        loadProviderKeysSuccess: () => {
            actions.loadByokModels()
        },
        createProviderKeySuccess: () => {
            actions.loadByokModels()
        },
        updateProviderKeySuccess: () => {
            actions.loadByokModels()
        },
    })),

    afterMount(({ actions, values }) => {
        actions.loadTrialModels()
        if (values.providerKeys.length > 0) {
            actions.loadByokModels()
        }
    }),

    selectors({
        hasByokKeys: [
            (s) => [s.providerKeys],
            (providerKeys: LLMProviderKey[]): boolean => providerKeys.some((k) => k.state === 'ok'),
        ],
        trialProviderModelGroups: [
            (s) => [s.trialModels],
            (trialModels: ModelOption[]): ProviderModelGroup[] =>
                buildTrialProviderModelGroups(Array.isArray(trialModels) ? trialModels : []),
        ],
        providerModelGroups: [
            (s) => [s.byokModels, s.providerKeys],
            (byokModels: ModelOption[], providerKeys: LLMProviderKey[]): ProviderModelGroup[] => {
                const byKeyId: Record<string, ModelOption[]> = {}
                for (const model of byokModels) {
                    const keyId = model.providerKeyId ?? ''
                    if (!byKeyId[keyId]) {
                        byKeyId[keyId] = []
                    }
                    byKeyId[keyId].push(model)
                }

                const keysPerProvider: Record<string, number> = {}
                for (const key of providerKeys) {
                    keysPerProvider[key.provider] = (keysPerProvider[key.provider] ?? 0) + 1
                }

                const groups: ProviderModelGroup[] = []
                for (const key of providerKeys) {
                    const models = byKeyId[key.id] ?? []
                    // Show invalid/error keys as disabled entries with a state suffix.
                    // Keys in 'unknown' state are skipped — they haven't been validated yet.
                    if (isUnhealthyProviderKeyState(key.state) && models.length === 0) {
                        const providerLabel = LLM_PROVIDER_LABELS[key.provider] ?? key.provider
                        const suffix = providerKeyStateSuffix(key.state)
                        const label =
                            (keysPerProvider[key.provider] ?? 0) > 1
                                ? `${providerLabel} (${key.name})${suffix}`
                                : `${providerLabel}${suffix}`
                        groups.push({
                            provider: key.provider,
                            providerKeyId: key.id,
                            label,
                            models: [],
                            disabled: true,
                        })
                        continue
                    }

                    if (models.length === 0) {
                        continue
                    }

                    const providerLabel = LLM_PROVIDER_LABELS[key.provider] ?? key.provider
                    const label =
                        (keysPerProvider[key.provider] ?? 0) > 1 ? `${providerLabel} (${key.name})` : providerLabel

                    groups.push({ provider: key.provider, providerKeyId: key.id, label, models })
                }

                return groups.sort((a, b) => {
                    const providerDiff = providerSortIndex(a.provider) - providerSortIndex(b.provider)
                    if (providerDiff !== 0) {
                        return providerDiff
                    }
                    return a.label.localeCompare(b.label)
                })
            },
        ],
    }),
])
