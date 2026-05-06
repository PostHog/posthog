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

    // Only fire the loader when a real fetch is possible. If we fired it with the flag
    // off (or before flags resolve, when useFeatureFlag returns false), the loader would
    // passthrough and cache `{ input: undefined, output: undefined }` — and once the flag
    // later resolves to true the effect would short-circuit on `cached` and never refetch.
    const canFetch = aiEventsRolloutEnabled && !!traceId && !!timestamp

    useEffect(() => {
        if (!eventId || cached || loading || !canFetch) {
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
    }, [
        cached,
        loading,
        canFetch,
        loadAIDataForEvent,
        eventId,
        input,
        output,
        tools,
        traceId,
        timestamp,
        aiEventsRolloutEnabled,
    ])

    if (!eventId) {
        return {
            input,
            output,
            tools,
            isLoading: false,
        }
    }

    // When we can't fetch, fall back to whatever was passed in — there's nothing to wait
    // for. Once the flag flips on, the effect re-runs and `cached` takes over.
    return {
        input: cached?.input ?? input,
        output: cached?.output ?? output,
        tools: cached?.tools ?? tools,
        isLoading: canFetch && (loading || !cached),
    }
}
