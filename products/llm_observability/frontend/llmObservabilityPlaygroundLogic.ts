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
        clearConversation: true,
        submitPrompt: true,
        addAssistantMessage: (message: string) => ({ message }),
    }),

    reducers({
        prompt: ['', { setPrompt: (_, { prompt }) => prompt }],
        model: ['gpt-3.5-turbo', { setModel: (_, { model }) => model }],
        systemPrompt: ['You are a helpful AI assistant.', { setSystemPrompt: (_, { systemPrompt }) => systemPrompt }],
        temperature: [0.7, { setTemperature: (_, { temperature }) => temperature }],
        maxTokens: [1024, { setMaxTokens: (_, { maxTokens }) => maxTokens }],
        messages: [
            [] as Message[],
            {
                clearConversation: () => [],
                submitPrompt: (state) => {
                    if (!state.length || state[state.length - 1].role !== 'user') {
                        return state
                    }
                    return state
                },
                addAssistantMessage: (state, { message }) => {
                    return [...state, { role: 'assistant', content: message }]
                },
            },
        ],
    }),

    selectors({
        availableModels: [
            () => [],
            (): ModelOption[] => [
                {
                    id: 'gpt-3.5-turbo',
                    name: 'GPT-3.5 Turbo',
                    provider: 'OpenAI',
                    description: 'Fast model for most tasks',
                },
                {
                    id: 'gpt-4o',
                    name: 'GPT-4o',
                    provider: 'OpenAI',
                    description: 'Advanced reasoning capabilities',
                },
                {
                    id: 'o1-mini',
                    name: 'O1-Mini',
                    provider: 'Anthropic',
                    description: 'Fast, compact model for general use',
                },
            ],
        ],
    }),

    loaders(({ values }) => ({
        modelOptions: {
            __default: [] as ModelOption[],
            loadModelOptions: async (): Promise<ModelOption[]> => {
                try {
                    const response = await api.get('api/llm_playground/models/')
                    return response || values.availableModels
                } catch (error) {
                    console.error('Error loading model options:', error)
                    return values.availableModels
                }
            },
        },
        generationResponse: {
            __default: null as PlaygroundResponse | null,
            generateResponse: async (): Promise<PlaygroundResponse | null> => {
                if (!values.prompt) {
                    return null
                }

                // Add user message to conversation history
                // const updatedMessages = [...values.messages, { role: 'user' as const, content: values.prompt }]

                try {
                    const response = await api.create('api/llm_playground/generate/', {
                        prompt: values.prompt,
                        model: values.model,
                        temperature: values.temperature,
                        max_tokens: values.maxTokens,
                        system_prompt: values.systemPrompt,
                        messages: values.messages,
                    })
                    return response as PlaygroundResponse
                } catch (error) {
                    console.error('Error generating response:', error)
                    throw error
                }
            },
        },
    })),

    listeners(({ actions, asyncActions, values }) => ({
        submitPrompt: async () => {
            if (!values.prompt.trim()) {
                return
            }

            // Call the API to generate a response
            try {
                await asyncActions.generateResponse()

                // Update messages with the user's prompt and the response
                actions.setPrompt('')
            } catch (error) {
                console.error('Error in submitPrompt:', error)
            }
        },

        generateResponseSuccess: ({ generationResponse }) => {
            if (generationResponse?.text) {
                actions.addAssistantMessage(generationResponse.text)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadModelOptions()
    }),
])
