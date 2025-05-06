import { IconChat } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { isObject } from 'lib/utils'
import { urls } from 'scenes/urls'

import { EventType } from '~/types'

import { llmObservabilityPlaygroundLogic, Message } from '../llmObservabilityPlaygroundLogic'
import { ConversationMessagesDisplay } from './ConversationMessagesDisplay'
import { MetadataHeader } from './MetadataHeader'

export function ConversationDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    const { setSystemPrompt, setModel, setMessages } = useActions(llmObservabilityPlaygroundLogic)

    const handleTryInPlayground = (): void => {
        // Set model if available
        if (eventProperties.$ai_model) {
            setModel(eventProperties.$ai_model)
        }

        const input = eventProperties.$ai_input
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
                    if (input.content && typeof input.content === 'string') {
                        initialUserPrompt = input.content
                    } else {
                        initialUserPrompt = JSON.stringify(input, null, 2)
                    }
                }
            } catch (e) {
                console.error('Error processing $ai_input for playground:', e)
                initialUserPrompt = String(input)
                conversationMessages = []
            }
        }

        // Set state in playground logic
        if (systemPromptContent) {
            setSystemPrompt(systemPromptContent)
        }

        // If the input was just a string, add it as the first user message
        if (initialUserPrompt) {
            // Prepend it so it appears first in the playground
            conversationMessages.unshift({ role: 'user', content: initialUserPrompt })
        }

        setMessages(conversationMessages) // Set the extracted history (potentially including the initial prompt)

        // Navigate to the playground
        router.actions.push(urls.llmObservabilityPlayground())
    }

    return (
        <>
            <header className="mb-2 flex justify-between items-center">
                <MetadataHeader
                    inputTokens={eventProperties.$ai_input_tokens}
                    outputTokens={eventProperties.$ai_output_tokens}
                    totalCostUsd={eventProperties.$ai_total_cost_usd}
                    model={eventProperties.$ai_model}
                    latency={eventProperties.$ai_latency}
                />

                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconChat />}
                    onClick={handleTryInPlayground}
                    tooltip="Try this prompt in the playground"
                >
                    Try in Playground
                </LemonButton>
            </header>
            <ConversationMessagesDisplay
                input={eventProperties.$ai_input}
                output={eventProperties.$ai_output_choices ?? eventProperties.$ai_output ?? eventProperties.$ai_error}
                tools={eventProperties.$ai_tools}
                httpStatus={eventProperties.$ai_http_status}
                raisedError={eventProperties.$ai_is_error}
                bordered
            />
        </>
    )
}
