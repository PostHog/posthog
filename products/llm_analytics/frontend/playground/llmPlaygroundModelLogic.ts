import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiError } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { byokModelPickerLogic, type ModelOption } from '../byokModelPickerLogic'
import {
    firstUsableProviderKeyIdForProvider,
    LLMProviderKey,
    llmProviderKeysLogic,
    normalizeLLMProvider,
    providerSortIndex,
    sortedUsableProviderKeyIds,
} from '../settings/llmProviderKeysLogic'
import type { llmPlaygroundModelLogicType } from './llmPlaygroundModelLogicType'
import { llmPlaygroundPromptsLogic, type PromptConfig } from './llmPlaygroundPromptsLogic'

interface MatchModelOption {
    id: string
    providerKeyId?: string
}

interface MatchOptions {
    scopeToNamespacePrefix: boolean
    includeCanonicalFallback: boolean
    includeDefaultFallback: boolean
}

const DEFAULT_MATCH_MODEL = 'gpt-5-mini'

const TRACE_MATCH_OPTIONS: MatchOptions = {
    scopeToNamespacePrefix: true,
    includeCanonicalFallback: true,
    includeDefaultFallback: false,
}

const DEFAULT_MATCH_OPTIONS: MatchOptions = {
    scopeToNamespacePrefix: false,
    includeCanonicalFallback: false,
    includeDefaultFallback: true,
}

function normalizeModelId(modelId: string): string {
    return modelId.trim().toLowerCase()
}

function canonicalizeModelId(modelId: string): string {
    return normalizeModelId(modelId).replace(/[^a-z0-9]/g, '')
}

function comparableModelIdVariants(modelId: string): string[] {
    const normalizedModelId = normalizeModelId(modelId)
    const segments = normalizedModelId.split('/').filter(Boolean)
    const variants: string[] = []

    for (let index = 0; index < segments.length; index++) {
        variants.push(segments.slice(index).join('/'))
    }

    if (variants.length === 0 && normalizedModelId.length > 0) {
        variants.push(normalizedModelId)
    }

    return Array.from(new Set(variants))
}

function hasComparableModelVariantMatch(
    leftModelId: string,
    rightModelId: string,
    matcher: (leftVariant: string, rightVariant: string) => boolean
): boolean {
    const leftVariants = comparableModelIdVariants(leftModelId)
    const rightVariants = comparableModelIdVariants(rightModelId)
    return leftVariants.some((leftVariant) => rightVariants.some((rightVariant) => matcher(leftVariant, rightVariant)))
}

function isSuffixEquivalentModelId(leftModelId: string, rightModelId: string): boolean {
    return (
        leftModelId === rightModelId ||
        leftModelId.endsWith(`/${rightModelId}`) ||
        rightModelId.endsWith(`/${leftModelId}`)
    )
}

function pickPreferredModelOption(
    candidates: MatchModelOption[],
    providerKeys: LLMProviderKey[]
): MatchModelOption | null {
    if (candidates.length === 0) {
        return null
    }

    const providerKeyOrder = sortedUsableProviderKeyIds(providerKeys)
    if (providerKeyOrder.length === 0) {
        return candidates[0]
    }

    const providerKeyRank = new Map(providerKeyOrder.map((keyId, index) => [keyId, index]))
    return [...candidates].sort((a, b) => {
        const aRank = a.providerKeyId
            ? (providerKeyRank.get(a.providerKeyId) ?? Number.MAX_SAFE_INTEGER)
            : Number.MAX_SAFE_INTEGER
        const bRank = b.providerKeyId
            ? (providerKeyRank.get(b.providerKeyId) ?? Number.MAX_SAFE_INTEGER)
            : Number.MAX_SAFE_INTEGER
        if (aRank !== bRank) {
            return aRank - bRank
        }
        return a.id.localeCompare(b.id)
    })[0]
}

function pickProviderKeyIdForProvider(provider: string | undefined, providerKeys: LLMProviderKey[]): string | null {
    return firstUsableProviderKeyIdForProvider(provider, providerKeys)
}

function inferProviderFromModelId(modelId: string): string | null {
    const normalizedModelId = normalizeModelId(modelId)
    const candidateProvider = normalizedModelId.split('/')[0]
    return normalizeLLMProvider(candidateProvider)
}

