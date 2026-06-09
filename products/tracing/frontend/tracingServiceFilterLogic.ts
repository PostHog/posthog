import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { teamLogic } from 'scenes/teamLogic'

import { DateRange } from '~/queries/schema/schema-general'

import type { tracingServiceFilterLogicType } from './tracingServiceFilterLogicType'

export interface TracingServiceFilterLogicProps {
    dateRange?: DateRange
}

export const tracingServiceFilterLogic = kea<tracingServiceFilterLogicType>([
    path(['products', 'tracing', 'frontend', 'tracingServiceFilterLogic']),
    props({} as TracingServiceFilterLogicProps),
    key((props) => `${props.dateRange?.date_from ?? 'all'}_${props.dateRange?.date_to ?? 'all'}`),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        setSearch: (search: string) => ({ search }),
    }),

    reducers({
        search: ['' as string, { setSearch: (_, { search }) => search }],
    }),

    loaders(({ values, props: logicProps }) => ({
        allServiceNames: [
            [] as string[],
            {
                loadServiceNames: async () => {
                    try {
                        const response = await api.tracing.serviceNames({
                            search: values.search,
                            ...(logicProps.dateRange ? { dateRange: JSON.stringify(logicProps.dateRange) } : {}),
                        })
                        return (response.results ?? []).map((r: { name: string }) => r.name)
                    } catch (error) {
                        // The service filter is advisory — when the tracing backend is unavailable
                        // (e.g. the spans ClickHouse table isn't provisioned on this instance), the
                        // values endpoint 500s. Degrade gracefully to an empty list rather than
                        // letting kea-loaders surface the 500 as a handled exception on mount.
                        if (error instanceof ApiError && error.status && error.status >= 500) {
                            return []
                        }
                        throw error
                    }
                },
            },
        ],
    })),

    selectors({
        serviceNames: [
            (s) => [s.allServiceNames, s.search],
            (allServiceNames: string[], search: string): string[] => {
                if (!search) {
                    return allServiceNames
                }
                const lower = search.toLowerCase()
                return allServiceNames.filter((name) => name.toLowerCase().includes(lower))
            },
        ],
    }),

    listeners(({ actions }) => ({
        setSearch: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadServiceNames()
        },
    })),

    propsChanged(({ actions, props: newProps }, oldProps) => {
        if (
            newProps.dateRange?.date_from !== oldProps?.dateRange?.date_from ||
            newProps.dateRange?.date_to !== oldProps?.dateRange?.date_to
        ) {
            actions.loadServiceNames()
        }
    }),

    afterMount(({ actions }) => {
        actions.loadServiceNames()
    }),
])
