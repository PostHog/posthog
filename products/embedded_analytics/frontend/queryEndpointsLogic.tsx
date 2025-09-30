import Fuse from 'fuse.js'
import { actions, afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { NamedQueryLastExecutionTimesRequest } from '~/queries/schema/schema-general'
import { QueryEndpointType } from '~/types'

import type { queryEndpointsLogicType } from './queryEndpointsLogicType'

export interface QueryEndpointsFilters {
    search: string
}

export const DEFAULT_FILTERS: QueryEndpointsFilters = {
    search: '',
}

export interface QueryEndpointsLogicProps {
    tabId: string
}

export const queryEndpointsLogic = kea<queryEndpointsLogicType>([
    path(['products', 'embedded_analytics', 'frontend', 'queryEndpointsLogic']),
    props({} as QueryEndpointsLogicProps),
    key((props) => props.tabId),
    actions({
        setFilters: (filters: Partial<QueryEndpointsFilters>) => ({ filters }),
    }),
    loaders(() => ({
        allQueryEndpoints: [
            [] as QueryEndpointType[],
            {
                loadQueryEndpoints: async () => {
                    const response = await api.queryEndpoint.list()
                    let haystack: QueryEndpointType[] = response.results || []

                    if (haystack.length > 0) {
                        const names: NamedQueryLastExecutionTimesRequest = {
                            names: haystack.map((endpoint) => endpoint.name),
                        }
                        const lastExecutionTimes = await api.queryEndpoint.getLastExecutionTimes(names)

                        haystack = haystack.map((endpoint) => ({
                            ...endpoint,
                            last_executed_at: lastExecutionTimes[endpoint.name],
                        }))
                    }

                    return haystack
                },
            },
        ],
    })),
    reducers({
        filters: [
            DEFAULT_FILTERS as QueryEndpointsFilters,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
    }),
    selectors({
        queryEndpoints: [
            (s) => [s.allQueryEndpoints, s.filters],
            (allQueryEndpoints, filters) => {
                if (!filters.search) {
                    return allQueryEndpoints
                }

                const fuse = new Fuse<QueryEndpointType>(allQueryEndpoints, {
                    keys: ['name', 'description', 'query.query'],
                    threshold: 0.3,
                })
                return fuse.search(filters.search).map((result) => result.item)
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadQueryEndpoints()
    }),
])
