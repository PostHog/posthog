import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { byokModelPickerLogicType } from './byokModelPickerLogicType'
import { ModelOption, ProviderModelGroup } from './llmAnalyticsPlaygroundLogic'
import { LLMProvider, LLMProviderKey, LLM_PROVIDER_LABELS, llmProviderKeysLogic } from './settings/llmProviderKeysLogic'
import { isUnhealthyProviderKeyState, providerKeyStateSuffix } from './settings/providerKeyStateUtils'

export const byokModelPickerLogic = kea<byokModelPickerLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'byokModelPickerLogic']),

    connect(() => ({
        values: [llmProviderKeysLogic, ['providerKeys', 'providerKeysLoading']],
        actions: [llmProviderKeysLogic, ['loadProviderKeysSuccess']],
    })),

    actions({
        setSearch: (search: string) => ({ search }),
        clearSearch: true,
        toggleProviderExpanded: (providerKeyId: string) => ({ providerKeyId }),
    }),

    reducers({
        search: ['' as string, { setSearch: (_, { search }) => search, clearSearch: () => '' }],
        expandedProviders: [
            {} as Record<string, boolean>,
            {
                toggleProviderExpanded: (state, { providerKeyId }) => ({
                    ...state,
                    [providerKeyId]: !state[providerKeyId],
                }),
            },
        ],
    }),

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
    })),

    listeners(({ actions }) => ({
        loadProviderKeysSuccess: () => {
            actions.loadByokModels()
        },
    })),

    afterMount(({ actions, values }) => {
        if (values.providerKeys.length > 0) {
            actions.loadByokModels()
        }
    }),

    selectors({
        hasByokKeys: [
            (s) => [s.providerKeys],
            (providerKeys: LLMProviderKey[]): boolean => providerKeys.some((k) => k.state === 'ok'),
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

                return groups.sort((a, b) => a.label.localeCompare(b.label))
            },
        ],
        selectedProviderForModel: [
            (s) => [s.providerModelGroups],
            (groups: ProviderModelGroup[]) =>
                (model: string, providerKeyId: string | null): LLMProvider | null => {
                    const group = groups.find(
                        (g) => g.providerKeyId === providerKeyId && g.models.some((m) => m.id === model)
                    )
                    return group?.provider ?? null
                },
        ],
        filteredProviderModelGroups: [
            (s) => [s.providerModelGroups, s.search],
            (groups: ProviderModelGroup[], search: string): ProviderModelGroup[] => {
                if (!search) {
                    return groups
                }
                const lower = search.toLowerCase()
                return groups
                    .map((group) => ({
                        ...group,
                        models: group.models.filter(
                            (m) => m.name.toLowerCase().includes(lower) || m.id.toLowerCase().includes(lower)
                        ),
                    }))
                    .filter((group) => group.models.length > 0)
            },
        ],
        isProviderExpanded: [
            (s) => [s.expandedProviders],
            (expandedProviders: Record<string, boolean>) =>
                (providerKeyId: string): boolean =>
                    !!expandedProviders[providerKeyId],
        ],
        hasExplicitExpandState: [
            (s) => [s.expandedProviders],
            (expandedProviders: Record<string, boolean>) =>
                (providerKeyId: string): boolean =>
                    providerKeyId in expandedProviders,
        ],
    }),
])
