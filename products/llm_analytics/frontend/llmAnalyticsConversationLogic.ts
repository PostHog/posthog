import { actions, kea, key, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { llmAnalyticsConversationLogicType } from './llmAnalyticsConversationLogicType'

export type ConversationKind = 'session' | 'trace'

export interface ConversationRef {
    kind: ConversationKind
    id: string
}

export interface LLMAnalyticsConversationLogicProps {
    tabId?: string
}

function isConversationKind(value: unknown): value is ConversationKind {
    return value === 'session' || value === 'trace'
}

export const llmAnalyticsConversationLogic = kea<llmAnalyticsConversationLogicType>([
    path(['scenes', 'llm-analytics', 'llmAnalyticsConversationLogic']),
    props({} as LLMAnalyticsConversationLogicProps),
    key((props) => props.tabId ?? 'default'),

    actions({
        setConversationRef: (ref: ConversationRef) => ({ ref }),
        setDateRange: (dateFrom: string | null, dateTo?: string | null) => ({ dateFrom, dateTo }),
    }),

    reducers({
        conversationRef: [
            null as ConversationRef | null,
            {
                setConversationRef: (_, { ref }) => ref,
            },
        ],
        dateRange: [
            null as { dateFrom: string | null; dateTo: string | null } | null,
            {
                setDateRange: (_, { dateFrom, dateTo }) => ({
                    dateFrom: dateFrom ?? null,
                    dateTo: dateTo ?? null,
                }),
            },
        ],
    }),

    selectors({
        breadcrumbs: [
            (s) => [s.conversationRef],
            (ref: ConversationRef | null): Breadcrumb[] => {
                const conversationsUrl = urls.llmAnalyticsConversations()
                const searchParams = router.values.searchParams
                const conversationsPath =
                    Object.keys(searchParams).length > 0
                        ? `${conversationsUrl}?${new URLSearchParams(searchParams).toString()}`
                        : conversationsUrl
                return [
                    {
                        key: 'LLMAnalytics',
                        name: 'LLM analytics',
                        path: urls.llmAnalyticsDashboard(),
                        iconType: 'llm_analytics',
                    },
                    {
                        key: 'LLMAnalyticsConversations',
                        name: 'Conversations',
                        path: conversationsPath,
                        iconType: 'llm_analytics',
                    },
                    {
                        key: ['LLMAnalyticsConversation', ref?.id ?? ''],
                        name: ref?.id ?? 'Conversation',
                        iconType: 'llm_analytics',
                    },
                ]
            },
        ],
    }),

    tabAwareUrlToAction(({ actions, values }) => ({
        '/llm-analytics/conversations/:kind/:id': ({ kind, id }, { date_from, date_to }) => {
            if (!isConversationKind(kind) || !id) {
                return
            }
            actions.setConversationRef({ kind, id })
            if (date_from || date_to) {
                actions.setDateRange((date_from as string) || null, (date_to as string) || null)
            } else if (values.dateRange?.dateFrom) {
                actions.setDateRange(values.dateRange.dateFrom, values.dateRange.dateTo || null)
            }
        },
    })),
])
