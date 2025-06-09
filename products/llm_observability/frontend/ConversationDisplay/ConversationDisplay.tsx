import { IconChat } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { EventType } from '~/types'

import { llmObservabilityPlaygroundLogic } from '../llmObservabilityPlaygroundLogic'
import { ConversationMessagesDisplay } from './ConversationMessagesDisplay'
import { MetadataHeader } from './MetadataHeader'

export function ConversationDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    const { setupPlaygroundFromEvent } = useActions(llmObservabilityPlaygroundLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const handleTryInPlayground = (): void => {
        setupPlaygroundFromEvent({
            model: eventProperties.$ai_model,
            input: eventProperties.$ai_input,
        })
    }

    const showPlaygroundButton =
        eventProperties.$ai_model &&
        eventProperties.$ai_input &&
        featureFlags[FEATURE_FLAGS.LLM_OBSERVABILITY_PLAYGROUND]

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

                {showPlaygroundButton && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconChat />}
                        onClick={handleTryInPlayground}
                        tooltip="Try this prompt in the playground"
                    >
                        Try in Playground
                    </LemonButton>
                )}
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
