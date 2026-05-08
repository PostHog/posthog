import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { LLMTrace, NodeKind, TraceQuery } from '~/queries/schema/schema-general'

import { llmAnalyticsConversationsRetrieve } from './generated/api'
import { ConversationDetailResponseApi, ConversationTurnApi } from './generated/api.schemas'
import type { llmAnalyticsConversationDataLogicType } from './llmAnalyticsConversationDataLogicType'
import { ConversationKind, llmAnalyticsConversationLogic } from './llmAnalyticsConversationLogic'

const DEFAULT_DETAIL_DATE_FROM = '-30d'

export interface ConversationDataLogicProps {
    kind: ConversationKind
    id: string
    tabId?: string
}

// Re-export the generated types so the scene + helpers have a stable import path.
// `user_messages` / `assistant_messages` come back as `unknown[]` (from the
// `JSONField()` declarations on the serializer); the scene's `normalizeMessages`
// helper does the runtime narrowing.
export type ConversationTurn = ConversationTurnApi
export type ConversationDetail = ConversationDetailResponseApi

export const llmAnalyticsConversationDataLogic = kea<llmAnalyticsConversationDataLogicType>([
    path(['scenes', 'llm-analytics', 'llmAnalyticsConversationDataLogic']),
    props({} as ConversationDataLogicProps),
    key((props) => `${props.kind}:${props.id}:${props.tabId ?? 'default'}`),
    connect((props: ConversationDataLogicProps) => ({
        values: [teamLogic, ['currentTeamId'], llmAnalyticsConversationLogic({ tabId: props.tabId }), ['dateRange']],
    })),

    actions({
        loadConversation: true,
        loadConversationSuccess: (detail: ConversationDetail) => ({ detail }),
        loadConversationFailure: (error: string) => ({ error }),
        loadFullTrace: (traceId: string) => ({ traceId }),
        loadFullTraceSuccess: (traceId: string, trace: LLMTrace) => ({ traceId, trace }),
        loadFullTraceFailure: (traceId: string) => ({ traceId }),
        toggleReasoning: (traceId: string) => ({ traceId }),
        toggleEventExpand: (traceId: string, eventId: string) => ({ traceId, eventId }),
    }),

    reducers({
        detail: [
            null as ConversationDetail | null,
            {
                loadConversationSuccess: (_, { detail }) => detail,
            },
        ],
        loading: [
            true,
            {
                loadConversation: () => true,
                loadConversationSuccess: () => false,
                loadConversationFailure: () => false,
            },
        ],
        error: [
            null as string | null,
            {
                loadConversation: () => null,
                loadConversationFailure: (_, { error }) => error,
            },
        ],
        fullTraces: [
            {} as Record<string, LLMTrace>,
            {
                loadFullTraceSuccess: (state, { traceId, trace }) => ({
                    ...state,
                    [traceId]: trace,
                }),
            },
        ],
        loadingFullTraces: [
            new Set<string>() as Set<string>,
            {
                loadFullTrace: (state, { traceId }) => new Set(state).add(traceId),
                loadFullTraceSuccess: (state, { traceId }) => {
                    const next = new Set(state)
                    next.delete(traceId)
                    return next
                },
                loadFullTraceFailure: (state, { traceId }) => {
                    const next = new Set(state)
                    next.delete(traceId)
                    return next
                },
            },
        ],
        expandedReasoningTraceIds: [
            new Set<string>() as Set<string>,
            {
                toggleReasoning: (state, { traceId }) => {
                    const next = new Set(state)
                    if (next.has(traceId)) {
                        next.delete(traceId)
                    } else {
                        next.add(traceId)
                    }
                    return next
                },
            },
        ],
        expandedEventIds: [
            new Set<string>() as Set<string>,
            {
                toggleEventExpand: (state, { eventId }) => {
                    const next = new Set(state)
                    if (next.has(eventId)) {
                        next.delete(eventId)
                    } else {
                        next.add(eventId)
                    }
                    return next
                },
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        loadConversation: async () => {
            const teamId = values.currentTeamId
            if (!teamId) {
                actions.loadConversationFailure('No team id')
                return
            }
            try {
                const response = await llmAnalyticsConversationsRetrieve(String(teamId), props.id, {
                    kind: props.kind,
                    date_from: values.dateRange?.dateFrom || DEFAULT_DETAIL_DATE_FROM,
                    date_to: values.dateRange?.dateTo || undefined,
                })
                actions.loadConversationSuccess(response)
            } catch (error) {
                actions.loadConversationFailure(error instanceof Error ? error.message : 'Failed to load conversation')
            }
        },
        toggleReasoning: async ({ traceId }) => {
            // Lazy-load the full trace tree the first time the user opens reasoning
            // for a given trace. The conversation endpoint only returns flattened
            // user/assistant messages; the full event tree still comes from
            // TraceQuery (same shape the existing trace scene uses).
            if (
                values.expandedReasoningTraceIds.has(traceId) &&
                !values.fullTraces[traceId] &&
                !values.loadingFullTraces.has(traceId)
            ) {
                actions.loadFullTrace(traceId)
            }
        },
        loadFullTrace: async ({ traceId }) => {
            try {
                const traceQuery: TraceQuery = {
                    kind: NodeKind.TraceQuery,
                    traceId,
                }
                const response = await api.query(traceQuery)
                if (response.results && response.results[0]) {
                    actions.loadFullTraceSuccess(traceId, response.results[0] as LLMTrace)
                } else {
                    actions.loadFullTraceFailure(traceId)
                }
            } catch {
                actions.loadFullTraceFailure(traceId)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadConversation()
    }),
])
