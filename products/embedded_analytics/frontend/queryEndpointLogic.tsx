import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { urls } from 'scenes/urls'

import { NamedQueryRequest, NodeKind } from '~/queries/schema/schema-general'

import type { queryEndpointLogicType } from './queryEndpointLogicType'
import { queryEndpointsLogic } from './queryEndpointsLogic'

export type CodeExampleTab = 'terminal' | 'python' | 'nodejs'

export interface QueryEndpointLogicProps {
    tabId: string
}

export const queryEndpointLogic = kea<queryEndpointLogicType>([
    path(['products', 'embedded_analytics', 'frontend', 'queryEndpointLogic']),
    props({} as QueryEndpointLogicProps),
    key((props) => props.tabId),
    connect(() => ({
        actions: [queryEndpointsLogic, ['loadQueryEndpoints']],
    })),
    actions({
        setQueryEndpointName: (queryEndpointName: string) => ({ queryEndpointName }),
        setQueryEndpointDescription: (queryEndpointDescription: string) => ({ queryEndpointDescription }),
        setActiveCodeExampleTab: (tab: CodeExampleTab) => ({ tab }),
        createQueryEndpoint: (request: NamedQueryRequest) => ({ request }),
        createQueryEndpointSuccess: (response: any) => ({ response }),
        createQueryEndpointFailure: (error: any) => ({ error }),
        deleteQueryEndpoint: (name: string) => ({ name }),
        deleteQueryEndpointSuccess: (response: any) => ({ response }),
        deleteQueryEndpointFailure: (error: any) => ({ error }),
        deactivateQueryEndpoint: (name: string) => ({ name }),
        deactivateQueryEndpointSuccess: (response: any) => ({ response }),
        deactivateQueryEndpointFailure: (error: any) => ({ error }),
    }),
    reducers({
        queryEndpointName: [
            null as string | null,
            { setQueryEndpointName: (_, { queryEndpointName }) => queryEndpointName },
        ],
        queryEndpointDescription: [
            null as string | null,
            { setQueryEndpointDescription: (_, { queryEndpointDescription }) => queryEndpointDescription },
        ],
        activeCodeExampleTab: ['terminal' as CodeExampleTab, { setActiveCodeExampleTab: (_, { tab }) => tab }],
    }),
    listeners(({ actions }) => ({
        createQueryEndpoint: async ({ request }) => {
            try {
                const response = await api.queryEndpoint.create(request)
                actions.createQueryEndpointSuccess(response)
            } catch (error) {
                console.error('Failed to create query endpoint:', error)
                actions.createQueryEndpointFailure(error)
            }
        },
        createQueryEndpointSuccess: () => {
            actions.setQueryEndpointName('')
            actions.setQueryEndpointDescription('')
            lemonToast.success(
                <>
                    Query endpoint created successfully!
                    <br />
                    You will be redirected to the query endpoints page.
                </>,
                {
                    onClose: () => {
                        router.actions.push(urls.embeddedAnalyticsQueryEndpoints())
                    },
                }
            )
        },
        createQueryEndpointFailure: ({ error }) => {
            console.error('Failed to create query endpoint:', error)
            lemonToast.error('Failed to create query endpoint')
        },
        deleteQueryEndpoint: async ({ name }) => {
            try {
                // TODO: Add confirmation dialog
                await api.queryEndpoint.delete(name)
                actions.deleteQueryEndpointSuccess(name)
            } catch (error) {
                console.error('Failed to delete query endpoint:', error)
                actions.deleteQueryEndpointFailure(error)
            }
        },
        deleteQueryEndpointSuccess: () => {
            lemonToast.success('Query endpoint deleted successfully')
            actions.loadQueryEndpoints()
        },
        deleteQueryEndpointFailure: ({ error }) => {
            console.error('Failed to delete query endpoint:', error)
            lemonToast.error('Failed to delete query endpoint')
        },
        deactivateQueryEndpoint: async ({ name }) => {
            try {
                await api.queryEndpoint.update(name, {
                    query: { kind: NodeKind.HogQLQuery, query: '' },
                    is_active: false,
                })
                actions.deactivateQueryEndpointSuccess({})
            } catch (error) {
                console.error('Failed to deactivate query endpoint:', error)
                actions.deactivateQueryEndpointFailure(error)
            }
        },
        deactivateQueryEndpointSuccess: () => {
            lemonToast.success('Query endpoint deactivated successfully')
        },
        deactivateQueryEndpointFailure: ({ error }) => {
            console.error('Failed to deactivate query endpoint:', error)
            lemonToast.error('Failed to deactivate query endpoint')
        },
    })),
    permanentlyMount(),
])