function resolveProviderKeyIdForTraceModel(
    modelId: string,
    provider: string | null,
    availableModels: MatchModelOption[],
    providerKeys: LLMProviderKey[]
): string | null {
    const exactMatches = availableModels.filter((model) => model.id === modelId)
    if (exactMatches.length > 0) {
        return pickPreferredModelOption(exactMatches, providerKeys)?.providerKeyId ?? null
    }

    const normalizedModelId = normalizeModelId(modelId)
    const normalizedExactMatches = availableModels.filter((model) => normalizeModelId(model.id) === normalizedModelId)
    if (normalizedExactMatches.length > 0) {
        return pickPreferredModelOption(normalizedExactMatches, providerKeys)?.providerKeyId ?? null
    }

    return pickProviderKeyIdForProvider(provider ?? inferProviderFromModelId(modelId) ?? undefined, providerKeys)
}

function getModelCandidates(
    targetModel: string,
    availableModels: MatchModelOption[],
    scopeToNamespacePrefix: boolean
): MatchModelOption[] {
    if (!scopeToNamespacePrefix) {
        return availableModels
    }

    const normalizedTarget = normalizeModelId(targetModel)
    const targetPrefix = normalizedTarget.split('/')[0]
    const scoped = availableModels.filter((model) => normalizeModelId(model.id).startsWith(`${targetPrefix}/`))
    return scoped.length > 0 ? scoped : availableModels
}

function bestPrefixMatches(targetModel: string, candidates: MatchModelOption[]): MatchModelOption[] {
    const prefixMatchesWithLength = candidates
        .map((model) => {
            const modelVariants = comparableModelIdVariants(model.id)
            const targetVariants = comparableModelIdVariants(targetModel)
            const bestPrefixLength = modelVariants.reduce((bestLength, modelVariant) => {
                const matchingVariant = targetVariants.find((targetVariant) => targetVariant.startsWith(modelVariant))
                return matchingVariant ? Math.max(bestLength, modelVariant.length) : bestLength
            }, 0)
            return { model, bestPrefixLength }
        })
        .filter((item) => item.bestPrefixLength > 0)

    if (prefixMatchesWithLength.length === 0) {
        return []
    }

    const longestPrefixLength = Math.max(...prefixMatchesWithLength.map((item) => item.bestPrefixLength))
    return prefixMatchesWithLength
        .filter((item) => item.bestPrefixLength === longestPrefixLength)
        .map((item) => item.model)
}

function bestCanonicalPrefixMatches(targetModel: string, candidates: MatchModelOption[]): MatchModelOption[] {
    const targetCanonical = canonicalizeModelId(targetModel)
    const canonicalPrefixMatchesWithLength = candidates
        .map((model) => {
            const candidateCanonical = canonicalizeModelId(model.id)
            if (!candidateCanonical) {
                return { model, prefixLength: 0 }
            }
            const prefixLength = targetCanonical.startsWith(candidateCanonical) ? candidateCanonical.length : 0
            return { model, prefixLength }
        })
        .filter((item) => item.prefixLength > 0)

    if (canonicalPrefixMatchesWithLength.length === 0) {
        return []
    }

    const longestCanonicalPrefixLength = Math.max(...canonicalPrefixMatchesWithLength.map((item) => item.prefixLength))
    return canonicalPrefixMatchesWithLength
        .filter((item) => item.prefixLength === longestCanonicalPrefixLength)
        .map((item) => item.model)
}

