import { IconChat } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { isObject } from 'lib/utils'
import { urls } from 'scenes/urls'

import { EventType } from '~/types'

import { llmObservabilityPlaygroundLogic } from '../llmObservabilityPlaygroundLogic'
import { ConversationMessagesDisplay } from './ConversationMessagesDisplay'
import { MetadataHeader } from './MetadataHeader'

export function ConversationDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    const { setSystemPrompt, setModel, setPrompt } = useActions(llmObservabilityPlaygroundLogic)

    const handleTryInPlayground = (): void => {
        // Set model if available
        if (eventProperties.$ai_model) {
            setModel(eventProperties.$ai_model)
        }
        // Handle input based on its format
        const input = eventProperties.$ai_input
        if (input) {
            try {
                // If it's already a well-formatted messages array, use it directly
                if (Array.isArray(input) && input.every((msg) => msg.role && msg.content)) {
                    // Find system message if it exists
                    const systemMessage = input.find((msg) => msg.role === 'system')
                    if (systemMessage?.content && typeof systemMessage.content === 'string') {
                        setSystemPrompt(systemMessage.content)
                    }

                    // Keep only the last user message as the prompt
                    const lastUserMessage = [...input].reverse().find((msg) => msg.role === 'user')
                    if (lastUserMessage?.content) {
                        if (typeof lastUserMessage.content === 'string') {
                            setPrompt(lastUserMessage.content)
                        } else if (isObject(lastUserMessage.content)) {
                            setPrompt(JSON.stringify(lastUserMessage.content))
                        }
                    }

                    // Set all previous messages (excluding the last user message)
                    const previousMessages = input.filter(
                        (msg) => !(msg.role === 'user' && msg.content === lastUserMessage?.content)
                    )
                    if (previousMessages.length > 0) {
                        //setMessages(previousMessages);
                    }
                }
                // If a single string, use as prompt
                else if (typeof input === 'string') {
                    setPrompt(input)
                }
                // If it's a normalized object
                else if (isObject(input)) {
                    // Try to extract content
                    if (input.content && typeof input.content === 'string') {
                        setPrompt(input.content)
                    } else {
                        // Fallback to stringify the object
                        setPrompt(JSON.stringify(input, null, 2))
                    }
                }
            } catch (e) {
                // Fallback: convert to string and use as prompt
                setPrompt(String(input))
            }
        }

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
