import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { debounce, slugify } from 'lib/utils'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { EndpointRequest, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { EndpointType } from '~/types'

import type { endpointLogicType } from './endpointLogicType'
import { endpointsLogic } from './endpointsLogic'

export type CodeExampleTab = 'terminal' | 'python' | 'nodejs'

export interface EndpointLogicProps {
    tabId: string
}

export const endpointLogic = kea<endpointLogicType>([
    path(['products', 'endpoints', 'frontend', 'endpointLogic']),
    props({} as EndpointLogicProps),
    key((props) => props.tabId),
    connect(() => ({
        actions: [
            endpointsLogic,
            ['loadEndpoints'],
            sceneLayoutLogic,
            ['setScenePanelOpen'],
            teamLogic,
            ['addProductIntent'],
        ],
    })),
    actions({
        setEndpointName: (endpointName: string) => ({ endpointName }),
        setEndpointDescription: (endpointDescription: string) => ({ endpointDescription }),
        setActiveCodeExampleTab: (tab: CodeExampleTab) => ({ tab }),
        setSelectedCodeExampleVersion: (version: number | null) => ({ version }),
        setIsUpdateMode: (isUpdateMode: boolean) => ({ isUpdateMode }),
        setSelectedEndpointName: (selectedEndpointName: string | null) => ({ selectedEndpointName }),
        openCreateFromInsightModal: true,
        setDuplicateEndpoint: (endpoint: EndpointType | null) => ({ endpoint }),
        createEndpoint: (request: EndpointRequest) => ({ request }),
        createEndpointSuccess: (response: any) => ({ response }),
        createEndpointFailure: (isHogQLError?: boolean) => ({ isHogQLError }),
        updateEndpoint: (name: string, request: Partial<EndpointRequest>, showViewButton?: boolean) => ({
            name,
            request,
            showViewButton,
        }),
        updateEndpointSuccess: (response: any, showViewButton?: boolean) => ({ response, showViewButton }),
        updateEndpointFailure: (isHogQLError?: boolean) => ({ isHogQLError }),
        deleteEndpoint: (name: string) => ({ name }),
        deleteEndpointSuccess: (response: any) => ({ response }),
        deleteEndpointFailure: () => ({}),
        confirmToggleActive: (endpoint: EndpointType) => ({ endpoint }),
    }),
    reducers({
        endpointName: [null as string | null, { setEndpointName: (_, { endpointName }) => endpointName }],
        endpointDescription: [
            null as string | null,
            { setEndpointDescription: (_, { endpointDescription }) => endpointDescription },
        ],
        activeCodeExampleTab: ['terminal' as CodeExampleTab, { setActiveCodeExampleTab: (_, { tab }) => tab }],
        selectedCodeExampleVersion: [
            null as number | null,
            { setSelectedCodeExampleVersion: (_, { version }) => version },
        ],
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
        duplicateEndpoint: [
            null as EndpointType | null,
            {
                setDuplicateEndpoint: (_, { endpoint }) => endpoint,
            },
        ],
    }),
    loaders(({ actions, values }) => ({
        endpoint: [
            null as EndpointType | null,
            {
                loadEndpoint: async (name: string) => {
                    if (!name) {
                        return null
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

                    return endpoint
                },
            },
        ],
        materializationStatus: [
            null as EndpointType['materialization'] | null,
            {
                loadMaterializationStatus: async (name: string) => {
                    if (!name) {
                        return null
                    }
                    const materializationStatus = await api.endpoint.getMaterializationStatus(name)

                    // Update the endpoint object with the new materialization status
                    if (values.endpoint) {
                        const updatedEndpoint = {
                            ...values.endpoint,
                            materialization: materializationStatus,
                            is_materialized: materializationStatus?.can_materialize
                                ? !!materializationStatus.status
                                : false,
                        }
                        actions.loadEndpointSuccess(updatedEndpoint)
                    }

                    return materializationStatus
                },
            },
        ],
    })),
    listeners(({ actions }) => {
        const reloadMaterializationStatus = debounce((name: string): void => {
            actions.loadMaterializationStatus(name)
        }, 2000)
        return {
            openCreateFromInsightModal: () => {
                actions.loadEndpoints()
            },
            createEndpoint: async ({ request }) => {
                try {
                    if (request.name) {
                        request.name = slugify(request.name)
                    }
                    const response = await api.endpoint.create(request)
                    actions.createEndpointSuccess(response)
                } catch (error: any) {
                    console.error('Failed to create endpoint:', error)
                    const isHogQLError = error.attr === 'query' && error.detail?.startsWith('Invalid HogQL query')
                    actions.createEndpointFailure(isHogQLError)
                }
            },
            createEndpointSuccess: ({ response }) => {
                actions.setEndpointName('')
                actions.setEndpointDescription('')
                actions.loadEndpoints()
                lemonToast.success(<>Endpoint created</>, {
                    button: {
                        label: 'View',
                        action: () => {
                            // Close the scene panel (info & actions panel) if endpoint was created from insight
                            if (response.derived_from_insight) {
                                actions.setScenePanelOpen(false)
                            }
                            router.actions.push(urls.endpoint(response.name))
                        },
                    },
                })

                // Mark endpoint creation task as completed
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.CreateFirstEndpoint)

                // Track product intent for sidebar visibility
                const intentContext = response.derived_from_insight
                    ? ProductIntentContext.ENDPOINT_CREATED_FROM_INSIGHT
                    : ProductIntentContext.ENDPOINT_CREATED_FROM_SQL_EDITOR
                actions.addProductIntent({
                    product_type: ProductKey.ENDPOINTS,
                    intent_context: intentContext,
                })
            },
            createEndpointFailure: ({ isHogQLError }) => {
                if (isHogQLError) {
                    lemonToast.error(
                        'Invalid HogQL query. Try running it first and fix any errors before creating an endpoint.'
                    )
                } else {
                    lemonToast.error('Failed to create endpoint')
                }
            },
            updateEndpoint: async ({ name, request, showViewButton }) => {
                try {
                    const response = await api.endpoint.update(name, request)
                    actions.updateEndpointSuccess(response, showViewButton)
                    actions.loadEndpoints()
                } catch (error: any) {
                    console.error('Failed to update endpoint:', error)
                    const isHogQLError = error.attr === 'query' && error.detail?.startsWith('Invalid HogQL query')
                    actions.updateEndpointFailure(isHogQLError)
                }
            },
            updateEndpointSuccess: ({ response, showViewButton }) => {
                if (showViewButton) {
                    lemonToast.success(<>Endpoint updated</>, {
                        button: {
                            label: 'View',
                            action: () => router.actions.push(urls.endpoint(response.name)),
                        },
                    })
                } else {
                    lemonToast.success('Endpoint updated')
                }

                reloadMaterializationStatus(response.name)

                // Mark activation task as completed when endpoint is activated
                if (response.is_active) {
                    globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.ConfigureEndpoint)
                }
            },
            updateEndpointFailure: ({ isHogQLError }) => {
                if (isHogQLError) {
                    lemonToast.error(
                        'Invalid HogQL query. Try running it first and fix any errors before updating the endpoint.'
                    )
                } else {
                    lemonToast.error('Failed to update endpoint')
                }
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
            confirmToggleActive: ({ endpoint }) => {
                const isActivating = !endpoint.is_active
                LemonDialog.open({
                    title: isActivating ? 'Activate endpoint?' : 'Deactivate endpoint?',
                    content: (
                        <div className="text-sm text-secondary">
                            {isActivating
                                ? 'Are you sure you want to activate this endpoint? It will be accessible via the API.'
                                : 'Are you sure you want to deactivate this endpoint? It will no longer be accessible via the API.'}
                        </div>
                    ),
                    primaryButton: {
                        children: isActivating ? 'Activate' : 'Deactivate',
                        type: 'primary',
                        status: isActivating ? undefined : 'danger',
                        onClick: () => {
                            actions.updateEndpoint(endpoint.name, { is_active: isActivating })
                        },
                        size: 'small',
                    },
                    secondaryButton: {
                        children: 'Cancel',
                        type: 'tertiary',
                        size: 'small',
                    },
                })
            },
        }
    }),
    permanentlyMount(),
])
