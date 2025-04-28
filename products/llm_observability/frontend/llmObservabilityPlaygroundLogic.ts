import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
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

export interface Message {
    role: 'user' | 'assistant' | 'system'
    content: string
}

export const llmObservabilityPlaygroundLogic = kea<llmObservabilityPlaygroundLogicType>([
    path(['products', 'llm_observability', 'frontend', 'llmObservabilityPlaygroundLogic']),

    actions({
        setPrompt: (prompt: string) => ({ prompt }),
        setModel: (model: string) => ({ model }),
        setSystemPrompt: (systemPrompt: string) => ({ systemPrompt }),
        setTemperature: (temperature: number) => ({ temperature }),
        setMaxTokens: (maxTokens: number) => ({ maxTokens }),
        setThinking: (thinking: boolean) => ({ thinking }),
        clearConversation: true,
        submitPrompt: true,
        addAssistantMessage: (message: string) => ({ message }),
        addUserMessage: (message: string) => ({ message }),
        appendAssistantText: (text: string) => ({ text }),
    }),

    reducers({
        prompt: ['', { setPrompt: (_, { prompt }) => prompt }],
        model: ['', { setModel: (_, { model }) => model }],
        systemPrompt: ['You are a helpful AI assistant.', { setSystemPrompt: (_, { systemPrompt }) => systemPrompt }],
        temperature: [0.7, { setTemperature: (_, { temperature }) => temperature }],
        maxTokens: [1024, { setMaxTokens: (_, { maxTokens }) => maxTokens }],
        thinking: [false, { setThinking: (_, { thinking }) => thinking }],
        messages: [
            [] as Message[],
            {
                clearConversation: () => [],
                addUserMessage: (state, { message }) => {
                    return [...state, { role: 'user', content: message }]
                },
                addAssistantMessage: (state, { message }) => {
                    return [...state, { role: 'assistant', content: message }]
                },
                appendAssistantText: (state, { text }) => {
                    const newState = [...state]
                    const last = newState[newState.length - 1]
                    if (last?.role === 'assistant') {
                        last.content += text
                        return newState
                    }
                    return state
                },
            },
        ],
    }),
    loaders(({ values }: any) => ({
        modelOptions: {
            __default: [] as ModelOption[],
            loadModelOptions: async () => {
                try {
                    const response = await api.get('/api/llm_proxy/models/')
                    return response as ModelOption[]
                } catch (error) {
                    console.error('Error loading model options:', error)
                    return values.modelOptions
                }
            },
        },
    })),
    listeners(({ actions, values }: any) => ({
        submitPrompt: async () => {
            if (!values.prompt.trim()) {
                return
            }

            actions.addUserMessage(values.prompt)
            actions.addAssistantMessage('')
            await api.stream('/api/llm_proxy/completion', {
                method: 'POST',
                data: {
                    system: values.systemPrompt,
                    messages: values.messages,
                    model: values.model,
                    thinking: values.thinking,
                },
                headers: { 'Content-Type': 'application/json' },
                onMessage: (event) => {
                    if (!event.data) {
                        return
                    }
                    const data = JSON.parse(event.data)
                    if (data.type === 'text') {
                        actions.appendAssistantText(data.text)
                    } else if (data.type === 'reasoning') {
                        // console.log('Thinking:', data.reasoning)
                    } else if (data.type === 'usage') {
                        // handle usage if needed
                    } else if (data.error) {
                        console.error('LLM Error:', data.error)
                    }
                },
                onError: (err) => {
                    console.error('Stream error:', err)
                },
            })
        },
    })),
    afterMount(({ actions }: any) => {
        actions.loadModelOptions()
    }),
])
