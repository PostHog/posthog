import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { DataTableNode } from '~/queries/schema/schema-general'

import {
    ERROR_TRACKING_DEFAULT_DATE_RANGE,
    ERROR_TRACKING_DEFAULT_FILTER_GROUP,
    ERROR_TRACKING_DEFAULT_SEARCH_QUERY,
    ERROR_TRACKING_DEFAULT_TEST_ACCOUNT,
    errorFiltersLogic,
} from './components/ErrorFilters/errorFiltersLogic'
import { issueActionsLogic } from './components/IssueActions/issueActionsLogic'
import {
    ERROR_TRACKING_DEFAULT_ASSIGNEE,
    ERROR_TRACKING_DEFAULT_ORDER_BY,
    ERROR_TRACKING_DEFAULT_ORDER_DIRECTION,
    ERROR_TRACKING_DEFAULT_STATUS,
    issueQueryOptionsLogic,
} from './components/IssueQueryOptions/issueQueryOptionsLogic'
import type { errorTrackingSceneLogicType } from './errorTrackingSceneLogicType'
import { errorTrackingQuery } from './queries'
import { ERROR_TRACKING_LISTING_RESOLUTION, syncSearchParams, updateSearchParams } from './utils'
import { actionToUrl, router, urlToAction } from 'kea-router'
import equal from 'fast-deep-equal'
import { Params } from 'scenes/sceneTypes'

