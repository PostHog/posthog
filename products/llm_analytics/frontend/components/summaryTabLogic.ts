/**
 * Logic for Summary Tab Content
 *
 * Manages API calls for trace/event summarization and state.
 */
import { kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { getCookie } from 'lib/api'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

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
    flow_diagram: string
    summary_bullets: SummaryBullet[]
    interesting_notes: InterestingNote[] // Empty array if none
}

export interface SummaryTabLogicProps {
    trace?: LLMTrace
    event?: LLMTraceEvent
    tree?: any[]
}

export const summaryTabLogic = kea([
    path(['products', 'llm_analytics', 'frontend', 'components', 'summaryTabLogic']),
    props({} as SummaryTabLogicProps),
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
    loaders(({ props }) => ({
        summaryData: {
            __default: null as { summary: StructuredSummary; text_repr: string } | null,
            generateSummary: async (mode: SummaryMode = 'minimal') => {
                // Determine if we're summarizing a trace or an event
                const isTrace = !!props.trace

                // Build request payload
                const payload = isTrace
                    ? {
                          summarize_type: 'trace',
                          mode,
                          data: {
                              trace: props.trace,
                              hierarchy: props.tree || [],
                          },
                      }
                    : {
                          summarize_type: 'event',
                          mode,
                          data: {
                              event: props.event,
                          },
                      }

                // Call the summarization API endpoint
                const teamId = (window as any).POSTHOG_APP_CONTEXT?.current_team?.id
                if (!teamId) {
                    throw new Error('Team ID not available')
                }

                const url = `/api/projects/${teamId}/llm_analytics/summarize/`
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
])
