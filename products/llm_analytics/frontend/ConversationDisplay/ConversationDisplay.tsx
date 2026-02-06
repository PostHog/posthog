import { useActions } from 'kea'

import { IconChat } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { EventType } from '~/types'

import { AIDataLoading } from '../components/AIDataLoading'
import { useAIData } from '../hooks/useAIData'
import { llmAnalyticsPlaygroundLogic } from '../llmAnalyticsPlaygroundLogic'
import { normalizeMessages } from '../utils'
import { ConversationMessagesDisplay } from './ConversationMessagesDisplay'
import { MetadataHeader } from './MetadataHeader'

export interface ConversationDisplayProps {
    eventProperties: EventType['properties']
    eventId: string
}

export function ConversationDisplay({ eventProperties, eventId }: ConversationDisplayProps): JSX.Element {
    const { setupPlaygroundFromEvent } = useActions(llmAnalyticsPlaygroundLogic)

    const { input, output, isLoading } = useAIData({
        uuid: eventId,
        input: eventProperties.$ai_input,
        output: eventProperties.$ai_output_choices,
    })

    const handleTryInPlayground = (): void => {
        setupPlaygroundFromEvent({
            model: eventProperties.$ai_model,
            input,
        })
    }

    const showPlaygroundButton = eventProperties.$ai_model && input

    return (
        <>
            <header className="mb-2 flex justify-between items-center">
                <MetadataHeader
                    inputTokens={eventProperties.$ai_input_tokens}
                    outputTokens={eventProperties.$ai_output_tokens}
                    cacheReadTokens={eventProperties.$ai_cache_read_input_tokens}
                    cacheWriteTokens={eventProperties.$ai_cache_creation_input_tokens}
                    totalCostUsd={eventProperties.$ai_total_cost_usd}
                    model={eventProperties.$ai_model}
                    latency={eventProperties.$ai_latency}
                    timeToFirstToken={eventProperties.$ai_time_to_first_token}
                    isStreaming={eventProperties.$ai_stream === true}
                    timestamp={eventProperties.timestamp}
                />

                {showPlaygroundButton && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconChat />}
                        onClick={handleTryInPlayground}
                        tooltip="Try this prompt in the playground"
                        data-attr="try-in-playground-conversation"
                    >
                        Try in Playground
                    </LemonButton>
                )}
            </header>
            {isLoading ? (
                <AIDataLoading variant="block" />
            ) : (
                <ConversationMessagesDisplay
                    inputNormalized={normalizeMessages(input, 'user', eventProperties.$ai_tools)}
                    outputNormalized={normalizeMessages(output, 'assistant')}
                    errorData={eventProperties.$ai_error}
                    httpStatus={eventProperties.$ai_http_status}
                    raisedError={eventProperties.$ai_is_error}
                    bordered
                />
            )}
        </>
    )
}
