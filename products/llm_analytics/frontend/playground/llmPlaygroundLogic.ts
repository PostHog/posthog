import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { byokModelPickerLogic, type ModelOption } from '../byokModelPickerLogic'
import { llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import type { llmPlaygroundLogicType } from './llmPlaygroundLogicType'
import { matchClosestModel, modelLifecycleListeners, modelReducers, modelSelectors } from './llmPlaygroundModelLogic'
import { promptActions, promptReducers, promptSelectors } from './llmPlaygroundPromptsLogic'
import { runListeners, runReducers, type ComparisonItem } from './llmPlaygroundRunLogic'

export type { MessageRole, Message, PromptConfig, ReasoningLevel } from './llmPlaygroundPromptsLogic'
export type { ComparisonItem } from './llmPlaygroundRunLogic'

export const llmPlaygroundLogic = kea<llmPlaygroundLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'llmPlaygroundLogic']),

    connect(() => ({
        values: [
            byokModelPickerLogic,
            ['byokModels', 'byokModelsLoading', 'hasByokKeys'],
            llmProviderKeysLogic,
            ['providerKeys', 'providerKeysLoading'],
        ],
        actions: [
            byokModelPickerLogic,
            ['loadByokModelsSuccess', 'loadByokModelsFailure'],
            llmProviderKeysLogic,
            ['loadProviderKeys', 'loadProviderKeysSuccess', 'loadProviderKeysFailure'],
        ],
    })),

    actions({
        ...promptActions,
        submitPrompt: true,
        finishSubmitPrompt: true,
        addToComparison: (item: ComparisonItem) => ({ item }),
        updateComparisonItem: (id: string, payload: Partial<ComparisonItem>) => ({ id, payload }),
        setRateLimited: (retryAfterSeconds: number) => ({ retryAfterSeconds }),
        setSubscriptionRequired: (required: boolean) => ({ required }),
        setActiveProviderKeyId: (id: string | null) => ({ id }),
        clearPendingTargetModel: true,
    }),

    reducers({
        ...promptReducers,
        ...modelReducers,
        ...runReducers,
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
                        llmPlaygroundLogic.actions.setActiveProviderKeyId(config?.active_provider_key?.id ?? null)
                    } catch (e) {
                        console.warn('Failed to load evaluation config', e)
                    }
                }

                const trialModels = (await api.get('/api/llm_proxy/models/')) as ModelOption[]
                const options = trialModels ?? []
                const pendingTargetModel = values.pendingTargetModel

                const normalizedPrompts = values.promptConfigs.map((prompt, index) => {
                    // Don't auto-normalize the first prompt while we're still resolving a pending target model.
                    if (index === 0 && pendingTargetModel) {
                        return prompt
                    }
                    // Don't normalize trial-model IDs over a BYOK-resolved prompt.
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
                    llmPlaygroundLogic.actions.setPromptConfigs(normalizedPrompts)
                }

                return options
            },
        },
    })),

    listeners(({ actions, values }) => {
        return {
            ...modelLifecycleListeners({ actions, values }),
            ...runListeners({ actions, values }),
        }
    }),
    afterMount(({ actions }) => {
        actions.loadModelOptions()
    }),

    selectors({
        ...promptSelectors,
        ...modelSelectors,
    }),
])
