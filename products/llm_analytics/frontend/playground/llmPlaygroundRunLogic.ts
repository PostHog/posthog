import { actions, connect, kea, listeners, path, reducers } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError, RateLimitError } from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { uuid } from 'lib/utils'

import type { ModelOption } from '../modelPickerLogic'
import { llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import { llmPlaygroundModelLogic } from './llmPlaygroundModelLogic'
import { llmPlaygroundPromptsLogic, type Message, type PromptConfig } from './llmPlaygroundPromptsLogic'
import type { llmPlaygroundRunLogicType } from './llmPlaygroundRunLogicType'
import { resolveProviderKeyForPrompt } from './playgroundModelMatching'

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
    cache_read_tokens?: number | null
    cache_write_tokens?: number | null
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
    const cacheReadTokens = (data.cache_read_tokens as number | undefined) ?? null
    const cacheWriteTokens = (data.cache_write_tokens as number | undefined) ?? null

    return {
        prompt_tokens: typeof promptTokens === 'number' ? promptTokens : null,
        completion_tokens: typeof completionTokens === 'number' ? completionTokens : null,
        total_tokens: typeof totalTokens === 'number' ? totalTokens : null,
        cache_read_tokens: typeof cacheReadTokens === 'number' ? cacheReadTokens : null,
        cache_write_tokens: typeof cacheWriteTokens === 'number' ? cacheWriteTokens : null,
    }
}

/** Merge a new usage chunk into existing usage, keeping non-zero values from prior chunks.
 * Anthropic sends input_tokens in message_start and output_tokens in message_delta,
 * so a simple replace would zero out the input_tokens. */
function mergeUsage(prev: UsageSummary, next: UsageSummary): UsageSummary {
    const pick = (a: number | null | undefined, b: number | null | undefined): number | null => {
        if (typeof b === 'number' && b > 0) {
            return b
        }
        return typeof a === 'number' ? a : null
    }
    return {
        prompt_tokens: pick(prev.prompt_tokens, next.prompt_tokens),
        completion_tokens: pick(prev.completion_tokens, next.completion_tokens),
        total_tokens: pick(prev.total_tokens, next.total_tokens),
        cache_read_tokens: pick(prev.cache_read_tokens, next.cache_read_tokens),
        cache_write_tokens: pick(prev.cache_write_tokens, next.cache_write_tokens),
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
    usage?: UsageSummary
    ttftMs?: number | null
    latencyMs?: number | null
}

export const llmPlaygroundRunLogic = kea<llmPlaygroundRunLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'playground', 'llmPlaygroundRunLogic']),

    connect(() => ({
        values: [
            llmPlaygroundPromptsLogic,
            ['promptConfigs'],
            llmPlaygroundModelLogic,
            ['effectiveModelOptions', 'activeProviderKeyId'],
            llmProviderKeysLogic,
            ['providerKeys'],
        ],
    })),

    actions({
        submitPrompt: true,
        finishSubmitPrompt: true,
        addToComparison: (item: ComparisonItem) => ({ item }),
        updateComparisonItem: (id: string, payload: Partial<ComparisonItem>) => ({ id, payload }),
        setRateLimited: (retryAfterSeconds: number) => ({ retryAfterSeconds }),
        setSubscriptionRequired: (required: boolean) => ({ required }),
    }),

    reducers({
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
    }),

    listeners(({ actions, values }) => ({
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
                const runs = runnablePrompts.map(async ({ prompt, index, messagesToSend }) => {
                    const liveItemId = uuid()
                    let responseUsage: UsageSummary = {}
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
                                        responseUsage = mergeUsage(responseUsage, normalizeUsageFromStreamChunk(data))
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
    })),
])
