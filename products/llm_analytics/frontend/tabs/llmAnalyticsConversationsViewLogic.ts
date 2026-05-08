import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { teamLogic } from 'scenes/teamLogic'

import { llmAnalyticsConversationsList } from '../generated/api'
import { ConversationListItemApi } from '../generated/api.schemas'
import { llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import type { llmAnalyticsConversationsViewLogicType } from './llmAnalyticsConversationsViewLogicType'

export interface LLMAnalyticsConversationsViewLogicProps {
    tabId?: string
}

// Re-export the generated type so scene + table column code has a stable import path.
// Single line of indirection — if drf-spectacular ever drops the `Api` suffix or splits
// the type, this is the only place we touch.
export type ConversationListItem = ConversationListItemApi

export const llmAnalyticsConversationsViewLogic = kea<llmAnalyticsConversationsViewLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'tabs', 'llmAnalyticsConversationsViewLogic']),
    key((props: LLMAnalyticsConversationsViewLogicProps) => props.tabId || 'default'),
    props({} as LLMAnalyticsConversationsViewLogicProps),
    connect((props: LLMAnalyticsConversationsViewLogicProps) => ({
        values: [
            llmAnalyticsSharedLogic({ tabId: props.tabId }),
            ['dateFilter', 'shouldFilterTestAccounts', 'propertyFilters'],
            teamLogic,
            ['currentTeamId'],
        ],
    })),

    actions({
        setIncludeOrphanTraces: (includeOrphanTraces: boolean) => ({ includeOrphanTraces }),
        loadConversations: true,
        loadConversationsSuccess: (results: ConversationListItem[]) => ({ results }),
        loadConversationsFailure: (error: string) => ({ error }),
    }),

    reducers({
        includeOrphanTraces: [
            false,
            {
                setIncludeOrphanTraces: (_, { includeOrphanTraces }) => includeOrphanTraces,
            },
        ],
        conversations: [
            [] as ConversationListItem[],
            {
                loadConversationsSuccess: (_, { results }) => results,
            },
        ],
        conversationsLoading: [
            // Initialize true so the empty-state UI doesn't flash on the first render
            // (between the initial paint and `afterMount` dispatching `loadConversations`).
            // Matches `llmAnalyticsConversationDataLogic.loading`.
            true,
            {
                loadConversations: () => true,
                loadConversationsSuccess: () => false,
                loadConversationsFailure: () => false,
            },
        ],
        conversationsError: [
            null as string | null,
            {
                loadConversations: () => null,
                loadConversationsFailure: (_, { error }) => error,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        loadConversations: async () => {
            const teamId = values.currentTeamId
            if (!teamId) {
                actions.loadConversationsFailure('No team id')
                return
            }
            try {
                // `properties` is a JSON-encoded array; the generated client
                // serializes params via .toString(), so we encode it ourselves.
                const propertiesParam =
                    values.propertyFilters && values.propertyFilters.length > 0
                        ? JSON.stringify(values.propertyFilters)
                        : undefined
                const response = await llmAnalyticsConversationsList(String(teamId), {
                    date_from: values.dateFilter.dateFrom || undefined,
                    date_to: values.dateFilter.dateTo || undefined,
                    filter_test_accounts: values.shouldFilterTestAccounts || undefined,
                    include_orphan_traces: values.includeOrphanTraces || undefined,
                    properties: propertiesParam,
                })
                actions.loadConversationsSuccess(response.results || [])
            } catch (error) {
                console.error('Failed to load conversations', error)
                actions.loadConversationsFailure(error instanceof Error ? error.message : 'Unknown error')
            }
        },
        setIncludeOrphanTraces: () => actions.loadConversations(),
    })),

    subscriptions(({ actions }) => ({
        // Reload whenever a shared filter changes (date range, test-account toggle, properties).
        dateFilter: () => actions.loadConversations(),
        shouldFilterTestAccounts: () => actions.loadConversations(),
        propertyFilters: () => actions.loadConversations(),
    })),

    afterMount(({ actions }) => {
        actions.loadConversations()
    }),
])
