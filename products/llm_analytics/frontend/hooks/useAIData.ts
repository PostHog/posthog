import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { llmAnalyticsAIDataLogic } from '../llmAnalyticsAIDataLogic'

export interface UseAIDataResult {
    input: unknown
    output: unknown
    tools: unknown
    isLoading: boolean
}

export interface EventData {
    uuid: string
    input: unknown
    output: unknown
    tools?: unknown
    traceId?: string
    timestamp?: string
}

export function useAIData(eventData: EventData | undefined): UseAIDataResult {
    const { aiDataCache, isEventLoading } = useValues(llmAnalyticsAIDataLogic)
    const { loadAIDataForEvent } = useActions(llmAnalyticsAIDataLogic)
    const aiEventsRolloutEnabled = useFeatureFlag('AI_EVENTS_TABLE_ROLLOUT')

    const eventId = eventData?.uuid
    const input = eventData?.input
    const output = eventData?.output
    const tools = eventData?.tools
    const traceId = eventData?.traceId
    const timestamp = eventData?.timestamp
    const cached = eventId ? aiDataCache[eventId] : undefined
    const loading = eventId ? isEventLoading(eventId) : false

    useEffect(() => {
        if (!eventId || cached || loading) {
            return
        }

        loadAIDataForEvent({
            eventId,
            input,
            output,
            tools,
            traceId,
            timestamp,
            aiEventsRolloutEnabled,
        })
    }, [cached, loading, loadAIDataForEvent, eventId, input, output, tools, traceId, timestamp, aiEventsRolloutEnabled])

    if (!eventId) {
        return {
            input,
            output,
            tools,
            isLoading: false,
        }
    }

    return {
        input: cached?.input,
        output: cached?.output,
        tools: cached?.tools,
        isLoading: loading || !cached,
    }
}
