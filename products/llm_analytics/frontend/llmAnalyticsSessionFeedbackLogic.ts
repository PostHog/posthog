import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'

import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import type { llmAnalyticsSessionFeedbackLogicType } from './llmAnalyticsSessionFeedbackLogicType'

export interface SessionFeedback {
    rating: string
    triggerType: string
    traceId: string | null
    timestamp: string
}

export interface SessionSupportTicket {
    ticketId: string
    traceId: string | null
    timestamp: string
}

export interface SessionFeedbackLogicProps {
    sessionId: string
}

export const llmAnalyticsSessionFeedbackLogic = kea<llmAnalyticsSessionFeedbackLogicType>([
    path(['scenes', 'llm-analytics', 'llmAnalyticsSessionFeedbackLogic']),
    props({} as SessionFeedbackLogicProps),
    key((props) => props.sessionId),

    actions({
        loadSessionFeedback: true,
        loadSessionFeedbackSuccess: (feedback: SessionFeedback[]) => ({ feedback }),
        loadSessionFeedbackFailure: true,
        loadSessionSupportTickets: true,
        loadSessionSupportTicketsSuccess: (tickets: SessionSupportTicket[]) => ({ tickets }),
        loadSessionSupportTicketsFailure: true,
    }),

    reducers({
        sessionFeedback: [
            [] as SessionFeedback[],
            {
                loadSessionFeedbackSuccess: (_, { feedback }) => feedback,
                loadSessionFeedbackFailure: () => [],
            },
        ],
        feedbackLoading: [
            false,
            {
                loadSessionFeedback: () => true,
                loadSessionFeedbackSuccess: () => false,
                loadSessionFeedbackFailure: () => false,
            },
        ],
        sessionSupportTickets: [
            [] as SessionSupportTicket[],
            {
                loadSessionSupportTicketsSuccess: (_, { tickets }) => tickets,
                loadSessionSupportTicketsFailure: () => [],
            },
        ],
        supportTicketsLoading: [
            false,
            {
                loadSessionSupportTickets: () => true,
                loadSessionSupportTicketsSuccess: () => false,
                loadSessionSupportTicketsFailure: () => false,
            },
        ],
    }),

    listeners(({ actions, props }) => ({
        loadSessionFeedback: async () => {
            const { sessionId } = props
            if (!sessionId) {
                actions.loadSessionFeedbackFailure()
                return
            }

            const feedbackQuery: HogQLQuery = {
                kind: NodeKind.HogQLQuery,
                query: `
                    SELECT
                        properties.$ai_metric_value as rating,
                        properties.feedback_trigger_type as trigger_type,
                        properties.$ai_trace_id as trace_id,
                        timestamp
                    FROM events
                    WHERE event = '$ai_metric'
                      AND properties.$ai_metric_name = 'feedback'
                      AND properties.$ai_session_id = {sessionId}
                    ORDER BY timestamp DESC
                `,
                values: { sessionId },
            }

            try {
                const response = await api.query(feedbackQuery)
                const feedback: SessionFeedback[] = (response.results || []).map((row: any[]) => ({
                    rating: row[0] || '',
                    triggerType: row[1] || '',
                    traceId: row[2] || null,
                    timestamp: row[3] || '',
                }))
                actions.loadSessionFeedbackSuccess(feedback)
            } catch (error) {
                console.error('Error loading session feedback:', error)
                actions.loadSessionFeedbackFailure()
            }
        },

        loadSessionSupportTickets: async () => {
            const { sessionId } = props
            if (!sessionId) {
                actions.loadSessionSupportTicketsFailure()
                return
            }

            const ticketsQuery: HogQLQuery = {
                kind: NodeKind.HogQLQuery,
                query: `
                    SELECT
                        properties.$ai_support_ticket_id as ticket_id,
                        properties.$ai_trace_id as trace_id,
                        timestamp
                    FROM events
                    WHERE event = 'posthog_ai_support_ticket_created'
                      AND properties.$ai_conversation_id = {sessionId}
                    ORDER BY timestamp DESC
                `,
                values: { sessionId },
            }

            try {
                const response = await api.query(ticketsQuery)
                const tickets: SessionSupportTicket[] = (response.results || []).map((row: any[]) => ({
                    ticketId: row[0] || '',
                    traceId: row[1] || null,
                    timestamp: row[2] || '',
                }))
                actions.loadSessionSupportTicketsSuccess(tickets)
            } catch (error) {
                console.error('Error loading session support tickets:', error)
                actions.loadSessionSupportTicketsFailure()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadSessionFeedback()
        actions.loadSessionSupportTickets()
    }),
])
