import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { createFuse } from 'lib/utils/fuseSearch'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { EndpointType } from '~/types'

import type { endpointsLogicType } from './endpointsLogicType'

export type EndpointsTab = 'endpoints' | 'usage'

export interface EndpointsFilters {
    search: string
    tags: string[]
}

export const DEFAULT_FILTERS: EndpointsFilters = {
    search: '',
    tags: [],
}

export interface EndpointsLogicProps {
    tabId: string
}

export const endpointsLogic = kea<endpointsLogicType>([
    path(['products', 'endpoints', 'frontend', 'endpointsLogic']),
    props({} as EndpointsLogicProps),
    key((props) => props.tabId),
    connect(() => ({
        actions: [teamLogic, ['addProductIntent']],
    })),
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
                    return response.results || []
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
                let results = allEndpoints

                if (filters.tags.length > 0) {
                    const required = new Set(filters.tags)
                    results = results.filter((endpoint) => endpoint.tags?.some((tag) => required.has(tag)))
                }

                if (filters.search) {
                    const fuse = createFuse<EndpointType>(results, {
                        keys: ['name', 'description', 'query.query'],
                        threshold: 0.3,
                    })
                    results = fuse.search(filters.search).map((result) => result.item)
                }

                return results
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadEndpoints()
        actions.addProductIntent({
            product_type: ProductKey.ENDPOINTS,
            intent_context: ProductIntentContext.ENDPOINTS_VIEWED,
        })
    }),

    tabAwareUrlToAction(({ actions }) => ({
        [urls.endpoints()]: (_, searchParams) => {
            if (searchParams.tab === 'usage') {
                actions.setActiveTab('usage')
            } else {
                actions.setActiveTab('endpoints')
                actions.loadEndpoints()
            }
        },
    })),
])
