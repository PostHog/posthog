import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataTableNode, EndpointRunRequest, InsightVizNode, Node, NodeKind } from '~/queries/schema/schema-general'
import { isHogQLQuery, isInsightQueryNode } from '~/queries/utils'
import { Breadcrumb, DataWarehouseSyncInterval, EndpointType, EndpointVersionType } from '~/types'

import { endpointLogic } from './endpointLogic'
import type { endpointSceneLogicType } from './endpointSceneLogicType'

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
    path(['products', 'endpoints', 'frontend', 'endpointSceneLogic']),
    tabAwareScene(),
    connect(() => ({
        actions: [endpointLogic, ['loadEndpoint', 'loadEndpointSuccess']],
        values: [endpointLogic, ['endpoint', 'endpointLoading']],
    })),
    actions({
        setLocalQuery: (query: Node | null) => ({ query }),
        setActiveTab: (tab: EndpointTab) => ({ tab }),
        setPayloadJson: (value: string) => ({ value }),
        setCacheAge: (cacheAge: number | null) => ({ cacheAge }),
        setSyncFrequency: (syncFrequency: DataWarehouseSyncInterval | null) => ({ syncFrequency }),
        setIsMaterialized: (isMaterialized: boolean | null) => ({ isMaterialized }),
        selectVersion: (version: number | null) => ({ version }),
        returnToCurrentVersion: true,
        updateVersionMaterialization: (
            version: number,
            data: Partial<Pick<EndpointVersionType, 'is_materialized' | 'sync_frequency'>>
        ) => ({ version, data }),
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
            null as boolean | null,
            {
                setIsMaterialized: (_, { isMaterialized }) => isMaterialized,
            },
        ],
        viewingVersion: [
            null as number | null,
            {
                selectVersion: (_, { version }) => version,
                returnToCurrentVersion: () => null,
                loadEndpointSuccess: () => null, // Reset when loading endpoint
            },
        ],
    }),
    loaders(() => ({
        versions: {
            __default: [] as EndpointVersionType[],
            loadVersions: async ({ name }: { name: string }) => {
                try {
                    return await api.endpoint.listVersions(name)
                } catch (error) {
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
        selectedVersionData: {
            __default: null as EndpointVersionType | null,
            loadSelectedVersion: async ({ name, version }: { name: string; version: number }) => {
                try {
                    return await api.endpoint.getVersion(name, version)
                } catch (error) {
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
        isViewingOldVersion: [
            (s) => [s.viewingVersion, s.endpoint],
            (viewingVersion: number | null, endpoint: EndpointType | null): boolean => {
                if (viewingVersion === null || endpoint === null) {
                    return false
                }
                return viewingVersion !== endpoint.current_version
            },
        ],
        currentEndpointData: [
            (s) => [s.endpoint, s.viewingVersion, s.selectedVersionData],
            (
                endpoint: EndpointType | null,
                viewingVersion: number | null,
                selectedVersionData: EndpointVersionType | null
            ): EndpointType | EndpointVersionType | null => {
                if (viewingVersion === null) {
                    return endpoint
                }
                return selectedVersionData
            },
        ],
        currentQuery: [
            (s) => [s.localQuery, s.endpoint, s.viewingVersion, s.selectedVersionData],
            (
                localQuery: Node | null,
                endpoint: EndpointType | null,
                viewingVersion: number | null,
                selectedVersionData: EndpointVersionType | null
            ): Node | null => {
                if (localQuery && viewingVersion === null) {
                    return localQuery
                }
                if (viewingVersion !== null && selectedVersionData) {
                    return selectedVersionData.query
                }
                return endpoint?.query || null
            },
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
    listeners(({ actions, values }) => ({
        loadEndpointSuccess: ({ endpoint }: { endpoint: EndpointType | null; payload?: string }) => {
            const initialPayload = generateInitialPayloadJson(endpoint)
            actions.setPayloadJson(initialPayload)
            actions.setCacheAge(endpoint?.cache_age_seconds ?? null)
            actions.setSyncFrequency(endpoint?.materialization?.sync_frequency ?? null)
            actions.setIsMaterialized(endpoint?.is_materialized ?? null)
            // Load versions when endpoint loads
            if (endpoint?.name) {
                actions.loadVersions({ name: endpoint.name })

                // Check if there's a version parameter in the URL
                const { searchParams } = router.values
                if (searchParams.version) {
                    const version = parseInt(searchParams.version, 10)
                    if (!isNaN(version) && version !== endpoint.current_version) {
                        actions.setViewingVersion(version)
                        actions.selectVersion(version)
                    }
                }
            }
        },
        selectVersion: ({ version }) => {
            const endpoint = values.endpoint
            if (!endpoint) {
                return
            }
            if (version !== null) {
                // Load the selected version data
                actions.loadSelectedVersion({ name: endpoint.name, version })
            }
        },
        loadSelectedVersionSuccess: ({ selectedVersionData }) => {
            const endpoint = values.endpoint
            if (!endpoint || !selectedVersionData) {
                return
            }
            // Update payload JSON to include version parameter when viewing old version
            if (selectedVersionData.version !== endpoint.current_version) {
                const currentPayload = values.payloadJson
                try {
                    const payload = currentPayload ? JSON.parse(currentPayload) : {}
                    payload.version = selectedVersionData.version
                    actions.setPayloadJson(JSON.stringify(payload, null, 2))
                } catch (error) {
                    // If current payload is invalid JSON, create new one with version
                    actions.setPayloadJson(JSON.stringify({ version: selectedVersionData.version }, null, 2))
                }
            }
        },
        returnToCurrentVersion: () => {
            const endpoint = values.endpoint
            if (!endpoint) {
                return
            }
            actions.setViewingVersion(null)
            actions.setLocalQuery(null)
            // Reset payload to default when returning to current version
            const initialPayload = generateInitialPayloadJson(endpoint)
            actions.setPayloadJson(initialPayload)
        },
        updateVersionMaterialization: async ({ version, data }) => {
            const endpoint = values.endpoint
            if (!endpoint) {
                return
            }
            try {
                await api.endpoint.updateVersion(endpoint.name, version, data)
                // Refresh versions list
                actions.loadVersions({ name: endpoint.name })
            } catch (error) {
                console.error('Failed to update version materialization:', error)
            }
        },
    })),
    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.endpoint(':name')]: ({ name }: { name?: string }) => {
            const { searchParams } = router.values
            if (name && (!values.endpoint || values.endpoint.name !== name)) {
                actions.loadEndpoint(name)
            }
            if (searchParams.tab && searchParams.tab !== values.activeTab) {
                actions.setActiveTab(searchParams.tab as EndpointTab)
            } else if (!searchParams.tab && values.activeTab !== EndpointTab.QUERY) {
                actions.setActiveTab(EndpointTab.QUERY)
            }
            // Handle version parameter
            if (searchParams.version) {
                const version = parseInt(searchParams.version, 10)
                if (!isNaN(version) && version !== values.viewingVersion) {
                    actions.setViewingVersion(version)
                    actions.selectVersion(version)
                }
            } else if (values.viewingVersion !== null) {
                // Reset to current version if no version param
                actions.setViewingVersion(null)
            }
        },
    })),
])
