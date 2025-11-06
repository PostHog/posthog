import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { uuid } from 'lib/utils'
import { isObject } from 'lib/utils'
import { urls } from 'scenes/urls'

import type { llmAnalyticsPlaygroundLogicType } from './llmAnalyticsPlaygroundLogicType'
import { normalizeRole } from './utils'

export interface ModelOption {
    id: string
    name: string
    provider: string
    description: string
}

export interface PlaygroundResponse {
    text: string
    model: string
    usage: {
        prompt_tokens: number | null
        completion_tokens: number | null
        total_tokens: number | null
    }
}

enum NormalizedMessageRole {
    User = 'user',
    Assistant = 'assistant',
    System = 'system',
}

export type MessageRole = `${NormalizedMessageRole}`

export interface Message {
    role: MessageRole
    content: string
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
    System = 'system',
}

type ConversationRole = NormalizedMessageRole.User | NormalizedMessageRole.Assistant

function extractConversationMessage(rawMessage: RawMessage): Message {
    const normalizedRole = normalizeRole(rawMessage.role, NormalizedMessageRole.User)
    const enumMap: Partial<Record<string, ConversationRole>> = {
        [InputMessageRole.User]: NormalizedMessageRole.User,
        [InputMessageRole.Assistant]: NormalizedMessageRole.Assistant,
    }

    const enumRole: ConversationRole | undefined = enumMap[normalizedRole]

    // Default to 'user' role when we don't understand the role
    // Better to show the message as a user message than to drop it entirely
    const roleToUse = enumRole ?? NormalizedMessageRole.User

    return {
        role: roleToUse,
        content: typeof rawMessage.content === 'string' ? rawMessage.content : JSON.stringify(rawMessage.content),
    }
}

export interface ComparisonItem {
    id: string
    model: string
    systemPrompt: string
    requestMessages: Message[]
    response: string
    usage?: {
        prompt_tokens?: number | null
        completion_tokens?: number | null
        total_tokens?: number | null
    }
    ttftMs?: number | null
    latencyMs?: number | null
}

const DEFAULT_MODEL = 'gpt-4.1'

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

function matchClosestModel(targetModel: string, availableModels: ModelOption[]): string {
    const ids = availableModels.map((m) => m.id)
    if (ids.includes(targetModel)) {
        return targetModel
    }
    const match = pickByPrefix(targetModel, ids)
    if (match) {
        return match
    }
    return DEFAULT_MODEL
}

