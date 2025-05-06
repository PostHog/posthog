import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

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
                clearConversation: () => null,
                setMessages: () => null,
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
            const messagesToSend = values.messages.filter(
                (m) => (m.role === 'user' || m.role === 'assistant' || m.role === 'system') && m.content.trim()
            )

            if (messagesToSend.length === 0) {
                console.warn('SubmitPrompt called with no valid messages.')
                actions.finalizeAssistantMessage()
                return
            }

            try {
                await api.stream('/api/llm_proxy/completion', {
                    method: 'POST',
                    data: {
                        system: values.systemPrompt,
                        messages: messagesToSend.filter((m) => m.role === 'user' || m.role === 'assistant'),
                        model: values.model,
                        thinking: values.thinking,
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
                                actions.addAssistantMessageChunk(data.text)
                                // } else if (data.type === 'reasoning') {
                                //     // TODO: Add reasoning
                                // } else if (data.type === 'usage') {
                                //     // TODO: Add usage
                            } else if (data.error) {
                                console.error('LLM Error:', data.error)
                                actions.addAssistantMessageChunk(`\n\n**LLM Error:** ${data.error}`)
                            }
                        } catch (e) {
                            console.error('Error parsing stream message:', e, 'Data:', event.data)
                            actions.addAssistantMessageChunk(`\n\n**Stream Error:** Could not parse response chunk.`)
                        }
                    },
                    onError: (err) => {
                        console.error('Stream error:', err)
                        actions.addAssistantMessageChunk(
                            `\n\n**Stream Connection Error:** ${err.message || 'Unknown error'}`
                        )
                        actions.finalizeAssistantMessage()
                    },
                })
                actions.finalizeAssistantMessage()
            } catch (error) {
                console.error('Submit prompt error:', error)
                actions.addAssistantMessageChunk(`\n\n**Error:** Failed to initiate prompt submission.`)
                actions.finalizeAssistantMessage()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadModelOptions()
    }),
    selectors({}),
])
