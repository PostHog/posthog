import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { getCookie } from 'lib/api'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import type { summaryViewLogicType } from './summaryViewLogicType'

export type SummaryMode = 'minimal' | 'detailed'

export interface SummaryBullet {
    text: string
    line_refs: string
}

export interface InterestingNote {
    text: string
    line_refs: string // Can be empty string if no line refs
}

export interface StructuredSummary {
    title: string
    flow_diagram: string
    summary_bullets: SummaryBullet[]
    interesting_notes: InterestingNote[] // Empty array if none
}

export interface SummaryViewLogicProps {
    trace?: LLMTrace
    event?: LLMTraceEvent
    tree?: any[]
}

export const summaryViewLogic = kea<summaryViewLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'summary-view', 'summaryViewLogic']),
    props({} as SummaryViewLogicProps),
    connect({
        values: [maxGlobalLogic, ['dataProcessingAccepted']],
    }),
    key((props) => {
        // Use trace ID or event ID as the key
        if (props.trace) {
            return `trace-${props.trace.id}`
        }
        if (props.event) {
            return `event-${props.event.id}`
        }
        return 'unknown'
    }),
    actions({
        setSummaryMode: (mode: SummaryMode) => ({ mode }),
        regenerateSummary: true,
        toggleFlowExpanded: true,
        toggleSummaryExpanded: true,
        toggleNotesExpanded: true,
    }),
    reducers({
        summaryMode: [
            'minimal' as SummaryMode,
            {
                setSummaryMode: (_, { mode }) => mode,
            },
        ],
        isFlowExpanded: [
            false,
            {
                toggleFlowExpanded: (state) => !state,
            },
        ],
        isSummaryExpanded: [
            true,
            {
                toggleSummaryExpanded: (state) => !state,
            },
        ],
        isNotesExpanded: [
            true,
            {
                toggleNotesExpanded: (state) => !state,
            },
        ],
    }),
    loaders(({ props, values }) => ({
        summaryData: {
            __default: null as { summary: StructuredSummary; text_repr: string } | null,
            generateSummary: async ({ mode, forceRefresh = false }: { mode: SummaryMode; forceRefresh?: boolean }) => {
                // Check data processing consent before making API call
                if (!values.dataProcessingAccepted) {
                    throw new Error('AI data processing must be approved before generating summaries')
                }

                // Determine if we're summarizing a trace or an event
                const isTrace = !!props.trace

                // Build request payload
                const payload = isTrace
                    ? {
                          summarize_type: 'trace',
                          mode,
                          force_refresh: forceRefresh,
                          data: {
                              trace: props.trace,
                              hierarchy: props.tree || [],
                          },
                      }
                    : {
                          summarize_type: 'event',
                          mode,
                          force_refresh: forceRefresh,
                          data: {
                              event: props.event,
                          },
                      }

                // Call the summarization API endpoint
                const teamId = (window as any).POSTHOG_APP_CONTEXT?.current_team?.id
                if (!teamId) {
                    throw new Error('Team ID not available')
                }

                const url = `/api/environments/${teamId}/llm_analytics/summarization/`
                const response = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('posthog_csrftoken') || '',
                    },
                    body: JSON.stringify(payload),
                    credentials: 'include',
                })

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}))
                    throw new Error(errorData.detail || errorData.error || 'Failed to generate summary')
                }

                const data = await response.json()
                return {
                    summary: data.summary,
                    text_repr: data.text_repr,
                }
            },
        },
    })),
    listeners(({ actions, values }) => ({
        regenerateSummary: () => {
            // Regenerate with current mode but force refresh to bust cache
            actions.generateSummary({ mode: values.summaryMode, forceRefresh: true })
        },
        setSummaryMode: ({ mode }) => {
            // Generate summary for new mode if we don't have data yet
            if (values.summaryData) {
                actions.generateSummary({ mode, forceRefresh: false })
            }
        },
    })),
])
