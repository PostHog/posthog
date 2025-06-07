import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { uuid } from 'lib/utils'
import { isObject } from 'lib/utils'
import { urls } from 'scenes/urls'

import type { llmObservabilityPlaygroundLogicType } from './llmObservabilityPlaygroundLogicType'

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

export type MessageRole = 'user' | 'assistant' | 'system'

export interface Message {
    role: MessageRole
    content: string
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

export const llmObservabilityPlaygroundLogic = kea<llmObservabilityPlaygroundLogicType>([
    path(['products', 'llm_observability', 'frontend', 'llmObservabilityPlaygroundLogic']),

    actions({
        setModel: (model: string) => ({ model }),
        setSystemPrompt: (systemPrompt: string) => ({ systemPrompt }),
        setTemperature: (temperature: number) => ({ temperature }),
        setMaxTokens: (maxTokens: number) => ({ maxTokens }),
        setThinking: (thinking: boolean) => ({ thinking }),
        clearConversation: true,
        submitPrompt: true,
        setMessages: (messages: Message[]) => ({ messages }),
        deleteMessage: (index: number) => ({ index }),
        addAssistantMessageChunk: (text: string) => ({ text }),
        finalizeAssistantMessage: true,
        addMessage: (message?: Partial<Message>) => ({ message }),
        updateMessage: (index: number, payload: Partial<Message>) => ({ index, payload }),
        addResponseToHistory: (content: string) => ({ content }),
        addCurrentRunToComparison: true,
        setLastRunDetails: (details: ComparisonItem | null) => ({ details }),
        addToComparison: (item: ComparisonItem) => ({ item }),
        removeFromComparison: (id: string) => ({ id }),
        clearComparison: true,
        setupPlaygroundFromEvent: (payload: { model?: string; input?: any }) => ({ payload }),
        setResponseError: (hasError: boolean) => ({ hasError }),
        clearResponseError: true,
    }),

    reducers({
        model: ['', { setModel: (_, { model }) => model }],
        systemPrompt: ['You are a helpful AI assistant.', { setSystemPrompt: (_, { systemPrompt }) => systemPrompt }],
        temperature: [0.7, { setTemperature: (_, { temperature }) => temperature }],
        maxTokens: [1024, { setMaxTokens: (_, { maxTokens }) => maxTokens }],
        thinking: [false, { setThinking: (_, { thinking }) => thinking }],
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
        currentResponse: [
            null as string | null,
            {
                submitPrompt: () => '',
                addAssistantMessageChunk: (state, { text }) => (state ?? '') + text,
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
                    if (!values.model && (response as ModelOption[])?.length > 0) {
                        llmObservabilityPlaygroundLogic.actions.setModel((response as ModelOption[])[0].id)
                    }
                    return response as ModelOption[]
                } catch (error) {
                    console.error('Error loading model options:', error)
                    return values.modelOptions
                }
            },
        },
    })),
    listeners(({ actions, values }) => ({
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

                await api.stream('/api/llm_proxy/completion', {
                    method: 'POST',
                    data: {
                        system: requestSystemPrompt,
                        messages: messagesToSend.filter((m) => m.role === 'user' || m.role === 'assistant'),
                        model: requestModel,
                        thinking: values.thinking,
                        temperature: values.temperature,
                        max_tokens: values.maxTokens,
                    },
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
            const { model, input } = payload

            // Set model if available
            if (model) {
                actions.setModel(model)
            }

            let systemPromptContent: string | undefined = undefined
            let conversationMessages: Message[] = []
            let initialUserPrompt: string | undefined = undefined

            if (input) {
                try {
                    // Case 1: Input is a standard messages array
                    if (Array.isArray(input) && input.every((msg) => msg.role && msg.content)) {
                        // Find and set system message
                        const systemMessage = input.find((msg) => msg.role === 'system')
                        if (systemMessage?.content && typeof systemMessage.content === 'string') {
                            systemPromptContent = systemMessage.content
                        }

                        // Extract user and assistant messages for history
                        conversationMessages = input
                            .filter((msg) => msg.role === 'user' || msg.role === 'assistant')
                            .map((msg) => ({
                                role: msg.role as 'user' | 'assistant',
                                content: typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content),
                            }))
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
            router.actions.push(urls.llmObservabilityPlayground())
        },
    })),
    afterMount(({ actions }) => {
        actions.loadModelOptions()
    }),
    selectors({}),
])