export const errorTrackingSceneLogic = kea<errorTrackingSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingSceneLogic']),

    connect(() => ({
        values: [
            errorFiltersLogic,
            ['dateRange', 'filterTestAccounts', 'filterGroup', 'searchQuery'],
            issueQueryOptionsLogic,
            ['assignee', 'orderBy', 'orderDirection', 'status'],
        ],
        actions: [
            issueActionsLogic,
            ['mutationSuccess', 'mutationFailure'],
            errorFiltersLogic,
            ['setDateRange', 'setFilterTestAccounts', 'setFilterGroup', 'setSearchQuery'],
            issueQueryOptionsLogic,
            ['setAssignee', 'setOrderBy', 'setOrderDirection', 'setStatus'],
        ],
    })),

    actions({
        setSelectedIssueIds: (ids: string[]) => ({ ids }),
        setShiftKeyHeld: (shiftKeyHeld: boolean) => ({ shiftKeyHeld }),
        setPreviouslyCheckedRecordIndex: (index: number) => ({ index }),
    }),

    reducers({
        selectedIssueIds: [
            [] as string[],
            {
                setSelectedIssueIds: (_, { ids }) => ids,
            },
        ],
        shiftKeyHeld: [
            false as boolean,
            {
                setShiftKeyHeld: (_, { shiftKeyHeld }) => shiftKeyHeld,
            },
        ],
        previouslyCheckedRecordIndex: [
            null as number | null,
            {
                setPreviouslyCheckedRecordIndex: (_, { index }) => index,
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
    }),

    subscriptions(({ actions }) => ({
        query: () => actions.setSelectedIssueIds([]),
    })),

    listeners(({ actions }) => ({
        mutationSuccess: () => actions.setSelectedIssueIds([]),
        mutationFailure: () => actions.setSelectedIssueIds([]),
    })),

    urlToAction(({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            const hasParams =
                !!params.orderBy ||
                !!params.orderDirection ||
                !!params.status ||
                !!params.assignee ||
                !!params.dateRange ||
                !!params.filterGroup ||
                !!params.filterTestAccounts ||
                !!params.searchQuery

            if (params.orderBy && !equal(params.orderBy, values.orderBy)) {
                actions.setOrderBy(params.orderBy)
            } else if (hasParams && !params.orderBy) {
                actions.setOrderBy(ERROR_TRACKING_DEFAULT_ORDER_BY)
            }
            if (params.status && !equal(params.status, values.status)) {
                actions.setStatus(params.status)
            } else if (hasParams && !params.status) {
                actions.setStatus(ERROR_TRACKING_DEFAULT_STATUS)
            }
            if (params.assignee && !equal(params.assignee, values.assignee)) {
                actions.setAssignee(params.assignee)
            } else if (hasParams && !params.assignee) {
                actions.setAssignee(ERROR_TRACKING_DEFAULT_ASSIGNEE)
            }
            if (params.orderDirection && !equal(params.orderDirection, values.orderDirection)) {
                actions.setOrderDirection(params.orderDirection)
            } else if (hasParams && !params.orderDirection) {
                actions.setOrderDirection(ERROR_TRACKING_DEFAULT_ORDER_DIRECTION)
            }
            if (params.dateRange && !equal(params.dateRange, values.dateRange)) {
                actions.setDateRange(params.dateRange)
            } else if (hasParams && !params.dateRange) {
                actions.setDateRange(ERROR_TRACKING_DEFAULT_DATE_RANGE)
            }
            if (params.filterGroup && !equal(params.filterGroup, values.filterGroup)) {
                actions.setFilterGroup(params.filterGroup)
            } else if (hasParams && !params.filterGroup) {
                actions.setFilterGroup(ERROR_TRACKING_DEFAULT_FILTER_GROUP)
            }
            if (params.filterTestAccounts && !equal(params.filterTestAccounts, values.filterTestAccounts)) {
                actions.setFilterTestAccounts(params.filterTestAccounts)
            } else if (hasParams && !params.filterTestAccounts) {
                actions.setFilterTestAccounts(ERROR_TRACKING_DEFAULT_TEST_ACCOUNT)
            }
            if (params.searchQuery && !equal(params.searchQuery, values.searchQuery)) {
                actions.setSearchQuery(params.searchQuery)
            } else if (hasParams && !params.searchQuery) {
                actions.setSearchQuery(ERROR_TRACKING_DEFAULT_SEARCH_QUERY)
            }
        }
        return {
            '*': urlToAction,
        }
    }),

    actionToUrl(({ values }) => {
        const buildURL = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            }
        ] => {
            return syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'assignee', values.assignee, ERROR_TRACKING_DEFAULT_ASSIGNEE)
                updateSearchParams(params, 'status', values.status, ERROR_TRACKING_DEFAULT_STATUS)
                updateSearchParams(params, 'orderBy', values.orderBy, ERROR_TRACKING_DEFAULT_ORDER_BY)
                updateSearchParams(
                    params,
                    'orderDirection',
                    values.orderDirection,
                    ERROR_TRACKING_DEFAULT_ORDER_DIRECTION
                )
                updateSearchParams(
                    params,
                    'filterTestAccounts',
                    values.filterTestAccounts,
                    ERROR_TRACKING_DEFAULT_TEST_ACCOUNT
                )
                updateSearchParams(params, 'searchQuery', values.searchQuery, ERROR_TRACKING_DEFAULT_SEARCH_QUERY)
                updateSearchParams(params, 'filterGroup', values.filterGroup, ERROR_TRACKING_DEFAULT_FILTER_GROUP)
                updateSearchParams(params, 'dateRange', values.dateRange, ERROR_TRACKING_DEFAULT_DATE_RANGE)
                return params
            })
        }

        return {
            setOrderBy: () => buildURL(),
            setStatus: () => buildURL(),
            setAssignee: () => buildURL(),
            setOrderDirection: () => buildURL(),
            setDateRange: () => buildURL(),
            setFilterGroup: () => buildURL(),
            setSearchQuery: () => buildURL(),
            setFilterTestAccounts: () => buildURL(),
        }
    }),

    afterMount(({ actions, cache }) => {
        const onKeyChange = (event: KeyboardEvent): void => {
            actions.setShiftKeyHeld(event.shiftKey)
        }

        // register shift key listener
        window.addEventListener('keydown', onKeyChange)
        window.addEventListener('keyup', onKeyChange)
        cache.onKeyChange = onKeyChange
    }),
    beforeUnmount(({ cache }) => {
        // unregister shift key listener
        window.removeEventListener('keydown', cache.onKeyChange)
        window.removeEventListener('keyup', cache.onKeyChange)
    }),
])
