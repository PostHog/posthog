import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import posthog from 'posthog-js'

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

export interface AggregatedToolCall {
    id: string
    name: string
    arguments: string
}

export interface UsageSummary {
    prompt_tokens?: number | null
    completion_tokens?: number | null
    total_tokens?: number | null
    cache_read_tokens?: number | null
    cache_write_tokens?: number | null
}

export function appendToolCallChunk(state: AggregatedToolCall[], toolCall: ToolCallChunk): AggregatedToolCall[] {
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

export function describeError(err: unknown, fallbackMessage: string): { message: string; status?: number } {
    if (err instanceof ApiError) {
        const dataError = typeof err.data?.error === 'string' ? err.data.error : null
        return {
            message: dataError || err.detail || err.message || fallbackMessage,
            status: err.status,
        }
    }
    return {
        message: (err instanceof Error && err.message) || fallbackMessage,
    }
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
export function mergeUsage(prev: UsageSummary, next: UsageSummary): UsageSummary {
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
    promptId: string
    promptLabel?: string
    model: string
    systemPrompt: string
    requestMessages: Message[]
    response: string
    reasoning?: string
    toolCalls?: AggregatedToolCall[]
    provider?: string
    providerKeyId?: string | null
    error?: boolean
    usage?: UsageSummary
    ttftMs?: number | null
    latencyMs?: number | null
}

// Per-key abort controllers so each tab can independently cancel its own in-flight run
// without affecting other tabs. Using a Map instead of Kea state avoids storing
// non-serializable objects in reducers.
const abortControllersByKey = new Map<string, AbortController>()

export interface LLMPlaygroundRunLogicProps {
    tabId?: string
}

export const llmPlaygroundRunLogic = kea<llmPlaygroundRunLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'playground', 'llmPlaygroundRunLogic']),
    props({} as LLMPlaygroundRunLogicProps),
    key((props) => props.tabId ?? 'default'),

    connect(({ tabId }: LLMPlaygroundRunLogicProps) => ({
        values: [
            llmPlaygroundPromptsLogic({ tabId }),
            ['promptConfigs'],
            llmPlaygroundModelLogic({ tabId }),
            ['effectiveModelOptions', 'activeProviderKeyId'],
            llmProviderKeysLogic,
            ['providerKeys'],
        ],
        actions: [llmPlaygroundPromptsLogic({ tabId }), ['resetPlayground']],
    })),

    actions({
        submitPrompt: true,
        finishSubmitPrompt: true,
        abortRun: true,
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
                resetPlayground: () => [],
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

    listeners(({ actions, values, props }) => ({
        abortRun: () => {
            posthog.capture('llma playground prompt aborted')
            const key = props.tabId ?? 'default'
            abortControllersByKey.get(key)?.abort()
        },
        setRateLimited: ({ retryAfterSeconds }) => {
            posthog.capture('llma playground rate limited', { retry_after_seconds: retryAfterSeconds })
        },
        setSubscriptionRequired: ({ required }) => {
            if (required) {
                posthog.capture('llma playground subscription required')
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

            posthog.capture('llma playground prompt submitted', {
                prompt_count: runnablePrompts.length,
                models: runnablePrompts.map(({ prompt }) => prompt.model),
                has_tools: runnablePrompts.some(({ prompt }) => !!prompt.tools?.length),
                total_message_count: runnablePrompts.reduce(
                    (sum, { messagesToSend }) => sum + messagesToSend.length,
                    0
                ),
            })

            const key = props.tabId ?? 'default'
            const abortController = new AbortController()
            abortControllersByKey.set(key, abortController)
            try {
                const runs = runnablePrompts.map(async ({ prompt, index, messagesToSend }) => {
                    const liveItemId = uuid()
                    let responseUsage: UsageSummary = {}
                    let ttftMs: number | null = null
                    let latencyMs: number | null = null
                    let firstTokenTime: number | null = null
                    let startTime: number | null = null
                    let responseText = ''
                    let responseReasoning = ''
                    let responseHasError = false
                    let toolCalls: AggregatedToolCall[] = []
                    let providerKeyId: string | null = null
                    let selectedModelProvider = ''
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
                            reasoning: responseReasoning,
                            toolCalls,
                            provider: selectedModelProvider,
                            providerKeyId,
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

                        providerKeyId =
                            resolveProviderKeyForPrompt(prompt, values.effectiveModelOptions, values.providerKeys)
                                ?.id ?? values.activeProviderKeyId
                        selectedModelProvider = selectedModel.provider.toLowerCase()

                        const requestData: Record<string, unknown> = {
                            system: prompt.systemPrompt,
                            messages: messagesToSend
                                .filter((m: Message) => m.role === 'user' || m.role === 'assistant')
                                .map((m: Message) => ({ role: m.role, content: m.content })),
                            model: selectedModel.id,
                            provider: selectedModelProvider,
                            thinking: prompt.thinking,
                            ...(providerKeyId ? { provider_key_id: providerKeyId } : {}),
                            ...(prompt.tools ? { tools: prompt.tools } : {}),
                            ...(prompt.maxTokens !== null && prompt.maxTokens > 0
                                ? { max_tokens: prompt.maxTokens }
                                : {}),
                            ...(typeof prompt.temperature === 'number' ? { temperature: prompt.temperature } : {}),
                            ...(typeof prompt.topP === 'number' ? { top_p: prompt.topP } : {}),
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
                                            toolCalls,
                                            ttftMs,
                                        })
                                    } else if (data.type === 'reasoning') {
                                        const reasoningChunk =
                                            typeof data.reasoning === 'string'
                                                ? data.reasoning
                                                : typeof data.text === 'string'
                                                  ? data.text
                                                  : ''
                                        responseReasoning += reasoningChunk
                                        actions.updateComparisonItem(liveItemId, {
                                            reasoning: responseReasoning,
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
                                if (abortController.signal.aborted) {
                                    return
                                }
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
                                const { message, status } = describeError(err, 'Unknown error')
                                const errorLabel = err instanceof ApiError ? 'Error' : 'Stream Connection Error'
                                responseText += `\n\n**${errorLabel}:** ${message}`
                                responseHasError = true
                                upsertLiveItem()
                                posthog.captureException(err, {
                                    tag: 'llma-playground-prompt-run',
                                    model: prompt.model,
                                    provider: selectedModelProvider,
                                    status,
                                })
                            },
                        })

                        globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.RunAiPlayground)
                    } catch (error) {
                        if (abortController.signal.aborted) {
                            responseText += `${responseText ? '\n\n' : ''}*Generation stopped.*`
                        } else if (error instanceof RateLimitError) {
                            actions.setRateLimited(error.retryAfterSeconds)
                            responseHasError = true
                        } else if (error instanceof ApiError && error.status === 402) {
                            actions.setSubscriptionRequired(true)
                            responseHasError = true
                        } else {
                            const { message, status } = describeError(error, 'Failed to initiate prompt submission.')
                            responseText += `\n\n**Error:** ${message}`
                            responseHasError = true
                            lemonToast.error(message)
                            posthog.captureException(error, {
                                tag: 'llma-playground-prompt-submit',
                                model: prompt.model,
                                provider: selectedModelProvider,
                                status,
                            })
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

                    posthog.capture('llma playground prompt completed', {
                        model: prompt.model,
                        provider: selectedModelProvider,
                        latency_ms: latencyMs,
                        ttft_ms: ttftMs,
                        prompt_tokens: responseUsage.prompt_tokens,
                        completion_tokens: responseUsage.completion_tokens,
                        success: !responseHasError,
                        has_tools: !!prompt.tools?.length,
                        aborted: abortController.signal.aborted,
                    })
                })

                await Promise.allSettled(runs)
            } finally {
                abortControllersByKey.delete(key)
                abortController.abort()
                actions.finishSubmitPrompt()
            }
        },
    })),
])
