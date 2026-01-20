import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataTableNode, EndpointRunRequest, InsightVizNode, Node, NodeKind } from '~/queries/schema/schema-general'
import { isHogQLQuery, isInsightQueryNode } from '~/queries/utils'
import { Breadcrumb, DataWarehouseSyncInterval, EndpointType } from '~/types'

import { endpointLogic } from './endpointLogic'
import type { endpointSceneLogicType } from './endpointSceneLogicType'

export interface EndpointSceneLogicProps {
    tabId: string
}

export function generateEndpointPayload(endpoint: EndpointType | null): Record<string, any> {
    if (!endpoint) {
        return {}
    }

    if (isInsightQueryNode(endpoint.query)) {
        return {
            query_override: {},
            filters_override: {},
        }
    }
    if (endpoint.query?.kind === NodeKind.HogQLQuery) {
        const variables = endpoint.query?.variables || {}
        const entries = Object.entries(variables)

        if (entries.length === 0) {
            return {}
        }

        const variablesValues: Record<string, any> = {}
        entries.forEach(([_, value]: [string, any]) => {
            variablesValues[value.code_name] = value.value
        })

        return { variables: variablesValues }
    }
    return {}
}

function generateInitialPayloadJson(endpoint: EndpointType | null): string {
    return JSON.stringify(generateEndpointPayload(endpoint), null, 2)
}

export enum EndpointTab {
    QUERY = 'query',
    CONFIGURATION = 'configuration',
    PLAYGROUND = 'playground',
    HISTORY = 'history',
}

export const endpointSceneLogic = kea<endpointSceneLogicType>([
    props({} as EndpointSceneLogicProps),
    path(['products', 'endpoints', 'frontend', 'endpointSceneLogic']),
    tabAwareScene(),
    connect((props: EndpointSceneLogicProps) => ({
        actions: [endpointLogic({ tabId: props.tabId }), ['loadEndpoint', 'loadEndpointSuccess']],
        values: [endpointLogic({ tabId: props.tabId }), ['endpoint', 'endpointLoading']],
    })),
    actions({
        setLocalQuery: (query: Node | null) => ({ query }),
        setActiveTab: (tab: EndpointTab) => ({ tab }),
        setPayloadJson: (value: string) => ({ value }),
        setPayloadJsonError: (error: string | null) => ({ error }),
        setCacheAge: (cacheAge: number | null) => ({ cacheAge }),
        setSyncFrequency: (syncFrequency: DataWarehouseSyncInterval | null) => ({ syncFrequency }),
        setIsMaterialized: (isMaterialized: boolean | null) => ({ isMaterialized }),
        setEndpointName: (name: string | null) => ({ name }),
    }),
    reducers({
        localQuery: [
            null as Node | null,
            {
                setLocalQuery: (_, { query }) => query,
                loadEndpointSuccess: () => null,
            },
        ],
        activeTab: [
            EndpointTab.QUERY as EndpointTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        payloadJson: [
            '' as string,
            {
                setPayloadJson: (_, { value }) => value,
            },
        ],
        payloadJsonError: [
            null as string | null,
            {
                setPayloadJsonError: (_, { error }) => error,
                setPayloadJson: () => null,
            },
        ],
        cacheAge: [
            null as number | null,
            {
                setCacheAge: (_, { cacheAge }) => cacheAge,
            },
        ],
        syncFrequency: [
            '24hour' as DataWarehouseSyncInterval | null,
            {
                setSyncFrequency: (_, { syncFrequency }) => syncFrequency,
            },
        ],
        isMaterialized: [
            true as boolean | null,
            {
                setIsMaterialized: (_, { isMaterialized }) => isMaterialized,
                loadEndpointSuccess: (_, { endpoint }) => endpoint?.is_materialized ?? null,
            },
        ],
        endpointName: [
            null as string | null,
            {
                setEndpointName: (_, { name }) => name,
            },
        ],
    }),
    loaders(() => ({
        endpointResult: {
            __default: null as string | null,
            loadEndpointResult: async ({ name, data }: { name: string; data: EndpointRunRequest }) => {
                try {
                    const result = await api.endpoint.run(name, data)
                    if (result && typeof result === 'object' && 'clickhouse' in result) {
                        const { clickhouse, ...rest } = result as any
                        return JSON.stringify(rest, null, 2)
                    }
                    return JSON.stringify(result, null, 2)
                } catch (error: any) {
                    const errorResponse = {
                        error: true,
                        message: error.message || 'Unknown error',
                        status: error.status,
                        detail: error.detail || error.data,
                    }
                    return JSON.stringify(errorResponse, null, 2)
                }
            },
        },
    })),
    selectors({
        currentQuery: [
            (s) => [s.localQuery, s.endpoint],
            (localQuery: Node | null, endpoint: EndpointType | null): Node | null =>
                localQuery || endpoint?.query || null,
        ],
        queryToRender: [
            (s) => [s.currentQuery],
            (currentQuery: Node | null): Node | null => {
                if (!currentQuery) {
                    return null
                }

                if (isHogQLQuery(currentQuery)) {
                    return {
                        kind: NodeKind.DataTableNode,
                        source: currentQuery,
                        showHogQLEditor: true,
                    } as DataTableNode
                }

                if (isInsightQueryNode(currentQuery)) {
                    return {
                        kind: NodeKind.InsightVizNode,
                        source: currentQuery,
                        full: true,
                    } as InsightVizNode
                }

                return currentQuery
            },
        ],
        breadcrumbs: [
            (s) => [s.endpoint],
            (endpoint: EndpointType | null): Breadcrumb[] => [
                {
                    key: Scene.Endpoints,
                    name: 'Endpoints',
                    path: urls.endpoints(),
                    iconType: 'endpoints',
                },
                {
                    key: [Scene.Endpoints, endpoint?.name || 'new'],
                    name: endpoint?.name || 'New Endpoint',
                },
            ],
        ],
    }),
    listeners(({ actions }) => ({
        loadEndpointSuccess: ({ endpoint }: { endpoint: EndpointType | null; payload?: string }) => {
            const initialPayload = generateInitialPayloadJson(endpoint)
            actions.setPayloadJson(initialPayload)
            actions.setCacheAge(endpoint?.cache_age_seconds ?? null)
            actions.setSyncFrequency(endpoint?.materialization?.sync_frequency ?? null)
        },
    })),
    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.endpoint(':name')]: ({ name }: { name?: string }, _, __, currentLocation, previousLocation) => {
            const { searchParams } = router.values
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            if (name && didPathChange) {
                const isSameEndpoint = values.endpointName === name

                if (!currentLocation.initial && isSameEndpoint) {
                    // Already viewing this endpoint, skip reload
                } else {
                    actions.setEndpointName(name)
                    actions.loadEndpoint(name)
                }
            }

            if (searchParams.tab && searchParams.tab !== values.activeTab) {
                actions.setActiveTab(searchParams.tab as EndpointTab)
            } else if (!searchParams.tab && values.activeTab !== EndpointTab.QUERY) {
                actions.setActiveTab(EndpointTab.QUERY)
            }
        },
    })),
])
