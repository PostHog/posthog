import React from 'react'

import type { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import type { DisplayOption } from '../llmAnalyticsTraceLogic'
import { hasTraceContent } from '../traceViewUtils'
import { isLLMEvent } from '../utils'
import { EventContentDisplay, EventContentDisplayAsync, EventContentGeneration } from './EventContentWithAsyncData'
import { NoTopLevelTraceEmptyState } from './NoTopLevelTraceEmptyState'

export function TraceConversationContent({
    event,
    traceId,
    searchQuery,
    displayOption,
    traceMetricsSlot,
}: {
    event: LLMTrace | LLMTraceEvent
    traceId?: string | null
    searchQuery?: string
    displayOption?: DisplayOption
    traceMetricsSlot?: React.ReactNode
}): JSX.Element {
    if (isLLMEvent(event)) {
        if (event.event === '$ai_generation') {
            return (
                <EventContentGeneration
                    eventId={event.id}
                    traceId={traceId}
                    rawInput={event.properties.$ai_input}
                    rawOutput={event.properties.$ai_output_choices ?? event.properties.$ai_output}
                    tools={event.properties.$ai_tools}
                    errorData={event.properties.$ai_error}
                    httpStatus={event.properties.$ai_http_status}
                    raisedError={event.properties.$ai_is_error}
                    searchQuery={searchQuery}
                    displayOption={displayOption}
                />
            )
        }

        if (event.event === '$ai_embedding') {
            return (
                <EventContentDisplayAsync
                    eventId={event.id}
                    rawInput={event.properties.$ai_input}
                    rawOutput="Embedding vector generated"
                />
            )
        }

        return (
            <EventContentDisplayAsync
                eventId={event.id}
                rawInput={event.properties.$ai_input_state}
                rawOutput={event.properties.$ai_output_state ?? event.properties.$ai_error}
                raisedError={event.properties.$ai_is_error}
            />
        )
    }

    if (!hasTraceContent(event)) {
        return <NoTopLevelTraceEmptyState />
    }

    return (
        <>
            {traceMetricsSlot}
            <EventContentDisplay rawInput={event.inputState} rawOutput={event.outputState} searchQuery={searchQuery} />
        </>
    )
}
