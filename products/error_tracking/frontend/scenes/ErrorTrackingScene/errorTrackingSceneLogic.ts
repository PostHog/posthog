import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { DataTableNode } from '~/queries/schema/schema-general'
import { ActivityScope, Breadcrumb } from '~/types'

import { issueActionsLogic } from '../../components/IssueActions/issueActionsLogic'
import { issueFiltersLogic } from '../../components/IssueFilters/issueFiltersLogic'
import { issueQueryOptionsLogic } from '../../components/IssueQueryOptions/issueQueryOptionsLogic'
import { bulkSelectLogic } from '../../logics/bulkSelectLogic'
import { errorTrackingQuery } from '../../queries'
import { ERROR_TRACKING_LISTING_RESOLUTION } from '../../utils'
import type { errorTrackingSceneLogicType } from './errorTrackingSceneLogicType'

export const errorTrackingSceneLogic = kea<errorTrackingSceneLogicType>([
    path(['products', 'error_tracking', 'scenes', 'ErrorTrackingScene', 'errorTrackingSceneLogic']),

    actions({
        setActiveTab: (activeTab: string) => ({ activeTab }),
    }),

    connect(() => ({
        values: [
            issueFiltersLogic,
            ['dateRange', 'filterTestAccounts', 'filterGroup', 'searchQuery'],
            issueQueryOptionsLogic,
            ['assignee', 'orderBy', 'orderDirection', 'status'],
        ],
        actions: [issueActionsLogic, ['mutationSuccess', 'mutationFailure'], bulkSelectLogic, ['setSelectedIssueIds']],
    })),

    reducers({
        activeTab: [
            'issues',
            {
                setActiveTab: (_, { activeTab }) => activeTab,
            },
        ],
    }),

    selectors({
        query: [
            (s) => [
                s.orderBy,
                s.status,
                s.dateRange,
                s.assignee,
                s.filterTestAccounts,
                s.filterGroup,
                s.searchQuery,
                s.orderDirection,
            ],
            (
                orderBy,
                status,
                dateRange,
                assignee,
                filterTestAccounts,
                filterGroup,
                searchQuery,
                orderDirection
            ): DataTableNode =>
                errorTrackingQuery({
                    orderBy,
                    status,
                    dateRange,
                    assignee,
                    filterTestAccounts,
                    filterGroup,
                    volumeResolution: ERROR_TRACKING_LISTING_RESOLUTION,
                    searchQuery,
                    columns: ['error', 'volume', 'occurrences', 'sessions', 'users'],
                    orderDirection,
                }),
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'error-tracking',
                    name: 'Error tracking',
                    iconType: 'error_tracking',
                },
            ],
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({
                activity_scope: ActivityScope.ERROR_TRACKING_ISSUE,
            }),
        ],
    }),

    subscriptions(({ actions }) => ({
        query: () => actions.setSelectedIssueIds([]),
    })),
])
