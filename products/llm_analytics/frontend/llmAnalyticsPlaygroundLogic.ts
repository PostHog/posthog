import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError, RateLimitError } from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { isObject, uuid } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { byokModelPickerLogic } from './byokModelPickerLogic'
import type { llmAnalyticsPlaygroundLogicType } from './llmAnalyticsPlaygroundLogicType'
import {
    LLMProvider,
    LLMProviderKey,
    llmProviderKeysLogic,
    providerSortIndex,
    sortProviderKeys,
} from './settings/llmProviderKeysLogic'
import { normalizeRole } from './utils'

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

enum NormalizedMessageRole {
    User = 'user',
    Assistant = 'assistant',
    System = 'system',
}

export type MessageRole = `${NormalizedMessageRole}`
export type ReasoningLevel = 'minimal' | 'low' | 'medium' | 'high' | null

export interface Message {
    role: MessageRole
    content: string
}

export interface PromptConfig {
    id: string
    model: string
    selectedProviderKeyId: string | null
    systemPrompt: string
    maxTokens: number | null
    thinking: boolean
    reasoningLevel: ReasoningLevel
    tools: Record<string, unknown>[] | null
    messages: Message[]
}

interface RawMessage {
    role: string
    content: unknown
}

enum InputMessageRole {
    User = 'user',
    Assistant = 'assistant',
    AI = 'ai',
    Model = 'model',
}

type ConversationRole = NormalizedMessageRole.User | NormalizedMessageRole.Assistant

function extractTextFromMessagePart(part: unknown): string | null {
    if (!isObject(part)) {
        return null
    }

    if (typeof part.text === 'string' && part.text.trim().length > 0) {
        return part.text
    }

    if (typeof part.content === 'string' && part.content.trim().length > 0) {
        return part.content
    }

    if (typeof part.output_text === 'string' && part.output_text.trim().length > 0) {
        return part.output_text
    }

    if (typeof part.value === 'string' && part.value.trim().length > 0) {
        return part.value
    }

    return null
}

function normalizeMessageContent(content: unknown): string {
    if (typeof content === 'string') {
        return content
    }

    if (Array.isArray(content)) {
        const extractedTextParts = content
            .map(extractTextFromMessagePart)
            .filter((part): part is string => part !== null)

        if (extractedTextParts.length > 0) {
            return extractedTextParts.join('\n\n')
        }
    }

    return JSON.stringify(content)
}

function extractConversationMessage(rawMessage: RawMessage): Message {
    const normalizedRole = normalizeRole(rawMessage.role, NormalizedMessageRole.User)
    const enumMap: Partial<Record<string, ConversationRole>> = {
        [InputMessageRole.User]: NormalizedMessageRole.User,
        [InputMessageRole.Assistant]: NormalizedMessageRole.Assistant,
    }

    const enumRole: ConversationRole | undefined = enumMap[normalizedRole]

    return {
        role: enumRole ?? NormalizedMessageRole.User,
        content: normalizeMessageContent(rawMessage.content),
    }
}

export interface ComparisonItem {
    id: string
    promptId?: string
    promptLabel?: string
    model: string
    systemPrompt: string
    requestMessages: Message[]
    response: string
    error?: boolean
    usage?: {
        prompt_tokens?: number | null
        completion_tokens?: number | null
        total_tokens?: number | null
    }
    ttftMs?: number | null
    latencyMs?: number | null
}

const DEFAULT_MODEL = 'gpt-5-mini'
const DEFAULT_SYSTEM_PROMPT = 'You are a helpful AI assistant.'

function createPromptConfig(partial: Partial<PromptConfig> = {}): PromptConfig {
    return {
        id: partial.id ?? uuid(),
        model: partial.model ?? '',
        selectedProviderKeyId: partial.selectedProviderKeyId ?? null,
        systemPrompt: partial.systemPrompt ?? DEFAULT_SYSTEM_PROMPT,
        maxTokens: partial.maxTokens ?? null,
        thinking: partial.thinking ?? false,
        reasoningLevel: partial.reasoningLevel ?? 'medium',
        tools: partial.tools ?? null,
        messages: partial.messages ?? [],
    }
}

const INITIAL_PROMPT = createPromptConfig()

function pickByPrefix(query: string, idList: string[]): string | null {
    let best = null
    for (const s of idList) {
        if (query.startsWith(s)) {
            if (best === null || s.length > best.length) {
                best = s
            }
        }
    }
    return best
}