export const llmAnalyticsPlaygroundLogic = kea<llmAnalyticsPlaygroundLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'llmAnalyticsPlaygroundLogic']),

    actions({
        setModel: (model: string) => ({ model }),
        setSystemPrompt: (systemPrompt: string) => ({ systemPrompt }),
        setMaxTokens: (maxTokens: number | null) => ({ maxTokens }),
        setThinking: (thinking: boolean) => ({ thinking }),
        setReasoningLevel: (reasoningLevel: 'minimal' | 'low' | 'medium' | 'high' | null) => ({ reasoningLevel }),
        setTools: (tools: any) => ({ tools }),
        clearConversation: true,
        submitPrompt: true,
        setMessages: (messages: Message[]) => ({ messages }),
        deleteMessage: (index: number) => ({ index }),
        addAssistantMessageChunk: (text: string) => ({ text }),
        addFinalizedContent: (text: string) => ({ text }),
        addToolCallChunk: (toolCall: { id?: string; function: { name?: string; arguments?: string } }) => ({
            toolCall,
        }),
        clearToolCalls: true,
        finalizeAssistantMessage: true,
        addMessage: (message?: Partial<Message>) => ({ message }),
        updateMessage: (index: number, payload: Partial<Message>) => ({ index, payload }),
        addResponseToHistory: (content: string) => ({ content }),
        addCurrentRunToComparison: true,
        setLastRunDetails: (details: ComparisonItem | null) => ({ details }),
        addToComparison: (item: ComparisonItem) => ({ item }),
        removeFromComparison: (id: string) => ({ id }),
        clearComparison: true,
        setupPlaygroundFromEvent: (payload: { model?: string; input?: any; tools?: any }) => ({ payload }),
        setResponseError: (hasError: boolean) => ({ hasError }),
        clearResponseError: true,
    }),

    reducers({
        model: ['', { setModel: (_, { model }) => model }],
        systemPrompt: ['You are a helpful AI assistant.', { setSystemPrompt: (_, { systemPrompt }) => systemPrompt }],
        maxTokens: [null as number | null, { setMaxTokens: (_, { maxTokens }) => maxTokens }],
        thinking: [false, { setThinking: (_, { thinking }) => thinking }],
        reasoningLevel: [
            null as 'minimal' | 'low' | 'medium' | 'high' | null,
            { setReasoningLevel: (_, { reasoningLevel }) => reasoningLevel },
        ],
        tools: [null as any, { setTools: (_, { tools }) => tools }],
        messages: [
            [] as Message[],
            {
                clearConversation: () => [],
                setMessages: (_, { messages }) => messages,
                deleteMessage: (state, { index }) => state.filter((_, i) => i !== index),
                addMessage: (state, { message }) => {
                    const defaultMessage: Message = { role: 'user', content: '' }
                    return [...state, { ...defaultMessage, ...message }]
                },
                updateMessage: (state, { index, payload }) => {
                    if (index < 0 || index >= state.length) {
                        return state
                    }
                    const newState = [...state]
                    newState[index] = { ...newState[index], ...payload }
                    return newState
                },
                addResponseToHistory: (state, { content }) => {
                    if (content) {
                        return [...state, { role: 'assistant', content }]
                    }
                    return state
                },
            },
        ],
        submitting: [
            false as boolean,
            {
                submitPrompt: () => true,
                addAssistantMessageChunk: () => true,
                finalizeAssistantMessage: () => false,
            },
        ],
        currentToolCalls: [
            [] as Array<{ id: string; name: string; arguments: string }>,
            {
                submitPrompt: () => [],
                clearConversation: () => [],
                setMessages: () => [],
                clearToolCalls: () => [],
                addToolCallChunk: (state, { toolCall }) => {
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
                },
            },
        ],
        currentResponse: [
            null as string | null,
            {
                submitPrompt: () => '',
                addAssistantMessageChunk: (state, { text }) => (state ?? '') + text,
                addFinalizedContent: (state, { text }) => (state ?? '') + text,
                addResponseToHistory: () => null,
                clearConversation: () => null,
                setMessages: () => null,
            },
        ],
        lastRunDetails: [
            null as ComparisonItem | null,
            {
                submitPrompt: () => null,
                setLastRunDetails: (_, { details }) => details,
                addToComparison: () => null,
                clearConversation: () => null,
                setMessages: () => null,
            },
        ],
        comparisonItems: [
            [] as ComparisonItem[],
            {
                addToComparison: (state, { item }) => [...state, item],
                removeFromComparison: (state, { id }) => state.filter((item) => item.id !== id),
                clearComparison: () => [],
            },
        ],
        responseHasError: [
            false as boolean,
            {
                submitPrompt: () => false,
                setResponseError: (_, { hasError }) => hasError,
                clearResponseError: () => false,
                clearConversation: () => false,
                setMessages: () => false,
                addResponseToHistory: () => false,
            },
        ],
    }),
    loaders(({ values }) => ({
        modelOptions: {
            __default: [] as ModelOption[],
            loadModelOptions: async () => {
                try {
                    const response = await api.get('/api/llm_proxy/models/')
                    if (!response) {
                        return []
                    }
                    const options = response as ModelOption[]
                    const closestMatch = matchClosestModel(values.model, options)
                    if (values.model !== closestMatch) {
                        llmAnalyticsPlaygroundLogic.actions.setModel(closestMatch)
                    }
                    return options
                } catch (error) {
                    console.error('Error loading model options:', error)
                    return values.modelOptions
                }
            },
        },
    })),
    listeners(({ actions, values }) => ({
        finalizeAssistantMessage: () => {
            const toolCalls = values.currentToolCalls
            if (toolCalls.length > 0) {
                const toolCallsText = toolCalls
                    .map((tc) => JSON.stringify({ id: tc.id, name: tc.name, arguments: tc.arguments }, null, 2))
                    .join('\n\n')

                if (toolCallsText) {
                    const separator = values.currentResponse && values.currentResponse.trim() ? '\n\n' : ''
                    actions.addFinalizedContent(separator + toolCallsText)
                }
            }
            actions.clearToolCalls()
        },
        submitPrompt: async (_, breakpoint) => {
            const requestModel = values.model
            const requestSystemPrompt = values.systemPrompt
            const messagesToSend = values.messages.filter(
                (m) => (m.role === 'user' || m.role === 'assistant' || m.role === 'system') && m.content.trim()
            )

            const requestMessages = messagesToSend

            if (messagesToSend.length === 0) {
                lemonToast.error('Please add some messages before running the prompt')
                actions.finalizeAssistantMessage()
                return
            }

            let responseUsage: ComparisonItem['usage'] = {}
            let ttftMs: number | null = null
            let latencyMs: number | null = null
            let firstTokenTime: number | null = null

            // Declare startTime outside try block
            let startTime: number | null = null

            try {
                // Start timer for latency? Might be inaccurate due to network etc.
                startTime = performance.now()

                const requestData: any = {
                    system: requestSystemPrompt,
                    messages: messagesToSend.filter((m) => m.role === 'user' || m.role === 'assistant'),
                    model: requestModel,
                    thinking: values.thinking,
                }

                // Include tools if available
                if (values.tools) {
                    requestData.tools = values.tools
                }

                // Only include max_tokens if it has a value
                if (values.maxTokens !== null && values.maxTokens > 0) {
                    requestData.max_tokens = values.maxTokens
                }

                // Include optional reasoning level if provided
                if (values.reasoningLevel) {
                    requestData.reasoning_level = values.reasoningLevel
                }

                await api.stream('/api/llm_proxy/completion', {
                    method: 'POST',
                    data: requestData,
                    headers: { 'Content-Type': 'application/json' },
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
                                actions.addAssistantMessageChunk(data.text)
                            } else if (data.type === 'tool_call') {
                                if (firstTokenTime === null && startTime !== null) {
                                    firstTokenTime = performance.now()
                                    ttftMs = firstTokenTime - startTime
                                }
                                actions.addToolCallChunk(data)
                            } else if (data.type === 'usage') {
                                responseUsage = {
                                    prompt_tokens: data.prompt_tokens ?? null,
                                    completion_tokens: data.completion_tokens ?? null,
                                    total_tokens: data.total_tokens ?? null,
                                }
                            } else if (data.error) {
                                console.error('LLM Error:', data.error)
                                actions.addAssistantMessageChunk(`\n\n**LLM Error:** ${data.error}`)
                                actions.setResponseError(true)
                            }
                        } catch (e) {
                            console.error('Error parsing stream message:', e, 'Data:', event.data)
                            actions.addAssistantMessageChunk(`\n\n**Stream Error:** Could not parse response chunk.`)
                            actions.setResponseError(true)
                        }
                    },
                    onError: (err) => {
                        console.error('Stream error:', err)
                        actions.addAssistantMessageChunk(
                            `\n\n**Stream Connection Error:** ${err.message || 'Unknown error'}`
                        )
                        actions.setResponseError(true)
                        actions.finalizeAssistantMessage()
                    },
                })
                actions.finalizeAssistantMessage()
            } catch (error) {
                console.error('Submit prompt error:', error)
                actions.addAssistantMessageChunk(`\n\n**Error:** Failed to initiate prompt submission.`)
                actions.setResponseError(true)
                lemonToast.error('Failed to connect to LLM service. Please try again.')
                actions.finalizeAssistantMessage()
            } finally {
                if (startTime) {
                    const endTime = performance.now()
                    latencyMs = endTime - startTime
                }
            }

            if (values.currentResponse !== null) {
                const runDetails: ComparisonItem = {
                    id: uuid(),
                    model: requestModel,
                    systemPrompt: requestSystemPrompt,
                    requestMessages: requestMessages,
                    response: values.currentResponse,
                    usage: responseUsage,
                    ttftMs: ttftMs,
                    latencyMs: latencyMs,
                }
                actions.setLastRunDetails(runDetails)
            }
        },
        addCurrentRunToComparison: () => {
            if (values.lastRunDetails) {
                actions.addToComparison(values.lastRunDetails)
            }
        },
        setupPlaygroundFromEvent: ({ payload }) => {
            const { model, input, tools } = payload

            if (model) {
                actions.setModel(matchClosestModel(model, values.modelOptions))
            }

            // Set tools if available
            if (tools) {
                actions.setTools(tools)
            }

            let systemPromptContent: string | undefined = undefined
            let conversationMessages: Message[] = []
            let initialUserPrompt: string | undefined = undefined

            if (input) {
                try {
                    // Case 1: Input is a standard messages array
                    if (Array.isArray(input) && input.every((msg) => msg.role && msg.content)) {
                        // Find and concatenate all system messages
                        const systemMessages = input.filter((msg) => msg.role === 'system')
                        if (systemMessages.length > 0) {
                            const systemContents = systemMessages
                                .map((msg) => msg.content)
                                .filter((content): content is string => typeof content === 'string' && content.trim().length > 0)
                            if (systemContents.length > 0) {
                                systemPromptContent = systemContents.join('\n\n')
                            }
                        }

                        // Extract user and assistant messages for history (skip system messages as they're handled separately)
                        conversationMessages = input
                            .filter((msg: RawMessage) => msg.role !== 'system')
                            .map((msg: RawMessage) => extractConversationMessage(msg))
                    }
                    // Case 2: Input is just a single string prompt
                    else if (typeof input === 'string') {
                        initialUserPrompt = input
                    }
                    // Case 3: Input is some other object (try to extract content)
                    else if (isObject(input)) {
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

            // Set state in playground logic
            if (systemPromptContent) {
                actions.setSystemPrompt(systemPromptContent)
            } else {
                // Reset to default if no system prompt found in the input
                actions.setSystemPrompt('You are a helpful AI assistant.')
            }

            // If the input was just a string, add it as the first user message
            if (initialUserPrompt) {
                // Prepend it so it appears first in the playground
                conversationMessages.unshift({ role: 'user', content: initialUserPrompt })
            }

            actions.setMessages(conversationMessages) // Set the extracted history (potentially including the initial prompt)

            // Navigate to the playground
            router.actions.push(urls.llmAnalyticsPlayground())
        },
    })),
    afterMount(({ actions }) => {
        actions.loadModelOptions()
    }),
    selectors({}),
])
