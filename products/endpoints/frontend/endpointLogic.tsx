import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { debounce, slugify } from 'lib/utils'
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
        createEndpointFailure: () => ({}),
        updateEndpoint: (name: string, request: Partial<EndpointRequest>) => ({ name, request }),
        updateEndpointSuccess: (response: any) => ({ response }),
        updateEndpointFailure: () => ({}),
        deleteEndpoint: (name: string) => ({ name }),
        deleteEndpointSuccess: (response: any) => ({ response }),
        deleteEndpointFailure: () => ({}),
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
    listeners(({ actions }) => {
        const reloadEndpoint = debounce((name: string): void => {
            actions.loadEndpoint(name)
        }, 2000)
        return {
            createEndpoint: async ({ request }) => {
                try {
                    if (request.name) {
                        request.name = slugify(request.name)
                    }
                    const response = await api.endpoint.create(request)
                    actions.createEndpointSuccess(response)
                } catch (error) {
                    console.error('Failed to create endpoint:', error)
                    actions.createEndpointFailure()
                }
            },
            createEndpointSuccess: ({ response }) => {
                actions.setEndpointName('')
                actions.setEndpointDescription('')
                lemonToast.success(<>Endpoint created</>, {
                    button: {
                        label: 'View',
                        action: () => router.actions.push(urls.endpoint(response.name)),
                    },
                })
            },
            createEndpointFailure: () => {
                lemonToast.error('Failed to create endpoint')
            },
            updateEndpoint: async ({ name, request }) => {
                try {
                    const response = await api.endpoint.update(name, request)
                    actions.updateEndpointSuccess(response)
                } catch (error) {
                    console.error('Failed to update endpoint:', error)
                    actions.updateEndpointFailure()
                }
            },
            updateEndpointSuccess: ({ response }) => {
                lemonToast.success('Endpoint updated')
                reloadEndpoint(response.name)
            },
            updateEndpointFailure: () => {
                lemonToast.error('Failed to update endpoint')
            },
            deleteEndpoint: async ({ name }) => {
                try {
                    await api.endpoint.delete(name)
                    actions.deleteEndpointSuccess(name)
                } catch (error) {
                    console.error('Failed to delete endpoint:', error)
                    actions.deleteEndpointFailure()
                }
            },
            deleteEndpointSuccess: () => {
                lemonToast.success('Endpoint deleted')
                actions.loadEndpoints()
            },
            deleteEndpointFailure: () => {
                lemonToast.error('Failed to delete endpoint')
            },
        }
    }),
    permanentlyMount(),
])