function normalizeModelId(modelId: string): string {
    return modelId.trim().toLowerCase()
}

function isSuffixEquivalentModelId(leftModelId: string, rightModelId: string): boolean {
    return (
        leftModelId === rightModelId ||
        leftModelId.endsWith(`/${rightModelId}`) ||
        rightModelId.endsWith(`/${leftModelId}`)
    )
}

function getProviderKeyOrder(providerKeys: LLMProviderKey[]): string[] {
    return sortProviderKeys(providerKeys)
        .filter((key) => key.state !== 'invalid')
        .map((key) => key.id)
}

function pickPreferredModelOption(candidates: ModelOption[], providerKeys: LLMProviderKey[]): ModelOption | null {
    if (candidates.length === 0) {
        return null
    }

    const providerKeyOrder = getProviderKeyOrder(providerKeys)
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

function matchClosestModelOption(
    targetModel: string,
    availableModels: ModelOption[],
    providerKeys: LLMProviderKey[] = []
): ModelOption | null {
    if (availableModels.length === 0) {
        return null
    }

    const normalizedTarget = normalizeModelId(targetModel)

    const exactIdMatches = availableModels.filter((model) => model.id === targetModel)
    if (exactIdMatches.length > 0) {
        return pickPreferredModelOption(exactIdMatches, providerKeys)
    }

    const exactNormalizedIdMatches = availableModels.filter((model) => normalizeModelId(model.id) === normalizedTarget)
    if (exactNormalizedIdMatches.length > 0) {
        return pickPreferredModelOption(exactNormalizedIdMatches, providerKeys)
    }

    const suffixEquivalentMatches = availableModels.filter((model) =>
        isSuffixEquivalentModelId(normalizeModelId(model.id), normalizedTarget)
    )
    if (suffixEquivalentMatches.length > 0) {
        return pickPreferredModelOption(suffixEquivalentMatches, providerKeys)
    }

    const normalizedIds = availableModels.map((model) => normalizeModelId(model.id))
    const normalizedPrefixMatch = pickByPrefix(normalizedTarget, normalizedIds)
    if (normalizedPrefixMatch) {
        const normalizedPrefixMatches = availableModels.filter(
            (model) => normalizeModelId(model.id) === normalizedPrefixMatch
        )
        return pickPreferredModelOption(normalizedPrefixMatches, providerKeys)
    }

    const defaultModelMatches = availableModels.filter((model) => model.id === DEFAULT_MODEL)
    if (defaultModelMatches.length > 0) {
        return pickPreferredModelOption(defaultModelMatches, providerKeys)
    }

    return pickPreferredModelOption(availableModels, providerKeys)
}

function matchClosestModel(targetModel: string, availableModels: ModelOption[]): string {
    return matchClosestModelOption(targetModel, availableModels)?.id ?? DEFAULT_MODEL
}

function resolveTargetPromptId(promptConfigs: PromptConfig[], promptId?: string): string | null {
    if (promptId) {
        return promptId
    }
    return promptConfigs[0]?.id ?? null
}

function updatePromptConfigs(
    state: PromptConfig[],
    promptId: string | undefined,
    updater: (prompt: PromptConfig) => PromptConfig
): PromptConfig[] {
    const targetPromptId = resolveTargetPromptId(state, promptId)
    if (!targetPromptId) {
        return state
    }
    return state.map((prompt) => (prompt.id === targetPromptId ? updater(prompt) : prompt))
}

function resolveProviderKeyForPrompt(
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

function appendToolCallChunk(
    state: Array<{ id: string; name: string; arguments: string }>,
    toolCall: { id?: string; function: { name?: string; arguments?: string } }
): Array<{ id: string; name: string; arguments: string }> {
    if (toolCall.id && toolCall.id !== 'null') {
        const existingIndex = state.findIndex((tc) => tc.id === toolCall.id)
        if (existingIndex >= 0) {
            const updated = [...state]
            updated[existingIndex] = {
                ...updated[existingIndex],
                name: toolCall.function?.name || updated[existingIndex].name,
                arguments: updated[existingIndex].arguments + (toolCall.function?.arguments || ''),
            }
            return updated
        }
        return [
            ...state,
            {
                id: toolCall.id,
                name: toolCall.function?.name || '',
                arguments: toolCall.function?.arguments || '',
            },
        ]
    }

    if (state.length === 0) {
        return state
    }

    const updated = [...state]
    const lastIndex = updated.length - 1
    updated[lastIndex] = {
        ...updated[lastIndex],
        arguments: updated[lastIndex].arguments + (toolCall.function?.arguments || ''),
    }
    return updated
}

function formatToolCalls(toolCalls: Array<{ id: string; name: string; arguments: string }>): string {
    if (toolCalls.length === 0) {
        return ''
    }
    return toolCalls
        .map((tc) => JSON.stringify({ id: tc.id, name: tc.name, arguments: tc.arguments }, null, 2))
        .join('\n\n')
}

function normalizeUsageFromStreamChunk(data: Record<string, unknown>): ComparisonItem['usage'] {
    const promptTokens = (data.input_tokens as number | undefined) ?? (data.prompt_tokens as number | undefined) ?? null
    const completionTokens =
        (data.output_tokens as number | undefined) ?? (data.completion_tokens as number | undefined) ?? null
    const totalTokens = (data.total_tokens as number | undefined) ?? null

    return {
        prompt_tokens: typeof promptTokens === 'number' ? promptTokens : null,
        completion_tokens: typeof completionTokens === 'number' ? completionTokens : null,
        total_tokens: typeof totalTokens === 'number' ? totalTokens : null,
    }
}

export const llmAnalyticsPlaygroundLogic = kea<llmAnalyticsPlaygroundLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'llmAnalyticsPlaygroundLogic']),

    connect(() => ({
        values: [byokModelPickerLogic, ['byokModels', 'hasByokKeys'], llmProviderKeysLogic, ['providerKeys']],
        actions: [byokModelPickerLogic, ['loadByokModelsSuccess']],
    })),

    actions({
        addPromptConfig: (sourcePromptId?: string) => ({ sourcePromptId, newPromptId: uuid() }),
        removePromptConfig: (promptId: string) => ({ promptId }),
        setActivePromptId: (promptId: string | null) => ({ promptId }),
        setPromptConfigs: (promptConfigs: PromptConfig[]) => ({ promptConfigs }),
        setModel: (model: string, providerKeyId?: string, promptId?: string) => ({ model, providerKeyId, promptId }),
        setSystemPrompt: (systemPrompt: string, promptId?: string) => ({ systemPrompt, promptId }),
        setMaxTokens: (maxTokens: number | null, promptId?: string) => ({ maxTokens, promptId }),
        setThinking: (thinking: boolean, promptId?: string) => ({ thinking, promptId }),
        setReasoningLevel: (reasoningLevel: ReasoningLevel, promptId?: string) => ({ reasoningLevel, promptId }),
        setTools: (tools: Record<string, unknown>[] | null, promptId?: string) => ({ tools, promptId }),
        clearConversation: (promptId?: string) => ({ promptId }),
        submitPrompt: true,
        finishSubmitPrompt: true,
        setMessages: (messages: Message[], promptId?: string) => ({ messages, promptId }),
        deleteMessage: (index: number, promptId?: string) => ({ index, promptId }),
        addMessage: (message?: Partial<Message>, promptId?: string) => ({ message, promptId }),
        updateMessage: (index: number, payload: Partial<Message>, promptId?: string) => ({ index, payload, promptId }),
        addToComparison: (item: ComparisonItem) => ({ item }),
        updateComparisonItem: (id: string, payload: Partial<ComparisonItem>) => ({ id, payload }),
        setupPlaygroundFromEvent: (payload: { model?: string; input?: any; tools?: any }) => ({ payload }),
        setRateLimited: (retryAfterSeconds: number) => ({ retryAfterSeconds }),
        setSubscriptionRequired: (required: boolean) => ({ required }),
        setActiveProviderKeyId: (id: string | null) => ({ id }),
        setLocalToolsJson: (json: string | null, promptId?: string) => ({ json, promptId }),
    }),

    reducers({
        promptConfigs: [
            [INITIAL_PROMPT] as PromptConfig[],
            {
                setPromptConfigs: (_, { promptConfigs }) =>
                    promptConfigs.length > 0 ? promptConfigs : [createPromptConfig({ id: INITIAL_PROMPT.id })],
                addPromptConfig: (state, { sourcePromptId, newPromptId }) => {
                    const sourcePrompt = state.find((prompt) => prompt.id === sourcePromptId) ?? state[state.length - 1]
                    return [...state, createPromptConfig({ ...sourcePrompt, id: newPromptId })]
                },
                removePromptConfig: (state, { promptId }) => {
                    if (state.length <= 1) {
                        return state
                    }
                    const nextState = state.filter((prompt) => prompt.id !== promptId)
                    return nextState.length > 0 ? nextState : [createPromptConfig()]
                },
                setModel: (state, { model, providerKeyId, promptId }) =>
                    updatePromptConfigs(state, promptId, (prompt) => ({
                        ...prompt,
                        model,
                        selectedProviderKeyId: providerKeyId ?? null,
                    })),
                setSystemPrompt: (state, { systemPrompt, promptId }) =>
                    updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, systemPrompt })),
                setMaxTokens: (state, { maxTokens, promptId }) =>
                    updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, maxTokens })),
                setThinking: (state, { thinking, promptId }) =>
                    updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, thinking })),
                setReasoningLevel: (state, { reasoningLevel, promptId }) =>
                    updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, reasoningLevel })),
                setTools: (state, { tools, promptId }) =>
                    updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, tools })),
                clearConversation: (state, { promptId }) =>
                    updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, messages: [] })),
                setMessages: (state, { messages, promptId }) =>
                    updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, messages })),
                deleteMessage: (state, { index, promptId }) =>
                    updatePromptConfigs(state, promptId, (prompt) => {
                        if (index < 0 || index >= prompt.messages.length) {
                            return prompt
                        }
                        return { ...prompt, messages: prompt.messages.filter((_, i) => i !== index) }
                    }),
                addMessage: (state, { message, promptId }) =>
                    updatePromptConfigs(state, promptId, (prompt) => {
                        const defaultMessage: Message = { role: 'user', content: '' }
                        return { ...prompt, messages: [...prompt.messages, { ...defaultMessage, ...message }] }
                    }),
                updateMessage: (state, { index, payload, promptId }) =>
                    updatePromptConfigs(state, promptId, (prompt) => {
                        if (index < 0 || index >= prompt.messages.length) {
                            return prompt
                        }
                        const newMessages = [...prompt.messages]
                        newMessages[index] = { ...newMessages[index], ...payload }
                        return { ...prompt, messages: newMessages }
                    }),
                setupPlaygroundFromEvent: (state, { payload }) => {
                    const targetPrompt = state[0] ?? createPromptConfig({ id: INITIAL_PROMPT.id })
                    const normalizedModel = payload.model ?? targetPrompt.model
                    return [
                        {
                            ...targetPrompt,
                            model: normalizedModel,
                        },
                    ]
                },
            },
        ],
        activePromptId: [
            INITIAL_PROMPT.id as string | null,
            {
                addPromptConfig: (_, { newPromptId }) => newPromptId,
                setActivePromptId: (_, { promptId }) => promptId,
                removePromptConfig: (state, { promptId }) => (state === promptId ? null : state),
                setupPlaygroundFromEvent: () => INITIAL_PROMPT.id,
            },
        ],
        modelOptionsErrorStatus: [
            null as number | null,
            {
                loadModelOptions: () => null,
                loadModelOptionsSuccess: () => null,
                loadModelOptionsFailure: (_, { error }) => {
                    const err = error as unknown
                    if (err instanceof ApiError) {
                        return err.status ?? null
                    }
                    return null
                },
            },
        ],
        submitting: [
            false as boolean,
            {
                submitPrompt: () => true,
                finishSubmitPrompt: () => false,
            },
        ],
        comparisonItems: [
            [] as ComparisonItem[],
            {
                submitPrompt: () => [],
                addToComparison: (state, { item }) => [...state, item],
                updateComparisonItem: (state, { id, payload }) =>
                    state.map((item) => (item.id === id ? { ...item, ...payload } : item)),
            },
        ],
        rateLimitedUntil: [
            null as number | null,
            {
                setRateLimited: (_, { retryAfterSeconds }) => Date.now() + retryAfterSeconds * 1000,
            },
        ],
        subscriptionRequired: [
            false as boolean,
            {
                setSubscriptionRequired: (_, { required }) => required,
            },
        ],
        activeProviderKeyId: [
            null as string | null,
            {
                setActiveProviderKeyId: (_, { id }) => id,
            },
        ],
        pendingTargetModel: [
            null as string | null,
            {
                setupPlaygroundFromEvent: (_, { payload }) => payload.model ?? null,
                loadByokModelsSuccess: () => null,
            },
        ],
        localToolsJsonByPromptId: [
            {} as Record<string, string | null>,
            {
                setLocalToolsJson: (state, { json, promptId }) => {
                    if (!promptId) {
                        return state
                    }
                    return { ...state, [promptId]: json }
                },
                setTools: (state, { promptId }) => {
                    if (!promptId) {
                        return state
                    }
                    return { ...state, [promptId]: null }
                },
                removePromptConfig: (state, { promptId }) => {
                    const { [promptId]: _, ...rest } = state
                    return rest
                },
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
                        llmAnalyticsPlaygroundLogic.actions.setActiveProviderKeyId(
                            config?.active_provider_key?.id ?? null
                        )
                    } catch (e) {
                        console.warn('Failed to load evaluation config', e)
                    }
                }

                const trialModels = (await api.get('/api/llm_proxy/models/')) as ModelOption[]
                const options = trialModels ?? []

                const normalizedPrompts = values.promptConfigs.map((prompt) => {
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
                    llmAnalyticsPlaygroundLogic.actions.setPromptConfigs(normalizedPrompts)
                }

                return options
            },
        },
    })),

    listeners(({ actions, values }) => ({
        removePromptConfig: ({ promptId }) => {
            if (values.promptConfigs.length === 0) {
                actions.setPromptConfigs([createPromptConfig({ id: INITIAL_PROMPT.id })])
                actions.setActivePromptId(INITIAL_PROMPT.id)
                return
            }

            if (values.activePromptId === null || values.activePromptId === promptId) {
                actions.setActivePromptId(values.promptConfigs[0]?.id ?? null)
            }
        },

        loadByokModelsSuccess: ({ byokModels }) => {
            if (byokModels.length === 0) {
                return
            }

            const targetModelForFirstPrompt = values.pendingTargetModel
            const normalizedPrompts = values.promptConfigs.map((prompt, index) => {
                const targetModel = index === 0 && targetModelForFirstPrompt ? targetModelForFirstPrompt : prompt.model
                const matchedModel = matchClosestModelOption(targetModel, byokModels, values.providerKeys)
                return {
                    ...prompt,
                    model: matchedModel?.id ?? matchClosestModel(targetModel, byokModels),
                    selectedProviderKeyId: matchedModel?.providerKeyId ?? prompt.selectedProviderKeyId,
                }
            })

            actions.setPromptConfigs(normalizedPrompts)
        },

        submitPrompt: async (_, breakpoint) => {
            const runnablePrompts = values.promptConfigs
                .map((prompt, index) => ({
                    prompt,
                    index,
                    messagesToSend: prompt.messages.filter((m) => m.content.trim()),
                }))
                .filter((item) => item.messagesToSend.length > 0)

            if (runnablePrompts.length === 0) {
                lemonToast.error('Please add some messages before running prompts')
                actions.finishSubmitPrompt()
                return
            }

            const abortController = new AbortController()
            try {
                const runs = runnablePrompts.map(async ({ prompt, index, messagesToSend }) => {
                    const liveItemId = uuid()
                    let responseUsage: ComparisonItem['usage'] = {}
                    let ttftMs: number | null = null
                    let latencyMs: number | null = null
                    let firstTokenTime: number | null = null
                    let startTime: number | null = null
                    let responseText = ''
                    let responseHasError = false
                    let toolCalls: Array<{ id: string; name: string; arguments: string }> = []
                    let itemAdded = false

                    const upsertLiveItem = (): void => {
                        const payload: ComparisonItem = {
                            id: liveItemId,
                            promptId: prompt.id,
                            promptLabel: `Prompt ${index + 1}`,
                            model: prompt.model,
                            systemPrompt: prompt.systemPrompt,
                            requestMessages: messagesToSend,
                            response: responseText,
                            error: responseHasError,
                            usage: responseUsage,
                            ttftMs,
                            latencyMs,
                        }
                        if (!itemAdded) {
                            actions.addToComparison(payload)
                            itemAdded = true
                        } else {
                            actions.updateComparisonItem(liveItemId, payload)
                        }
                    }

                    upsertLiveItem()

                    try {
                        startTime = performance.now()

                        const selectedModel = values.effectiveModelOptions.find((m) => m.id === prompt.model)
                        if (!selectedModel?.provider) {
                            lemonToast.error('Selected model not found in available models')
                            responseText = '**Error:** Selected model not available.'
                            responseHasError = true
                            upsertLiveItem()
                            return
                        }

                        const providerKeyId =
                            resolveProviderKeyForPrompt(prompt, values.effectiveModelOptions, values.providerKeys)
                                ?.id ?? values.activeProviderKeyId

                        const requestData: Record<string, unknown> = {
                            system: prompt.systemPrompt,
                            messages: messagesToSend.filter((m) => m.role === 'user' || m.role === 'assistant'),
                            model: selectedModel.id,
                            provider: selectedModel.provider.toLowerCase(),
                            thinking: prompt.thinking,
                            ...(providerKeyId ? { provider_key_id: providerKeyId } : {}),
                            ...(prompt.tools ? { tools: prompt.tools } : {}),
                            ...(prompt.maxTokens !== null && prompt.maxTokens > 0
                                ? { max_tokens: prompt.maxTokens }
                                : {}),
                            ...(prompt.reasoningLevel ? { reasoning_level: prompt.reasoningLevel } : {}),
                        }

                        await api.stream('/api/llm_proxy/completion', {
                            method: 'POST',
                            data: requestData,
                            headers: { 'Content-Type': 'application/json' },
                            signal: abortController.signal,
                            onMessage: (event) => {
                                breakpoint()
                                if (!event.data) {
                                    return
                                }

                                try {
                                    const data = JSON.parse(event.data)
                                    if (data.type === 'text') {
                                        if (firstTokenTime === null && startTime !== null) {
                                            firstTokenTime = performance.now()
                                            ttftMs = firstTokenTime - startTime
                                        }
                                        responseText += data.text
                                        upsertLiveItem()
                                    } else if (data.type === 'tool_call') {
                                        if (firstTokenTime === null && startTime !== null) {
                                            firstTokenTime = performance.now()
                                            ttftMs = firstTokenTime - startTime
                                        }
                                        toolCalls = appendToolCallChunk(toolCalls, data)
                                        const toolCallsText = formatToolCalls(toolCalls)
                                        const separator = responseText.trim() && toolCallsText ? '\n\n' : ''
                                        actions.updateComparisonItem(liveItemId, {
                                            response: responseText + separator + toolCallsText,
                                            ttftMs,
                                        })
                                    } else if (data.type === 'usage') {
                                        responseUsage = normalizeUsageFromStreamChunk(data)
                                        actions.updateComparisonItem(liveItemId, { usage: responseUsage })
                                    } else if (data.error) {
                                        responseText += `\n\n**LLM Error:** ${data.error}`
                                        responseHasError = true
                                        upsertLiveItem()
                                    }
                                } catch (e) {
                                    console.error('Error parsing stream message:', e, 'Data:', event.data)
                                    responseText += `\n\n**Stream Error:** Could not parse response chunk.`
                                    responseHasError = true
                                    upsertLiveItem()
                                }
                            },
                            onError: (err) => {
                                if (err instanceof RateLimitError) {
                                    actions.setRateLimited(err.retryAfterSeconds)
                                    responseHasError = true
                                    upsertLiveItem()
                                    return
                                }
                                if (err instanceof ApiError && err.status === 402) {
                                    actions.setSubscriptionRequired(true)
                                    responseHasError = true
                                    upsertLiveItem()
                                    return
                                }
                                responseText += `\n\n**Stream Connection Error:** ${err.message || 'Unknown error'}`
                                responseHasError = true
                                upsertLiveItem()
                            },
                        })

                        globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.RunAiPlayground)
                    } catch (error) {
                        if (error instanceof RateLimitError) {
                            actions.setRateLimited(error.retryAfterSeconds)
                            responseHasError = true
                        } else if (error instanceof ApiError && error.status === 402) {
                            actions.setSubscriptionRequired(true)
                            responseHasError = true
                        } else {
                            responseText += `\n\n**Error:** Failed to initiate prompt submission.`
                            responseHasError = true
                            lemonToast.error('Failed to connect to LLM service. Please try again.')
                        }
                        upsertLiveItem()
                    } finally {
                        if (startTime !== null) {
                            latencyMs = performance.now() - startTime
                        }
                    }

                    const toolCallsText = formatToolCalls(toolCalls)
                    if (toolCallsText) {
                        const separator = responseText.trim() ? '\n\n' : ''
                        responseText += separator + toolCallsText
                    }

                    upsertLiveItem()
                })

                await Promise.allSettled(runs)
            } finally {
                abortController.abort()
                actions.finishSubmitPrompt()
            }
        },

        setupPlaygroundFromEvent: ({ payload }) => {
            const { model, input, tools } = payload
            const currentPrompt = values.promptConfigs[0] ?? createPromptConfig({ id: INITIAL_PROMPT.id })
            const promptId = currentPrompt.id

            if (model) {
                const matchedModel = matchClosestModelOption(model, values.effectiveModelOptions, values.providerKeys)
                actions.setModel(
                    matchedModel?.id ?? matchClosestModel(model, values.effectiveModelOptions),
                    matchedModel?.providerKeyId,
                    promptId
                )
            }

            if (tools) {
                actions.setTools(tools, promptId)
            }

            let systemPromptContent: string | undefined = undefined
            let conversationMessages: Message[] = []
            let initialUserPrompt: string | undefined = undefined

            if (input) {
                try {
                    if (Array.isArray(input) && input.every((msg) => msg.role && msg.content)) {
                        const systemContents = input
                            .filter((msg) => msg.role === 'system')
                            .map((msg) => msg.content)
                            .filter(
                                (content): content is string => typeof content === 'string' && content.trim().length > 0
                            )

                        if (systemContents.length > 0) {
                            systemPromptContent = systemContents.join('\n\n')
                        }

                        conversationMessages = input
                            .filter((msg: RawMessage) => msg.role !== 'system')
                            .map((msg: RawMessage) => extractConversationMessage(msg))
                    } else if (typeof input === 'string') {
                        initialUserPrompt = input
                    } else if (isObject(input)) {
                        if (typeof input.content === 'string') {
                            initialUserPrompt = input.content
                        } else if (input.content && typeof input.content !== 'string') {
                            initialUserPrompt = JSON.stringify(input.content, null, 2)
                        } else {
                            initialUserPrompt = JSON.stringify(input, null, 2)
                        }
                    }
                } catch (e) {
                    console.error('Error processing input for playground:', e)
                    initialUserPrompt = String(input)
                    conversationMessages = []
                }
            }

            actions.setSystemPrompt(systemPromptContent ?? DEFAULT_SYSTEM_PROMPT, promptId)

            if (initialUserPrompt) {
                conversationMessages.unshift({ role: 'user', content: initialUserPrompt })
            }

            actions.setMessages(conversationMessages, promptId)
            actions.setActivePromptId(promptId)
            router.actions.push(urls.llmAnalyticsPlayground())
        },
    })),

    afterMount(({ actions }) => {
        actions.loadModelOptions()
    }),

    selectors({
        activePromptConfig: [
            (s) => [s.promptConfigs, s.activePromptId],
            (promptConfigs: PromptConfig[], activePromptId: string | null): PromptConfig => {
                return (
                    promptConfigs.find((prompt) => prompt.id === activePromptId) ??
                    promptConfigs[0] ??
                    createPromptConfig({ id: INITIAL_PROMPT.id })
                )
            },
        ],
        model: [(s) => [s.activePromptConfig], (activePromptConfig: PromptConfig): string => activePromptConfig.model],
        selectedProviderKeyId: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): string | null => activePromptConfig.selectedProviderKeyId,
        ],
        systemPrompt: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): string => activePromptConfig.systemPrompt,
        ],
        maxTokens: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): number | null => activePromptConfig.maxTokens,
        ],
        thinking: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): boolean => activePromptConfig.thinking,
        ],
        reasoningLevel: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): ReasoningLevel => activePromptConfig.reasoningLevel,
        ],
        tools: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): Record<string, unknown>[] | null => activePromptConfig.tools,
        ],
        messages: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): Message[] => activePromptConfig.messages,
        ],
        hasRunnablePrompts: [
            (s) => [s.promptConfigs],
            (promptConfigs: PromptConfig[]): boolean =>
                promptConfigs.some((prompt) => prompt.messages.some((message) => message.content.trim().length > 0)),
        ],
        effectiveModelOptions: [
            (s) => [s.hasByokKeys, s.byokModels, s.modelOptions],
            (hasByokKeys: boolean, byokModels: ModelOption[], modelOptions: ModelOption[]): ModelOption[] =>
                hasByokKeys && byokModels.length > 0 ? byokModels : modelOptions,
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
])
