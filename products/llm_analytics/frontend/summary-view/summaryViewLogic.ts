import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { teamLogic } from 'scenes/teamLogic'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { EnrichedTraceTreeNode } from '../llmAnalyticsTraceDataLogic'
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
    tree?: EnrichedTraceTreeNode[]
    autoGenerate?: boolean
}

export const summaryViewLogic = kea<summaryViewLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'summary-view', 'summaryViewLogic']),
    props({} as SummaryViewLogicProps),
    connect({
        values: [maxGlobalLogic, ['dataProcessingAccepted'], teamLogic, ['currentTeamId']],
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
        loadCachedSummary: true,
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
    selectors({
        entityId: [
            () => [(_, props) => props],
            (props: SummaryViewLogicProps): string | null => {
                if (props.trace) {
                    return props.trace.id
                }
                if (props.event) {
                    return props.event.id
                }
                return null
            },
        ],
    }),
    loaders(({ props, values }) => ({
        summaryData: {
            __default: null as { summary: StructuredSummary; text_repr: string } | null,
            generateSummary: async ({ mode, forceRefresh }: { mode: SummaryMode; forceRefresh?: boolean }) => {
                // Initialize here rather than in the function signature to avoid TS2371
                // Kea should be fixed to avoid including the default value in the function signature
                if (forceRefresh === undefined) {
                    forceRefresh = false
                }

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
                const teamId = values.currentTeamId
                if (!teamId) {
                    throw new Error('Team ID not available')
                }

                const data = await api.create(`api/environments/${teamId}/llm_analytics/summarization/`, payload)

                return {
                    summary: data.summary,
                    text_repr: data.text_repr,
                }
            },
        },
    })),
    listeners(({ actions, values }) => ({
        loadCachedSummary: async () => {
            // Try to load cached summary - requires consent since we're hitting the summarization API
            // which will return cached data if available (forceRefresh: false)
            if (!values.dataProcessingAccepted) {
                return
            }

            const entityId = values.entityId
            if (!entityId) {
                return
            }

            // Use generateSummary with forceRefresh: false - backend returns cached data if available
            actions.generateSummary({ mode: values.summaryMode, forceRefresh: false })
        },
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
    afterMount(({ props, actions, values }) => {
        if (props.autoGenerate && values.dataProcessingAccepted) {
            // Auto-generate was requested (e.g., from URL param)
            actions.generateSummary({ mode: values.summaryMode, forceRefresh: false })
        } else if (values.dataProcessingAccepted) {
            // Try to load cached summary on mount (will use cache if available)
            actions.loadCachedSummary()
        }
    }),
])
