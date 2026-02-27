import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiError } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { byokModelPickerLogic, type ModelOption } from '../byokModelPickerLogic'
import {
    LLMProviderKey,
    llmProviderKeysLogic,
    normalizeLLMProvider,
    providerSortIndex,
} from '../settings/llmProviderKeysLogic'
import type { llmPlaygroundModelLogicType } from './llmPlaygroundModelLogicType'
import { llmPlaygroundPromptsLogic, type PromptConfig } from './llmPlaygroundPromptsLogic'
import {
    isTraceLikeSelection,
    matchClosestModel,
    matchClosestModelOption,
    resolveProviderKeyForPrompt,
    resolveTraceModelSelection,
} from './playgroundModelMatching'

export {
    isTraceLikeSelection,
    matchClosestModel,
    matchClosestModelOption,
    resolveProviderKeyForPrompt,
    resolveTraceModelSelection,
} from './playgroundModelMatching'

export const llmPlaygroundModelLogic = kea<llmPlaygroundModelLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'playground', 'llmPlaygroundModelLogic']),

    connect(() => ({
        values: [
            llmPlaygroundPromptsLogic,
            [
                'promptConfigs',
                'activePromptConfig',
                'pendingTargetModel',
                'pendingTargetProvider',
                'pendingTargetIsTrace',
            ],
            byokModelPickerLogic,
            ['byokModels', 'byokModelsLoading', 'hasByokKeys'],
            llmProviderKeysLogic,
            ['providerKeys', 'providerKeysLoading'],
        ],
        actions: [
            llmPlaygroundPromptsLogic,
            ['setupPlaygroundFromEvent', 'setModel', 'setPromptConfigs', 'clearPendingTargetModel'],
            byokModelPickerLogic,
            ['loadByokModelsSuccess', 'loadByokModelsFailure'],
            llmProviderKeysLogic,
            ['loadProviderKeys', 'loadProviderKeysSuccess', 'loadProviderKeysFailure'],
        ],
    })),

    actions({
        setActiveProviderKeyId: (id: string | null) => ({ id }),
    }),

    reducers({
        modelOptionsErrorStatus: [
            null as number | null,
            {
                loadModelOptions: () => null,
                loadModelOptionsSuccess: () => null,
                loadModelOptionsFailure: (_: number | null, { error }: { error: unknown }) => {
                    if (error instanceof ApiError) {
                        return error.status ?? null
                    }
                    return null
                },
            },
        ],
        activeProviderKeyId: [
            null as string | null,
            {
                setActiveProviderKeyId: (_: string | null, { id }: { id: string | null }) => id,
            },
        ],
        providerKeysSettled: [
            false as boolean,
            {
                loadProviderKeys: () => false,
                loadProviderKeysSuccess: () => true,
                loadProviderKeysFailure: () => true,
            },
        ],
        byokModelsSettled: [
            false as boolean,
            {
                loadProviderKeys: () => false,
                loadProviderKeysSuccess: (_: boolean, { providerKeys }: { providerKeys: LLMProviderKey[] }) =>
                    !providerKeys.some((key) => key.state === 'ok'),
                loadByokModelsSuccess: () => true,
                loadByokModelsFailure: () => true,
            },
        ],
    }),

    loaders(({ values }) => ({
        modelOptions: {
            __default: [] as ModelOption[],
            loadModelOptions: async () => {
                const teamId = teamLogic.values.currentTeamId

                if (teamId) {
                    try {
                        const config = (await api.get(
                            `/api/environments/${teamId}/llm_analytics/evaluation_config/`
                        )) as { active_provider_key: { id: string } | null }
                        llmPlaygroundModelLogic.actions.setActiveProviderKeyId(config?.active_provider_key?.id ?? null)
                    } catch (e) {
                        console.warn('Failed to load evaluation config', e)
                    }
                }

                const trialModels = (await api.get('/api/llm_proxy/models/')) as ModelOption[]
                const options = trialModels ?? []
                const pendingTargetModel = values.pendingTargetModel

                const normalizedPrompts = values.promptConfigs.map((prompt, index) => {
                    if (index === 0 && pendingTargetModel) {
                        return prompt
                    }
                    if (values.hasByokKeys && prompt.selectedProviderKeyId) {
                        return prompt
                    }

                    const closestMatch = matchClosestModel(prompt.model, options)
                    if (prompt.model === closestMatch) {
                        return prompt
                    }
                    return {
                        ...prompt,
                        model: closestMatch,
                        selectedProviderKeyId: null,
                    }
                })

                const changed = normalizedPrompts.some((prompt, index) => prompt !== values.promptConfigs[index])
                if (changed) {
                    llmPlaygroundModelLogic.actions.setPromptConfigs(normalizedPrompts)
                }

                return options
            },
        },
    })),

    selectors({
        effectiveModelOptions: [
            (s) => [s.hasByokKeys, s.byokModels, s.modelOptions],
            (hasByokKeys: boolean, byokModels: ModelOption[], modelOptions: ModelOption[]): ModelOption[] =>
                hasByokKeys && byokModels.length > 0 ? byokModels : modelOptions,
        ],
        allModelOptions: [
            (s) => [s.modelOptions, s.byokModels],
            (modelOptions: ModelOption[], byokModels: ModelOption[]): ModelOption[] => [...modelOptions, ...byokModels],
        ],
        groupedModelOptions: [
            (s) => [s.modelOptions],
            (modelOptions: ModelOption[]) => {
                const options = Array.isArray(modelOptions) ? modelOptions : []
                const byProvider: Record<string, ModelOption[]> = {}

                for (const option of options) {
                    const provider = option.provider || 'Unknown'
                    if (!byProvider[provider]) {
                        byProvider[provider] = []
                    }
                    byProvider[provider].push(option)
                }

                return Object.entries(byProvider)
                    .sort(([a], [b]) => providerSortIndex(a) - providerSortIndex(b))
                    .map(([provider, providerModels]) => ({
                        title: provider,
                        options: providerModels.map((option) => ({
                            label: option.name,
                            value: option.id,
                            tooltip: option.description || `Provider: ${option.provider}`,
                        })),
                    }))
            },
        ],
        providerKeyForCurrentModel: [
            (s) => [s.activePromptConfig, s.effectiveModelOptions, s.providerKeys],
            (
                activePromptConfig: PromptConfig,
                modelOptions: ModelOption[],
                providerKeys: LLMProviderKey[]
            ): LLMProviderKey | null => resolveProviderKeyForPrompt(activePromptConfig, modelOptions, providerKeys),
        ],
        hasProviderKey: [(s) => [s.providerKeyForCurrentModel], (key: LLMProviderKey | null): boolean => key !== null],
    }),

    listeners(({ actions, values }) => {
        const applyTraceSelection = (targetModel: string, promptId: string, provider: string | null): void => {
            const { resolvedModelId, providerKeyId } = resolveTraceModelSelection(
                targetModel,
                provider,
                values.allModelOptions,
                values.providerKeys
            )
            actions.setModel(resolvedModelId, providerKeyId, promptId)
        }

        const applyPendingTraceSelection = (targetModel: string): void => {
            const promptId = values.promptConfigs[0]?.id
            if (!promptId) {
                actions.clearPendingTargetModel()
                return
            }
            applyTraceSelection(targetModel, promptId, values.pendingTargetProvider)
            actions.clearPendingTargetModel()
        }

        return {
            loadModelOptionsSuccess: () => {
                const targetModelForFirstPrompt = values.pendingTargetModel
                if (!targetModelForFirstPrompt) {
                    return
                }

                if (!values.providerKeysSettled || !values.byokModelsSettled) {
                    return
                }

                if (values.pendingTargetIsTrace) {
                    applyPendingTraceSelection(targetModelForFirstPrompt)
                    return
                }

                const normalizedPrompts = values.promptConfigs.map((prompt: PromptConfig, index: number) => {
                    const targetModel = index === 0 ? targetModelForFirstPrompt : prompt.model
                    const matchedModel = matchClosestModelOption(
                        targetModel,
                        values.effectiveModelOptions,
                        values.providerKeys
                    )
                    return {
                        ...prompt,
                        model:
                            index === 0
                                ? (matchedModel?.id ?? targetModelForFirstPrompt)
                                : (matchedModel?.id ?? matchClosestModel(targetModel, values.effectiveModelOptions)),
                        selectedProviderKeyId: matchedModel?.providerKeyId ?? prompt.selectedProviderKeyId,
                    }
                })

                actions.setPromptConfigs(normalizedPrompts)
                actions.clearPendingTargetModel()
            },
            loadByokModelsSuccess: ({ byokModels }: { byokModels: ModelOption[] }) => {
                if (byokModels.length === 0) {
                    return
                }

                const targetModelForFirstPrompt = values.pendingTargetModel
                if (targetModelForFirstPrompt && values.pendingTargetIsTrace) {
                    applyPendingTraceSelection(targetModelForFirstPrompt)
                    return
                }
                const normalizedPrompts = values.promptConfigs.map((prompt: PromptConfig, index: number) => {
                    const targetModel =
                        index === 0 && targetModelForFirstPrompt ? targetModelForFirstPrompt : prompt.model
                    const matchedModel = matchClosestModelOption(targetModel, byokModels, values.providerKeys)
                    return {
                        ...prompt,
                        model:
                            index === 0 && targetModelForFirstPrompt
                                ? (matchedModel?.id ?? targetModelForFirstPrompt)
                                : (matchedModel?.id ?? matchClosestModel(targetModel, byokModels)),
                        selectedProviderKeyId: matchedModel?.providerKeyId ?? prompt.selectedProviderKeyId,
                    }
                })

                actions.setPromptConfigs(normalizedPrompts)
                actions.clearPendingTargetModel()
            },
            setupPlaygroundFromEvent: ({ payload }: { payload: { model?: string; provider?: string } }) => {
                const { model, provider } = payload
                const currentPrompt = values.promptConfigs[0]
                const promptId = currentPrompt?.id
                if (!promptId || !model) {
                    return
                }

                if (!values.providerKeysSettled || !values.byokModelsSettled) {
                    return
                }

                const traceLikeSelection = isTraceLikeSelection(model, provider)
                if (traceLikeSelection) {
                    const { resolvedModelId, providerKeyId } = resolveTraceModelSelection(
                        model,
                        normalizeLLMProvider(provider),
                        values.allModelOptions,
                        values.providerKeys
                    )
                    actions.setModel(resolvedModelId, providerKeyId, promptId)
                } else {
                    const matchedModel = matchClosestModelOption(
                        model,
                        values.effectiveModelOptions,
                        values.providerKeys
                    )
                    actions.setModel(matchedModel?.id ?? model, matchedModel?.providerKeyId, promptId)
                }
                actions.clearPendingTargetModel()
            },
        }
    }),

    afterMount(({ actions }) => {
        actions.loadModelOptions()
    }),
])
