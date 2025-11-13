import { actions, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { FALLBACK_DELAY_MS, TEXT_REPR_API_TIMEOUT_MS } from './constants'
import type { textViewLogicType } from './textViewLogicType'

interface TraceTreeNode {
    event: LLMTraceEvent
    children?: TraceTreeNode[]
}

export interface TextViewLogicProps {
    trace?: LLMTrace
    event?: LLMTraceEvent
    tree?: TraceTreeNode[]
    teamId: number | null
    onFallback?: () => void
}

export const textViewLogic = kea<textViewLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'text-view', 'textViewLogic']),
    props({} as TextViewLogicProps),
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
        triggerFallback: true,
    }),
    loaders(({ props }) => ({
        textRepr: {
            __default: null as string | null,
            fetchTextRepr: async () => {
                // Return empty if no data or no team ID
                if (!props.trace && !props.event) {
                    return ''
                }
                if (!props.teamId) {
                    return ''
                }

                // Prepare request based on what data we have
                let requestData: any

                if (props.trace && props.tree) {
                    // Full trace view - need to send tree structure with children
                    // Recursively convert tree nodes to { event, children } format
                    const convertTreeNode = (node: TraceTreeNode): any => ({
                        event: node.event,
                        children: node.children ? node.children.map(convertTreeNode) : [],
                    })

                    requestData = {
                        event_type: '$ai_trace',
                        data: {
                            trace: {
                                ...props.trace,
                                trace_id: props.trace.id,
                                name: props.trace.traceName || 'Trace',
                            },
                            hierarchy: props.tree.map(convertTreeNode),
                        },
                        options: {
                            truncated: true,
                            include_markers: true,
                            include_line_numbers: true,
                        },
                    }
                } else if (props.event) {
                    // Single event view
                    requestData = {
                        event_type: props.event.event,
                        data: props.event,
                        options: {
                            truncated: true,
                            include_markers: true,
                            include_line_numbers: true,
                        },
                    }
                } else {
                    return ''
                }

                // Create abort controller for timeout
                const abortController = new AbortController()
                const timeoutId = setTimeout(() => abortController.abort(), TEXT_REPR_API_TIMEOUT_MS)

                try {
                    // Call Django API with timeout
                    const response = await api.create(
                        `api/environments/${props.teamId}/llm_analytics/text_repr/`,
                        requestData,
                        { signal: abortController.signal }
                    )
                    clearTimeout(timeoutId)
                    return response.text || ''
                } catch (apiErr) {
                    clearTimeout(timeoutId)
                    const isTimeout = apiErr instanceof Error && apiErr.name === 'AbortError'
                    const errorMessage = isTimeout
                        ? 'Text view generation timed out'
                        : apiErr instanceof Error
                          ? apiErr.message
                          : 'Failed to load text representation'
                    throw new Error(errorMessage)
                }
            },
        },
    })),
    listeners(({ props, actions }) => ({
        fetchTextReprFailure: async ({ error }) => {
            console.error('Error fetching text representation:', error)
            // Trigger fallback to standard view with a small delay
            actions.triggerFallback()
        },
        triggerFallback: async () => {
            if (props.onFallback) {
                // Small delay to show the fallback message briefly
                setTimeout(() => {
                    props.onFallback?.()
                }, FALLBACK_DELAY_MS)
            }
        },
    })),
])
