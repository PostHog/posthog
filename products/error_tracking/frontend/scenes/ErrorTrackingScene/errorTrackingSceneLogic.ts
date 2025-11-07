import equal from 'fast-deep-equal'
import { actions, connect, events, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { Params } from 'scenes/sceneTypes'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { DataTableNode } from '~/queries/schema/schema-general'
import { ActivityScope, Breadcrumb, PropertyFilterType } from '~/types'

import { issueActionsLogic } from '../../components/IssueActions/issueActionsLogic'
import { issueFiltersLogic } from '../../components/IssueFilters/issueFiltersLogic'
import { issueQueryOptionsLogic } from '../../components/IssueQueryOptions/issueQueryOptionsLogic'
import { bulkSelectLogic } from '../../logics/bulkSelectLogic'
import { errorTrackingQuery } from '../../queries'
import { ERROR_TRACKING_LISTING_RESOLUTION, syncSearchParams, updateSearchParams } from '../../utils'
import type { errorTrackingSceneLogicType } from './errorTrackingSceneLogicType'

export const ERROR_TRACKING_SCENE_LOGIC_KEY = 'ErrorTrackingScene'

const DEFAULT_ACTIVE_TAB = 'issues'

export type ErrorTrackingSceneActiveTab = 'issues' | 'impact'

export const errorTrackingSceneLogic = kea<errorTrackingSceneLogicType>([
    path(['products', 'error_tracking', 'scenes', 'ErrorTrackingScene', 'errorTrackingSceneLogic']),

    actions({
        setActiveTab: (activeTab: ErrorTrackingSceneActiveTab) => ({ activeTab }),
    }),

    connect(() => ({
        values: [
            issueFiltersLogic({ logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY }),
            ['dateRange', 'filterTestAccounts', 'filterGroup', 'searchQuery'],
            issueQueryOptionsLogic({ logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY }),
            ['assignee', 'orderBy', 'orderDirection', 'status'],
        ],
        actions: [issueActionsLogic, ['mutationSuccess', 'mutationFailure'], bulkSelectLogic, ['setSelectedIssueIds']],
    })),

    reducers({
        activeTab: [
            DEFAULT_ACTIVE_TAB as ErrorTrackingSceneActiveTab,
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
            ): DataTableNode => {
                const columns =
                    orderBy === 'revenue'
                        ? ['error', 'volume', 'occurrences', 'sessions', 'users', 'revenue']
                        : ['error', 'volume', 'occurrences', 'sessions', 'users']

                return errorTrackingQuery({
                    orderBy,
                    status,
                    dateRange,
                    assignee,
                    filterTestAccounts,
                    filterGroup,
                    volumeResolution: ERROR_TRACKING_LISTING_RESOLUTION,
                    searchQuery,
                    columns,
                    orderDirection,
                })
            },
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
                discussions_disabled: true,
            }),
        ],
    }),

    subscriptions(({ actions, values }) => ({
        query: (query, oldQuery) => {
            // Clear selected issues when query changes
            actions.setSelectedIssueIds([])

            // Don't fire analytics if query hasn't actually changed
            if (equal(query, oldQuery)) {
                return
            }

            // Calculate filter properties
            const filterGroup = values.filterGroup
            const hasFilters =
                filterGroup.values.length > 0 &&
                filterGroup.values.some(
                    (groupValue) =>
                        'values' in groupValue && Array.isArray(groupValue.values) && groupValue.values.length > 0
                )
            const filterCount = filterGroup.values.reduce((count, groupValue) => {
                if ('values' in groupValue && Array.isArray(groupValue.values)) {
                    return count + groupValue.values.length
                }
                return count
            }, 0)

            // Analyze filter categories used
            const filterCategories: string[] = []
            filterGroup.values.forEach((groupValue) => {
                if ('values' in groupValue && Array.isArray(groupValue.values)) {
                    groupValue.values.forEach((filterValue) => {
                        if ('type' in filterValue && typeof filterValue.type === 'string') {
                            const type = filterValue.type as PropertyFilterType
                            if (type === PropertyFilterType.Person && !filterCategories.includes('person_properties')) {
                                filterCategories.push('person_properties')
                            } else if (
                                type === PropertyFilterType.Event &&
                                !filterCategories.includes('event_properties')
                            ) {
                                filterCategories.push('event_properties')
                            } else if (
                                type === PropertyFilterType.ErrorTrackingIssue &&
                                !filterCategories.includes('error_tracking_issues')
                            ) {
                                filterCategories.push('error_tracking_issues')
                            } else if (type === PropertyFilterType.Cohort && !filterCategories.includes('cohorts')) {
                                filterCategories.push('cohorts')
                            } else if (
                                type === PropertyFilterType.HogQL &&
                                !filterCategories.includes('sql_expression')
                            ) {
                                filterCategories.push('sql_expression')
                            }
                        }
                    })
                }
            })

            posthog.capture('error_tracking_query_executed', {
                has_filters: hasFilters,
                filter_count: filterCount,
                filter_categories_used: filterCategories,
                has_search_query: !!values.searchQuery,
                filter_test_accounts: values.filterTestAccounts,
                sort_by: values.orderBy,
                sort_direction: values.orderDirection,
            })
        },
    })),

    actionToUrl(({ values }) => {
        const buildURL = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            return syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'activeTab', values.activeTab, DEFAULT_ACTIVE_TAB)
                return params
            })
        }

        return {
            setActiveTab: () => buildURL(),
        }
    }),

    urlToAction(({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            if (params.activeTab && !equal(params.activeTab, values.activeTab)) {
                actions.setActiveTab(params.activeTab)
            }
        }
        return {
            '*': urlToAction,
        }
    }),

    events(({ values }) => ({
        afterMount: () => {
            // Calculate filter properties
            const filterGroup = values.filterGroup
            const hasFilters =
                filterGroup.values.length > 0 &&
                filterGroup.values.some((group) => group.values && group.values.length > 0)
            const filterCount = filterGroup.values.reduce((count, group) => count + (group.values?.length || 0), 0)

            // Calculate date range in days
            const dateRange = values.dateRange.date_from || '-7d'
            const dateRangeDays = dateRange.startsWith('-') ? parseInt(dateRange.slice(1, -1)) : null

            posthog.capture('error_tracking_issues_list_viewed', {
                has_filters: hasFilters,
                filter_count: filterCount,
                has_search_query: !!values.searchQuery,
                filter_test_accounts: values.filterTestAccounts,
                sort_by: values.orderBy,
                sort_direction: values.orderDirection,
                date_range_days: dateRangeDays,
                active_tab: values.activeTab,
            })
        },
    })),
])
