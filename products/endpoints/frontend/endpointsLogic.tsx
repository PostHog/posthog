import Fuse from 'fuse.js'
import { actions, afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { urls } from 'scenes/urls'

import { EndpointLastExecutionTimesRequest } from '~/queries/schema/schema-general'
import { EndpointType } from '~/types'

import type { endpointsLogicType } from './endpointsLogicType'

export type EndpointsTab = 'endpoints' | 'usage'

export interface EndpointsFilters {
    search: string
}

export const DEFAULT_FILTERS: EndpointsFilters = {
    search: '',
}

export interface EndpointsLogicProps {
    tabId: string
}

export const endpointsLogic = kea<endpointsLogicType>([
    path(['products', 'endpoints', 'frontend', 'endpointsLogic']),
    props({} as EndpointsLogicProps),
    key((props) => props.tabId),
    actions({
        setFilters: (filters: Partial<EndpointsFilters>) => ({ filters }),
        setActiveTab: (activeTab: EndpointsTab) => ({ activeTab }),
    }),
    loaders(() => ({
        allEndpoints: [
            [] as EndpointType[],
            {
                loadEndpoints: async () => {
                    const response = await api.endpoint.list()
                    let haystack: EndpointType[] = response.results || []

                    if (haystack.length > 0) {
                        const names: EndpointLastExecutionTimesRequest = {
                            names: haystack.map((endpoint) => endpoint.name),
                        }
                        const lastExecutionTimes = await api.endpoint.getLastExecutionTimes(names)

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
            DEFAULT_FILTERS as EndpointsFilters,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        activeTab: [
            'endpoints' as EndpointsTab,
            {
                setActiveTab: (_, { activeTab }) => activeTab,
            },
        ],
    }),
    selectors({
        endpoints: [
            (s) => [s.allEndpoints, s.filters],
            (allEndpoints, filters) => {
                if (!filters.search) {
                    return allEndpoints
                }

                const fuse = new Fuse<EndpointType>(allEndpoints, {
                    keys: ['name', 'description', 'query.query'],
                    threshold: 0.3,
                })
                return fuse.search(filters.search).map((result) => result.item)
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadEndpoints()
    }),

    tabAwareUrlToAction(({ actions }) => ({
        [urls.endpoints()]: () => {
            actions.setActiveTab('endpoints')
            actions.loadEndpoints()
        },
        [urls.endpointsUsage()]: () => {
            actions.setActiveTab('usage')
        },
    })),
])
