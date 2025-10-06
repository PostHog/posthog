import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { urls } from 'scenes/urls'

import { NamedQueryRequest } from '~/queries/schema/schema-general'

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
        actions: [endpointsLogic, ['loadEndpoints']],
    })),
    actions({
        setEndpointName: (endpointName: string) => ({ endpointName }),
        setEndpointDescription: (endpointDescription: string) => ({ endpointDescription }),
        setActiveCodeExampleTab: (tab: CodeExampleTab) => ({ tab }),
        createEndpoint: (request: NamedQueryRequest) => ({ request }),
        createEndpointSuccess: (response: any) => ({ response }),
        createEndpointFailure: (error: any) => ({ error }),
        deleteEndpoint: (name: string) => ({ name }),
        deleteEndpointSuccess: (response: any) => ({ response }),
        deleteEndpointFailure: (error: any) => ({ error }),
        deactivateEndpoint: (name: string) => ({ name }),
        deactivateEndpointSuccess: (response: any) => ({ response }),
        deactivateEndpointFailure: (error: any) => ({ error }),
    }),
    reducers({
        endpointName: [null as string | null, { setEndpointName: (_, { endpointName }) => endpointName }],
        endpointDescription: [
            null as string | null,
            { setEndpointDescription: (_, { endpointDescription }) => endpointDescription },
        ],
        activeCodeExampleTab: ['terminal' as CodeExampleTab, { setActiveCodeExampleTab: (_, { tab }) => tab }],
    }),
    listeners(({ actions }) => ({
        createEndpoint: async ({ request }) => {
            try {
                const response = await api.endpoint.create(request)
                actions.createEndpointSuccess(response)
            } catch (error) {
                console.error('Failed to create endpoint:', error)
                actions.createEndpointFailure(error)
            }
        },
        createEndpointSuccess: () => {
            actions.setEndpointName('')
            actions.setEndpointDescription('')
            lemonToast.success(
                <>
                    Endpoint created successfully!
                    <br />
                    You will be redirected to the endpoints page.
                </>,
                {
                    onClose: () => {
                        router.actions.push(urls.endpoints())
                    },
                }
            )
        },
        createEndpointFailure: ({ error }) => {
            console.error('Failed to create endpoint:', error)
            lemonToast.error('Failed to create endpoint')
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
    })),
    permanentlyMount(),
])
