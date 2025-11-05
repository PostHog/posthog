/**
 * Logic for Summary Tab Content
 *
 * Manages API calls for trace/event summarization and state.
 */
import { actions, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { LLMTrace, LLMTraceEvent } from '../types'
import type { summaryTabLogicType } from './summaryTabLogicType'

export interface SummaryTabLogicProps {
    trace?: LLMTrace
    event?: LLMTraceEvent
    tree?: any[]
}

export const summaryTabLogic = kea<summaryTabLogicType>([
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
    actions({
        generateSummary: true,
    }),
    loaders(({ props }) => ({
        summary: [
            null as string | null,
            {
                generateSummary: async () => {
                    // Determine if we're summarizing a trace or an event
                    const isTrace = !!props.trace

                    // Build request payload
                    const payload = isTrace
                        ? {
                              summarize_type: 'trace',
                              data: {
                                  trace: props.trace,
                                  hierarchy: props.tree || [],
                              },
                          }
                        : {
                              summarize_type: 'event',
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
                        },
                        body: JSON.stringify(payload),
                        credentials: 'include',
                    })

                    if (!response.ok) {
                        const errorData = await response.json().catch(() => ({}))
                        throw new Error(errorData.detail || errorData.error || 'Failed to generate summary')
                    }

                    const data = await response.json()
                    return data.summary
                },
            },
        ],
    })),
    selectors({
        summaryError: [
            (s) => [s.summaryFailure],
            (summaryFailure): string | null => {
                if (!summaryFailure) {
                    return null
                }
                // Extract error message
                if (typeof summaryFailure === 'string') {
                    return summaryFailure
                }
                if (summaryFailure?.detail) {
                    return summaryFailure.detail
                }
                return 'An unexpected error occurred'
            },
        ],
    }),
])
