import { useActions, useValues } from 'kea'

import { IconChat } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

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
    const { featureFlags } = useValues(featureFlagLogic)

    const { input, output, isLoading } = useAIData({
        uuid: eventId,
        properties: eventProperties,
    })

    const handleTryInPlayground = (): void => {
        setupPlaygroundFromEvent({
            model: eventProperties.$ai_model,
            input,
        })
    }

    const showPlaygroundButton =
        eventProperties.$ai_model && input && featureFlags[FEATURE_FLAGS.LLM_OBSERVABILITY_PLAYGROUND]

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
