import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataTableNode, EndpointRunRequest, InsightVizNode, Node, NodeKind } from '~/queries/schema/schema-general'
import { isHogQLQuery, isInsightQueryNode } from '~/queries/utils'
import { Breadcrumb, DataWarehouseSyncInterval, EndpointType, EndpointVersionType } from '~/types'

import { endpointLogic } from './endpointLogic'
import type { endpointSceneLogicType } from './endpointSceneLogicType'

export interface EndpointSceneLogicProps {
    tabId: string
}

// Query types that support user-configurable breakdown filtering
const BREAKDOWN_SUPPORTED_QUERY_TYPES = new Set([NodeKind.TrendsQuery, NodeKind.FunnelsQuery, NodeKind.RetentionQuery])

function getSingleBreakdownProperty(breakdownFilter: any): string | null {
    if (breakdownFilter?.breakdown) {
        return breakdownFilter.breakdown
    }
    const breakdowns = breakdownFilter?.breakdowns || []
    if (breakdowns.length === 1) {
        return breakdowns[0]?.property
    }
    return null
}

export function generateEndpointPayload(endpoint: EndpointVersionType | null): Record<string, any> {
    if (!endpoint) {
        return {}
    }

    const query = endpoint.query
    const isMaterialized = endpoint.is_materialized
    const queryKind = query?.kind

    if (queryKind === NodeKind.HogQLQuery) {
        // HogQL: include variables with default values
        const variables = query.variables || {}
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

    if (isInsightQueryNode(query)) {
        // Insight query - build variables based on what's available
        const variablesValues: Record<string, any> = {}

        // Only include breakdown for query types that support it
        if (queryKind && BREAKDOWN_SUPPORTED_QUERY_TYPES.has(queryKind as NodeKind)) {
            const breakdownFilter = (query as any).breakdownFilter || {}
            const breakdown = getSingleBreakdownProperty(breakdownFilter)
            if (breakdown) {
                variablesValues[breakdown] = ''
            }
        }

        // Non-materialized also supports date filtering
        if (!isMaterialized) {
            variablesValues['date_from'] = '-7d'
            variablesValues['date_to'] = ''
        }

        if (Object.keys(variablesValues).length > 0) {
            return { variables: variablesValues }
        }
    }

    return {}
}

function generateInitialPayloadJson(endpoint: EndpointVersionType | null): string {
    return JSON.stringify(generateEndpointPayload(endpoint), null, 2)
}

export enum EndpointTab {
    QUERY = 'query',
    CONFIGURATION = 'configuration',
    VERSIONS = 'versions',
    PLAYGROUND = 'playground',
    HISTORY = 'history',
}

export const endpointSceneLogic = kea<endpointSceneLogicType>([
    props({} as EndpointSceneLogicProps),
    path(['products', 'endpoints', 'frontend', 'endpointSceneLogic']),
    tabAwareScene(),
    connect((props: EndpointSceneLogicProps) => ({
        actions: [
            endpointLogic({ tabId: props.tabId }),
            [
                'loadEndpoint',
                'loadEndpointSuccess',
                'loadVersions',
                'setEndpointDescription',
                'clearMaterializationStatus',
                'updateEndpointSuccess',
            ],
        ],
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
        setViewingVersion: (version: EndpointVersionType | null) => ({ version }),
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
        viewingVersion: [
            null as EndpointVersionType | null,
            {
                setViewingVersion: (_, { version }) => version,
                // Note: Don't reset on loadEndpointSuccess - the listener handles restoring from URL
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
            (s) => [s.localQuery, s.endpoint, s.viewingVersion],
            (
                localQuery: Node | null,
                endpoint: EndpointType | null,
                viewingVersion: EndpointVersionType | null
            ): Node | null => localQuery || viewingVersion?.query || endpoint?.query || null,
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
        loadEndpointSuccess: async ({ endpoint }: { endpoint: EndpointVersionType | null; payload?: string }) => {
            const initialPayload = generateInitialPayloadJson(endpoint)
            actions.setPayloadJson(initialPayload)
            actions.setCacheAge(endpoint?.cache_age_seconds ?? null)
            actions.setSyncFrequency(endpoint?.materialization?.sync_frequency ?? null)

            const { searchParams } = router.values

            // Load versions if on versions tab
            if (searchParams.tab === EndpointTab.VERSIONS && endpoint?.name) {
                actions.loadVersions(endpoint.name)
            }

            // Handle version param from URL
            if (searchParams.version && endpoint?.name) {
                const versionNumber = parseInt(searchParams.version, 10)
                if (!isNaN(versionNumber) && versionNumber !== endpoint.current_version) {
                    try {
                        const versionData = await api.endpoint.get(endpoint.name, versionNumber)
                        actions.setViewingVersion(versionData)
                    } catch {
                        // Version not found, clear the param
                        router.actions.replace(urls.endpoint(endpoint.name), { ...searchParams, version: undefined })
                        actions.setViewingVersion(null)
                    }
                } else {
                    // Version equals current, clear viewing version
                    actions.setViewingVersion(null)
                }
            } else {
                // No version param, clear viewing version
                actions.setViewingVersion(null)
            }
        },
        setActiveTab: ({ tab }) => {
            if (tab === EndpointTab.VERSIONS && values.endpoint?.name) {
                actions.loadVersions(values.endpoint.name)
            }
        },
        setViewingVersion: ({ version }) => {
            // Reset local state so viewed version's data shows through
            actions.setLocalQuery(null)
            actions.setCacheAge(null)
            actions.setSyncFrequency(null)
            actions.setIsMaterialized(null)
            actions.clearMaterializationStatus()

            // Reset description to viewed version's description (or endpoint's if going back to current)
            if (version) {
                actions.setEndpointDescription(version.description || '')
            } else if (values.endpoint) {
                actions.setEndpointDescription(values.endpoint.description || '')
            }

            // Update payload with version field if viewing a specific version
            if (values.endpoint) {
                const basePayload = generateEndpointPayload(values.endpoint)
                if (version && version.version !== values.endpoint.current_version) {
                    const payloadWithVersion = { ...basePayload, version: version.version }
                    actions.setPayloadJson(JSON.stringify(payloadWithVersion, null, 2))
                } else {
                    actions.setPayloadJson(JSON.stringify(basePayload, null, 2))
                }
            }

            // Update URL when viewing version changes
            const { searchParams } = router.values
            if (values.endpoint?.name) {
                if (version && version.version !== values.endpoint.current_version) {
                    router.actions.replace(urls.endpoint(values.endpoint.name), {
                        ...searchParams,
                        version: version.version,
                    })
                } else {
                    // Clear version param when going back to current version
                    const { version: _, ...rest } = searchParams
                    router.actions.replace(urls.endpoint(values.endpoint.name), rest)
                }
            }
        },
        loadEndpointResultSuccess: () => {
            // Mark test endpoint task as completed when user runs an endpoint in the playground
            globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.TestEndpoint)
        },
        updateEndpointSuccess: async ({ endpointName, options }) => {
            // Reload the viewed version after update to get fresh data
            const versionToReload = options?.version ?? values.viewingVersion?.version
            if (versionToReload && endpointName) {
                try {
                    const versionData = await api.endpoint.get(endpointName, versionToReload)
                    actions.setViewingVersion(versionData)
                } catch {
                    // Version may have been deleted, clear it
                    actions.setViewingVersion(null)
                }
            }
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

            // Handle version param changes without full endpoint reload
            if (!didPathChange && name) {
                const versionParam = searchParams.version ? parseInt(searchParams.version, 10) : null
                const currentViewingVersion = values.viewingVersion?.version ?? null

                if (versionParam !== currentViewingVersion) {
                    if (versionParam && values.endpoint?.name) {
                        // Load the requested version
                        const requestedVersion = versionParam
                        api.endpoint
                            .get(name, versionParam)
                            .then((versionData) => {
                                // Only apply if this is still the requested version
                                const currentParam = router.values.searchParams.version
                                if (currentParam && parseInt(currentParam, 10) === requestedVersion) {
                                    actions.setViewingVersion(versionData)
                                }
                            })
                            .catch(() => {
                                // Version not found
                                actions.setViewingVersion(null)
                            })
                    } else {
                        actions.setViewingVersion(null)
                    }
                }
            }
        },
    })),
])