function findMatchedModelOption(
    targetModel: string,
    availableModels: MatchModelOption[],
    providerKeys: LLMProviderKey[],
    options: MatchOptions
): MatchModelOption | null {
    if (availableModels.length === 0) {
        return null
    }

    const candidates = getModelCandidates(targetModel, availableModels, options.scopeToNamespacePrefix)
    const normalizedTarget = normalizeModelId(targetModel)

    const exactIdMatches = candidates.filter((model) => model.id === targetModel)
    if (exactIdMatches.length > 0) {
        return pickPreferredModelOption(exactIdMatches, providerKeys)
    }

    const exactNormalizedIdMatches = candidates.filter((model) => normalizeModelId(model.id) === normalizedTarget)
    if (exactNormalizedIdMatches.length > 0) {
        return pickPreferredModelOption(exactNormalizedIdMatches, providerKeys)
    }

    const exactComparableMatches = candidates.filter((model) =>
        hasComparableModelVariantMatch(
            model.id,
            targetModel,
            (leftVariant, rightVariant) => leftVariant === rightVariant
        )
    )
    if (exactComparableMatches.length > 0) {
        return pickPreferredModelOption(exactComparableMatches, providerKeys)
    }

    const suffixEquivalentMatches = candidates.filter((model) =>
        hasComparableModelVariantMatch(model.id, targetModel, isSuffixEquivalentModelId)
    )
    if (suffixEquivalentMatches.length > 0) {
        return pickPreferredModelOption(suffixEquivalentMatches, providerKeys)
    }

    const prefixMatches = bestPrefixMatches(targetModel, candidates)
    if (prefixMatches.length > 0) {
        return pickPreferredModelOption(prefixMatches, providerKeys)
    }

    if (options.includeCanonicalFallback) {
        const targetCanonical = canonicalizeModelId(targetModel)
        const canonicalExactMatches = candidates.filter((model) => canonicalizeModelId(model.id) === targetCanonical)
        if (canonicalExactMatches.length > 0) {
            return pickPreferredModelOption(canonicalExactMatches, providerKeys)
        }

        const canonicalPrefixMatches = bestCanonicalPrefixMatches(targetModel, candidates)
        if (canonicalPrefixMatches.length > 0) {
            return pickPreferredModelOption(canonicalPrefixMatches, providerKeys)
        }
    }

    if (options.includeDefaultFallback) {
        const defaultModelMatches = candidates.filter((model) => model.id === DEFAULT_MATCH_MODEL)
        if (defaultModelMatches.length > 0) {
            return pickPreferredModelOption(defaultModelMatches, providerKeys)
        }

        return pickPreferredModelOption(candidates, providerKeys)
    }

    return null
}

export function isTraceLikeSelection(model: string | undefined, provider: string | undefined): boolean {
    return provider !== undefined || Boolean(model && model.includes('/'))
}

export function resolveTraceModelSelection(
    modelId: string,
    provider: string | null,
    availableModels: MatchModelOption[],
    providerKeys: LLMProviderKey[]
): { resolvedModelId: string; providerKeyId?: string } {
    const matchedModel = findMatchedModelOption(modelId, availableModels, providerKeys, TRACE_MATCH_OPTIONS)
    if (matchedModel) {
        return { resolvedModelId: matchedModel.id, providerKeyId: matchedModel.providerKeyId }
    }

    const providerKeyId =
        resolveProviderKeyIdForTraceModel(modelId, provider, availableModels, providerKeys) ?? undefined
    return { resolvedModelId: modelId, providerKeyId }
}

export function matchClosestModelOption(
    targetModel: string,
    availableModels: MatchModelOption[],
    providerKeys: LLMProviderKey[] = []
): MatchModelOption | null {
    return findMatchedModelOption(targetModel, availableModels, providerKeys, DEFAULT_MATCH_OPTIONS)
}

export function matchClosestModel(targetModel: string, availableModels: MatchModelOption[]): string {
    return matchClosestModelOption(targetModel, availableModels)?.id ?? DEFAULT_MATCH_MODEL
}

export function resolveProviderKeyForPrompt(
    prompt: Pick<PromptConfig, 'model' | 'selectedProviderKeyId'>,
    modelOptions: ModelOption[],
    providerKeys: LLMProviderKey[]
): LLMProviderKey | null {
    if (prompt.selectedProviderKeyId) {
        const exactMatch = providerKeys.find((k) => k.id === prompt.selectedProviderKeyId)
        if (exactMatch) {
            return exactMatch
        }
    }

    const selectedModel = modelOptions.find((m) => m.id === prompt.model)
    if (!selectedModel) {
        return null
    }

    if (selectedModel.providerKeyId) {
        const exactMatch = providerKeys.find((k) => k.id === selectedModel.providerKeyId)
        if (exactMatch) {
            return exactMatch
        }
    }

    const provider = selectedModel.provider.toLowerCase()
    return providerKeys.find((k) => k.provider === provider && k.state !== 'invalid') ?? null
}

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
