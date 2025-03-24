import { EventType } from '~/types'

import { ConversationMessagesDisplay } from './ConversationMessagesDisplay'
import { MetadataHeader } from './MetadataHeader'

export function ConversationDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    return (
        <>
            <header className="mb-2">
                <MetadataHeader
                    inputTokens={eventProperties.$ai_input_tokens}
                    outputTokens={eventProperties.$ai_output_tokens}
                    totalCostUsd={eventProperties.$ai_total_cost_usd}
                    model={eventProperties.$ai_model}
                    latency={eventProperties.$ai_latency}
                />
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
