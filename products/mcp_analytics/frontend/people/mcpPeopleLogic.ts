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
import { type PersonRow, peopleQuery, toPersonRows } from './peopleQueries'

export const PEOPLE_DEFAULT_DATE_FILTER: DateFilter = { dateFrom: '-7d', dateTo: null }

/** The People tab: identified callers of the server, with one opened in a drawer. */
export const mcpPeopleLogic = kea([
    path(['products', 'mcp_analytics', 'frontend', 'people', 'mcpPeopleLogic']),
    connect(() => ({
        values: [mcpAnalyticsFiltersLogic, ['queryFilters as sharedQueryFilters']],
    })),
    actions({
        setDateFilter: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setSearch: (search: string) => ({ search }),
        openPerson: (distinctId: string | null) => ({ distinctId }),
    }),
    reducers({
        dateFilter: [
            PEOPLE_DEFAULT_DATE_FILTER as DateFilter,
            { setDateFilter: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }) },
        ],
        search: ['', { setSearch: (_, { search }) => search }],
        openedPerson: [null as string | null, { openPerson: (_, { distinctId }) => distinctId }],
    }),
    loaders(({ values }) => ({
        people: [
            [] as PersonRow[],
            {
                loadPeople: async (_: void, breakpoint) => {
                    const response = await api.query(
                        peopleQuery(
                            { date_from: values.dateFilter.dateFrom, date_to: values.dateFilter.dateTo },
                            values.sharedQueryFilters as MCPSharedQueryFilters
                        )
                    )
                    breakpoint()
                    return toPersonRows(response.results)
                },
            },
        ],
    })),
    reducers({
        peopleFailed: [false, { loadPeople: () => false, loadPeopleFailure: () => true }],
    }),
    selectors({
        filteredPeople: [
            (s) => [s.people, s.search],
            (people: PersonRow[], search: string): PersonRow[] => {
                const term = search.trim().toLowerCase()
                return term
                    ? people.filter(
                          (person) =>
                              person.label.toLowerCase().includes(term) ||
                              person.distinctId.toLowerCase().includes(term)
                      )
                    : people
            },
        ],
        openedPosition: [
            (s) => [s.filteredPeople, s.openedPerson],
            (people: PersonRow[], openedPerson: string | null): MCPDetailDrawerPosition | null => {
                const index = people.findIndex((person) => person.distinctId === openedPerson)
                return index >= 0 ? { index, total: people.length } : null
            },
        ],
        previousPerson: [
            (s) => [s.filteredPeople, s.openedPosition],
            (people: PersonRow[], position: MCPDetailDrawerPosition | null): string | null =>
                position && position.index > 0 ? people[position.index - 1].distinctId : null,
        ],
        nextPerson: [
            (s) => [s.filteredPeople, s.openedPosition],
            (people: PersonRow[], position: MCPDetailDrawerPosition | null): string | null =>
                position && position.index < people.length - 1 ? people[position.index + 1].distinctId : null,
        ],
    }),
    listeners(({ actions }) => ({
        setDateFilter: () => actions.loadPeople(),
        openPerson: ({ distinctId }) => {
            if (distinctId) {
                posthog.capture('mcp analytics drawer opened', { list: 'people' })
            }
        },
    })),
    subscriptions(({ actions }) => ({
        sharedQueryFilters: (_: MCPSharedQueryFilters, previous: MCPSharedQueryFilters | undefined) => {
            if (previous) {
                actions.loadPeople()
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
        [urls.mcpAnalyticsPeople()]: (_, searchParams) => {
            const dateFrom = typeof searchParams.date_from === 'string' ? searchParams.date_from : '-7d'
            const dateTo = typeof searchParams.date_to === 'string' ? searchParams.date_to : null
            if (dateFrom !== values.dateFilter.dateFrom || dateTo !== values.dateFilter.dateTo) {
                actions.setDateFilter(dateFrom, dateTo)
            }
        },
    })),
    afterMount(({ actions }) => actions.loadPeople()),
])
