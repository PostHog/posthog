import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { byokModelPickerLogicType } from './byokModelPickerLogicType'
import { ModelOption, ProviderModelGroup } from './llmAnalyticsPlaygroundLogic'
import { LLMProviderKey, LLM_PROVIDER_LABELS, llmProviderKeysLogic } from './settings/llmProviderKeysLogic'

export const byokModelPickerLogic = kea<byokModelPickerLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'byokModelPickerLogic']),

    connect(() => ({
        values: [llmProviderKeysLogic, ['providerKeys', 'providerKeysLoading']],
        actions: [llmProviderKeysLogic, ['loadProviderKeysSuccess']],
    })),

    actions({
        setSearch: (search: string) => ({ search }),
        clearSearch: true,
    }),

    reducers({
        search: ['' as string, { setSearch: (_, { search }) => search, clearSearch: () => '' }],
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
                            const models = (await api.get(
                                `/api/llm_proxy/models/?provider_key_id=${encodeURIComponent(key.id)}`
                            )) as Omit<ModelOption, 'providerKeyId'>[]
                            return models.map((m) => ({ ...m, providerKeyId: key.id }))
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
                    if (key.state === 'ok') {
                        keysPerProvider[key.provider] = (keysPerProvider[key.provider] ?? 0) + 1
                    }
                }

                const groups: ProviderModelGroup[] = []
                for (const [keyId, models] of Object.entries(byKeyId)) {
                    const key = providerKeys.find((k) => k.id === keyId)
                    if (!key) {
                        continue
                    }
                    const providerLabel = LLM_PROVIDER_LABELS[key.provider] ?? key.provider
                    const label =
                        (keysPerProvider[key.provider] ?? 0) > 1 ? `${providerLabel} (${key.name})` : providerLabel

                    groups.push({ provider: key.provider, providerKeyId: keyId, label, models })
                }

                return groups.sort((a, b) => a.label.localeCompare(b.label))
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
    }),
])
