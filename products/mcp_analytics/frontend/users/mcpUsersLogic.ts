import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import posthog from 'lib/posthog-typed'
import { urls } from 'scenes/urls'

import type { MCPDetailDrawerPosition } from '../components/MCPDetailDrawer'
import { type MCPSharedQueryFilters, mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import type { DateFilter } from '../mcpAnalyticsToolQualityLogic'
import { type UserRow, usersQuery, toUserRows } from './usersQueries'

export const USERS_DEFAULT_DATE_FILTER: DateFilter = { dateFrom: '-7d', dateTo: null }

/** The Users tab: identified callers of the server, with one opened in a drawer. */
export const mcpUsersLogic = kea([
    path(['products', 'mcp_analytics', 'frontend', 'users', 'mcpUsersLogic']),
    connect(() => ({
        values: [mcpAnalyticsFiltersLogic, ['queryFilters as sharedQueryFilters']],
    })),
    actions({
        setDateFilter: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setSearch: (search: string) => ({ search }),
        openUser: (distinctId: string | null) => ({ distinctId }),
    }),
    reducers({
        dateFilter: [
            USERS_DEFAULT_DATE_FILTER as DateFilter,
            { setDateFilter: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }) },
        ],
        search: ['', { setSearch: (_, { search }) => search }],
        openedUser: [null as string | null, { openUser: (_, { distinctId }) => distinctId }],
    }),
    loaders(({ values }) => ({
        users: [
            [] as UserRow[],
            {
                loadUsers: async (_: void, breakpoint) => {
                    const response = await api.query(
                        usersQuery(
                            { date_from: values.dateFilter.dateFrom, date_to: values.dateFilter.dateTo },
                            values.sharedQueryFilters as MCPSharedQueryFilters
                        )
                    )
                    breakpoint()
                    return toUserRows(response.results)
                },
            },
        ],
    })),
    reducers({
        usersFailed: [false, { loadUsers: () => false, loadUsersFailure: () => true }],
    }),
    selectors({
        filteredUsers: [
            (s) => [s.users, s.search],
            (users: UserRow[], search: string): UserRow[] => {
                const term = search.trim().toLowerCase()
                return term
                    ? users.filter(
                          (user) =>
                              user.label.toLowerCase().includes(term) || user.distinctId.toLowerCase().includes(term)
                      )
                    : users
            },
        ],
        openedPosition: [
            (s) => [s.filteredUsers, s.openedUser],
            (users: UserRow[], openedUser: string | null): MCPDetailDrawerPosition | null => {
                const index = users.findIndex((user) => user.distinctId === openedUser)
                return index >= 0 ? { index, total: users.length } : null
            },
        ],
        previousUser: [
            (s) => [s.filteredUsers, s.openedPosition],
            (users: UserRow[], position: MCPDetailDrawerPosition | null): string | null =>
                position && position.index > 0 ? users[position.index - 1].distinctId : null,
        ],
        nextUser: [
            (s) => [s.filteredUsers, s.openedPosition],
            (users: UserRow[], position: MCPDetailDrawerPosition | null): string | null =>
                position && position.index < users.length - 1 ? users[position.index + 1].distinctId : null,
        ],
    }),
    listeners(({ actions }) => ({
        setDateFilter: () => actions.loadUsers(),
        openUser: ({ distinctId }) => {
            if (distinctId) {
                posthog.capture('mcp analytics drawer opened', { list: 'users' })
            }
        },
    })),
    subscriptions(({ actions }) => ({
        sharedQueryFilters: (_: MCPSharedQueryFilters, previous: MCPSharedQueryFilters | undefined) => {
            if (previous) {
                actions.loadUsers()
            }
        },
    })),
    actionToUrl(({ values }) => ({
        setDateFilter: () => {
            const { currentLocation } = router.values
            const searchParams = { ...currentLocation.searchParams }
            for (const [key, value] of Object.entries({
                date_from: values.dateFilter.dateFrom,
                date_to: values.dateFilter.dateTo,
            })) {
                if (value) {
                    searchParams[key] = value
                } else {
                    delete searchParams[key]
                }
            }
            return [currentLocation.pathname, searchParams, currentLocation.hashParams, { replace: true }]
        },
    })),
    urlToAction(({ actions, values }) => ({
        [urls.mcpAnalyticsUsers()]: (_, searchParams) => {
            const dateFrom = typeof searchParams.date_from === 'string' ? searchParams.date_from : '-7d'
            const dateTo = typeof searchParams.date_to === 'string' ? searchParams.date_to : null
            if (dateFrom !== values.dateFilter.dateFrom || dateTo !== values.dateFilter.dateTo) {
                actions.setDateFilter(dateFrom, dateTo)
            }
        },
    })),
    afterMount(({ actions }) => actions.loadUsers()),
])
