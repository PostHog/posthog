import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { slugify } from 'lib/utils'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { urls } from 'scenes/urls'

import { EndpointRequest, HogQLQuery, InsightQueryNode, NodeKind } from '~/queries/schema/schema-general'
import { DataWarehouseSyncInterval, EndpointType } from '~/types'

import type { endpointLogicType } from './endpointLogicType'
import { endpointsLogic } from './endpointsLogic'

export type CodeExampleTab = 'terminal' | 'python' | 'nodejs'

export interface EndpointLogicProps {
    tabId: string
}

const NEW_ENDPOINT: Partial<EndpointType> = {
    name: 'new-endpoint',
    description: 'New endpoint returns this and that',
    query: {
        kind: NodeKind.HogQLQuery,
        query: 'select * from events limit 1',
    } as HogQLQuery | InsightQueryNode,
}

export const endpointLogic = kea<endpointLogicType>([
    path(['products', 'endpoints', 'frontend', 'endpointLogic']),
    props({} as EndpointLogicProps),
    key((props) => props.tabId),
    connect(() => ({
        actions: [endpointsLogic, ['loadEndpoints']],
    })),
    actions({
        setEndpointName: (endpointName: string) => ({ endpointName }),
        setEndpointDescription: (endpointDescription: string) => ({ endpointDescription }),
        setActiveCodeExampleTab: (tab: CodeExampleTab) => ({ tab }),
        setIsUpdateMode: (isUpdateMode: boolean) => ({ isUpdateMode }),
        setSelectedEndpointName: (selectedEndpointName: string | null) => ({ selectedEndpointName }),
        setCacheAge: (cacheAge: number | null) => ({ cacheAge }),
        setSyncFrequency: (syncFrequency: DataWarehouseSyncInterval | null) => ({ syncFrequency }),
        setIsMaterialized: (isMaterialized: boolean | null) => ({ isMaterialized }),
        createEndpoint: (request: EndpointRequest) => ({ request }),
        createEndpointSuccess: (response: any) => ({ response }),
        createEndpointFailure: (error: any) => ({ error }),
        updateEndpoint: (name: string, request: Partial<EndpointRequest>) => ({ name, request }),
        updateEndpointSuccess: (response: any) => ({ response }),
        updateEndpointFailure: (error: any) => ({ error }),
        deleteEndpoint: (name: string) => ({ name }),
        deleteEndpointSuccess: (response: any) => ({ response }),
        deleteEndpointFailure: (error: any) => ({ error }),
        deactivateEndpoint: (name: string) => ({ name }),
        deactivateEndpointSuccess: (response: any) => ({ response }),
        deactivateEndpointFailure: (error: any) => ({ error }),
        materializeEndpoint: (name: string, syncFrequency: DataWarehouseSyncInterval) => ({
            name,
            syncFrequency,
        }),
        materializeEndpointSuccess: (response: any) => ({ response }),
        materializeEndpointFailure: (error: any) => ({ error }),
        unmaterializeEndpoint: (name: string) => ({ name }),
        unmaterializeEndpointSuccess: (response: any) => ({ response }),
        unmaterializeEndpointFailure: (error: any) => ({ error }),
    }),
    reducers({
        endpointName: [null as string | null, { setEndpointName: (_, { endpointName }) => endpointName }],
        endpointDescription: [
            null as string | null,
            { setEndpointDescription: (_, { endpointDescription }) => endpointDescription },
        ],
        activeCodeExampleTab: ['terminal' as CodeExampleTab, { setActiveCodeExampleTab: (_, { tab }) => tab }],
        isUpdateMode: [
            false,
            {
                setIsUpdateMode: (_, { isUpdateMode }) => isUpdateMode,
            },
        ],
        selectedEndpointName: [
            null as string | null,
            {
                setSelectedEndpointName: (_, { selectedEndpointName }) => selectedEndpointName,
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
    }),
    loaders(({ actions }) => ({
        endpoint: [
            null as EndpointType | null,
            {
                loadEndpoint: async (name: string) => {
                    if (!name || name === 'new') {
                        return { ...NEW_ENDPOINT } as EndpointType
                    }
                    const endpoint = await api.endpoint.get(name)

                    // Fetch last execution time
                    try {
                        const executionTimes = await api.endpoint.getLastExecutionTimes({ names: [name] })
                        if (executionTimes[name]) {
                            endpoint.last_executed_at = executionTimes[name]
                        }
                    } catch (error) {
                        console.error('Failed to fetch last execution time:', error)
                    }

                    // TODO: This does not belong here. Refactor to the endpointSceneLogic?
                    actions.setCacheAge(endpoint.cache_age_seconds ?? null)
                    actions.setSyncFrequency(endpoint.materialization?.sync_frequency ?? null)
                    actions.setIsMaterialized(endpoint.is_materialized ?? null)

                    return endpoint
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        createEndpoint: async ({ request }) => {
            try {
                if (request.name) {
                    request.name = slugify(request.name)
                }
                const response = await api.endpoint.create(request)
                actions.createEndpointSuccess(response)
            } catch (error) {
                console.error('Failed to create endpoint:', error)
                actions.createEndpointFailure(error)
            }
        },
        createEndpointSuccess: ({ response }) => {
            actions.setEndpointName('')
            actions.setEndpointDescription('')
            lemonToast.success(
                <>
                    Endpoint created successfully!
                    <br />
                    You will be redirected to the endpoint page.
                </>,
                {
                    onClose: () => {
                        router.actions.push(urls.endpoint(response.name))
                    },
                }
            )
        },
        createEndpointFailure: ({ error }) => {
            console.error('Failed to create endpoint:', error)
            lemonToast.error('Failed to create endpoint')
        },
        updateEndpoint: async ({ name, request }) => {
            try {
                const response = await api.endpoint.update(name, request)
                actions.updateEndpointSuccess(response)
            } catch (error) {
                console.error('Failed to update endpoint:', error)
                actions.updateEndpointFailure(error)
            }
        },
        updateEndpointSuccess: ({ response }) => {
            lemonToast.success('Endpoint updated successfully')
            actions.loadEndpoint(response.name)
        },
        updateEndpointFailure: ({ error }) => {
            console.error('Failed to update endpoint:', error)
            lemonToast.error('Failed to update endpoint')
        },
        deleteEndpoint: async ({ name }) => {
            try {
                // TODO: Add confirmation dialog
                await api.endpoint.delete(name)
                actions.deleteEndpointSuccess(name)
            } catch (error) {
                console.error('Failed to delete endpoint:', error)
                actions.deleteEndpointFailure(error)
            }
        },
        deleteEndpointSuccess: () => {
            lemonToast.success('Endpoint deleted successfully')
            actions.loadEndpoints()
        },
        deleteEndpointFailure: ({ error }) => {
            console.error('Failed to delete endpoint:', error)
            lemonToast.error('Failed to delete endpoint')
        },
        deactivateEndpoint: async ({ name }) => {
            try {
                await api.endpoint.update(name, {
                    is_active: false,
                })
                actions.deactivateEndpointSuccess({})
            } catch (error) {
                console.error('Failed to deactivate endpoint:', error)
                actions.deactivateEndpointFailure(error)
            }
        },
        deactivateEndpointSuccess: () => {
            lemonToast.success('Endpoint deactivated successfully')
            actions.loadEndpoints()
        },
        deactivateEndpointFailure: ({ error }) => {
            console.error('Failed to deactivate endpoint:', error)
            lemonToast.error('Failed to deactivate endpoint')
        },
        materializeEndpoint: async ({ name, syncFrequency }) => {
            try {
                const response = await api.endpoint.update(name, {
                    is_materialized: true,
                    sync_frequency: syncFrequency,
                })
                actions.materializeEndpointSuccess(response)
            } catch (error) {
                console.error('Failed to materialize endpoint:', error)
                actions.materializeEndpointFailure(error)
            }
        },
        materializeEndpointSuccess: ({ response }) => {
            lemonToast.success('Endpoint materialization enabled successfully')
            actions.loadEndpoint(response.name)
        },
        materializeEndpointFailure: ({ error }) => {
            console.error('Failed to materialize endpoint:', error)
            lemonToast.error('Failed to enable materialization')
        },
        unmaterializeEndpoint: async ({ name }) => {
            try {
                const response = await api.endpoint.update(name, {
                    is_materialized: false,
                })
                actions.unmaterializeEndpointSuccess(response)
            } catch (error) {
                console.error('Failed to unmaterialize endpoint:', error)
                actions.unmaterializeEndpointFailure(error)
            }
        },
        unmaterializeEndpointSuccess: ({ response }) => {
            lemonToast.success('Endpoint materialization disabled successfully')
            actions.loadEndpoint(response.name)
        },
        unmaterializeEndpointFailure: ({ error }) => {
            console.error('Failed to disable materialization:', error)
            lemonToast.error('Failed to disable materialization')
        },
    })),
    permanentlyMount(),
])
