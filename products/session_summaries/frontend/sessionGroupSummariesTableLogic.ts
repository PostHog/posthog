import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { PaginationManual, Sorting } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { objectClean } from 'lib/utils'

import { Breadcrumb } from '~/types'

import type { sessionGroupSummariesTableLogicType } from './sessionGroupSummariesTableLogicType'
import { SessionGroupSummaryListItemType } from './types'

export interface SessionGroupSummariesListFilters {
    search: string
    createdBy: string | null
}

export const DEFAULT_FILTERS: SessionGroupSummariesListFilters = {
    search: '',
    createdBy: null,
}

const RESULTS_PER_PAGE = 50
const DEFAULT_SORTING: Sorting = { columnKey: '-created_at', order: 1 }

export const sessionGroupSummariesTableLogic = kea<sessionGroupSummariesTableLogicType>([
    path(['products', 'session_summaries', 'frontend', 'sessionGroupSummariesTableLogic']),
    connect({}),
    actions({
        loadSessionGroupSummaries: true, // Takes no parameters, load by default
        setFilters: (filters: Partial<SessionGroupSummariesListFilters>) => ({ filters }),
        tableSortingChanged: (sorting: Sorting | null) => ({
            sorting,
        }),
        setPage: (page: number) => ({ page }),
        deleteSessionGroupSummary: (id: string) => ({ id }),
    }),
    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) =>
                    objectClean({
                        ...state,
                        ...filters,
                    }),
            },
        ],
        page: [
            1,
            {
                setPage: (_, { page }) => page,
                setFilters: () => 1,
                tableSortingChanged: () => 1,
            },
        ],
        tableSorting: [
            DEFAULT_SORTING,
            { persist: true },
            {
                tableSortingChanged: (_, { sorting }) => sorting || DEFAULT_SORTING,
            },
        ],
    }),
    loaders(({ values }) => ({
        sessionGroupSummariesResponse: [
            null as CountedPaginatedResponse<SessionGroupSummaryListItemType> | null,
            {
                loadSessionGroupSummaries: async (_, breakpoint) => {
                    await breakpoint(100)
                    const createdByForQuery =
                        values.filters?.createdBy === DEFAULT_FILTERS.createdBy ? undefined : values.filters?.createdBy
                    const sortKey = values.tableSorting.columnKey || '-created_at'
                    const res = await api.sessionGroupSummaries.list({
                        created_by: createdByForQuery ?? undefined,
                        search: values.filters?.search || undefined,
                        order: sortKey,
                        limit: RESULTS_PER_PAGE,
                        offset: (values.page - 1) * RESULTS_PER_PAGE,
                    })
                    breakpoint()
                    return res
                },
                deleteSessionGroupSummary: async ({ id }) => {
                    await api.sessionGroupSummaries.delete(id)
                    return null
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        setFilters: () => actions.loadSessionGroupSummaries(),
        tableSortingChanged: () => actions.loadSessionGroupSummaries(),
        setPage: () => actions.loadSessionGroupSummaries(),
        deleteSessionGroupSummarySuccess: () => actions.loadSessionGroupSummaries(),
    })),
    selectors(({ actions }) => ({
        sessionGroupSummaries: [
            (s) => [s.sessionGroupSummariesResponse],
            (
                sessionGroupSummariesResponse: CountedPaginatedResponse<SessionGroupSummaryListItemType> | null
            ): SessionGroupSummaryListItemType[] => {
                return sessionGroupSummariesResponse?.results || []
            },
        ],
        pagination: [
            (s) => [s.page, s.sessionGroupSummariesResponse],
            (
                page: number,
                sessionGroupSummariesResponse: CountedPaginatedResponse<SessionGroupSummaryListItemType> | null
            ): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: RESULTS_PER_PAGE,
                    currentPage: page,
                    entryCount: sessionGroupSummariesResponse?.count ?? 0,
                    onBackward: () => actions.setPage(page - 1),
                    onForward: () => actions.setPage(page + 1),
                }
            },
        ],
    })),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'session-group-summaries',
                    name: 'Session summaries',
                    iconType: 'insight/hog',
                },
            ],
        ],
    }),
])
