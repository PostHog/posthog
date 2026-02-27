import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError, RateLimitError } from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { isObject, uuid } from 'lib/utils'
import { urls } from 'scenes/urls'

import type { ModelOption } from '../byokModelPickerLogic'
import { normalizeLLMProvider } from '../settings/llmProviderKeysLogic'
import { normalizeRole } from '../utils'
import {
    isTraceLikeSelection,
    matchClosestModelOption,
    resolveProviderKeyForPrompt,
    resolveTraceModelSelection,
} from './llmPlaygroundModelLogic'
import {
    createPromptConfig,
    DEFAULT_SYSTEM_PROMPT,
    INITIAL_PROMPT,
    Message,
    PromptConfig,
} from './llmPlaygroundPromptsLogic'

interface RawMessage {
    role: string
    content: unknown
}

type ConversationRole = 'user' | 'assistant'

enum InputMessageRole {
    User = 'user',
    Assistant = 'assistant',
    AI = 'ai',
    Model = 'model',
}

interface ToolCallChunk {
    id?: string
    function: {
        name?: string
        arguments?: string
    }
}

interface AggregatedToolCall {
    id: string
    name: string
    arguments: string
}

interface UsageSummary {
    prompt_tokens?: number | null
    completion_tokens?: number | null
    total_tokens?: number | null
}

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

function extractConversationMessage(rawMessage: RawMessage): { role: ConversationRole; content: string } {
    const normalizedMessageRole = normalizeRole(rawMessage.role, InputMessageRole.User)
    const enumMap: Partial<Record<string, ConversationRole>> = {
        [InputMessageRole.User]: InputMessageRole.User,
        [InputMessageRole.Assistant]: InputMessageRole.Assistant,
    }
    const enumRole: ConversationRole | undefined = enumMap[normalizedMessageRole]

    return {
        role: enumRole ?? InputMessageRole.User,
        content: normalizeMessageContent(rawMessage.content),
    }
}

function appendToolCallChunk(state: AggregatedToolCall[], toolCall: ToolCallChunk): AggregatedToolCall[] {
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

function formatToolCalls(toolCalls: AggregatedToolCall[]): string {
    if (toolCalls.length === 0) {
        return ''
    }
    return toolCalls
        .map((tc) => JSON.stringify({ id: tc.id, name: tc.name, arguments: tc.arguments }, null, 2))
        .join('\n\n')
}

function normalizeUsageFromStreamChunk(data: Record<string, unknown>): UsageSummary {
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

export const runReducers = {
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
            addToComparison: (state: ComparisonItem[], { item }: { item: ComparisonItem }) => [...state, item],
            updateComparisonItem: (
                state: ComparisonItem[],
                { id, payload }: { id: string; payload: Partial<ComparisonItem> }
            ) => state.map((item) => (item.id === id ? { ...item, ...payload } : item)),
        },
    ],
    rateLimitedUntil: [
        null as number | null,
        {
            setRateLimited: (_: number | null, { retryAfterSeconds }: { retryAfterSeconds: number }) =>
                Date.now() + retryAfterSeconds * 1000,
        },
    ],
    subscriptionRequired: [
        false as boolean,
        {
            setSubscriptionRequired: (_: boolean, { required }: { required: boolean }) => required,
        },
    ],
}

export function runListeners({
    actions,
    values,
}: {
    actions: any
    values: any
}): Record<string, (...args: any[]) => any> {
    return {
        removePromptConfig: ({ promptId }: { promptId: string }) => {
            if (values.promptConfigs.length === 0) {
                actions.setPromptConfigs([createPromptConfig({ id: INITIAL_PROMPT.id })])
                actions.setActivePromptId(INITIAL_PROMPT.id)
                return
            }

            if (values.activePromptId === null || values.activePromptId === promptId) {
                actions.setActivePromptId(values.promptConfigs[0]?.id ?? null)
            }
        },

        submitPrompt: async (_: unknown, breakpoint: () => void) => {
            const runnablePrompts = values.promptConfigs
                .map((prompt: PromptConfig, index: number) => ({
                    prompt,
                    index,
                    messagesToSend: prompt.messages.filter((m) => m.content.trim()),
                }))
                .filter((item: { messagesToSend: Message[] }) => item.messagesToSend.length > 0)

            if (runnablePrompts.length === 0) {
                lemonToast.error('Please add some messages before running prompts')
                actions.finishSubmitPrompt()
                return
            }

            const abortController = new AbortController()
            try {
                const runs = runnablePrompts.map(async ({ prompt, index, messagesToSend }: any) => {
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

                        const selectedModel = (values.effectiveModelOptions as ModelOption[]).find(
                            (m) => m.id === prompt.model
                        )
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
                            messages: messagesToSend.filter(
                                (m: Message) => m.role === 'user' || m.role === 'assistant'
                            ),
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

        setupPlaygroundFromEvent: ({
            payload,
        }: {
            payload: { model?: string; provider?: string; input?: any; tools?: any }
        }) => {
            const { model, provider, input, tools } = payload
            const currentPrompt = values.promptConfigs[0] ?? createPromptConfig({ id: INITIAL_PROMPT.id })
            const promptId = currentPrompt.id
            const traceLikeSelection = isTraceLikeSelection(model, provider)

            if (model && values.providerKeysSettled && values.byokModelsSettled) {
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
    }
}
