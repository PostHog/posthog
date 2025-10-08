import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataTableNode, InsightVizNode, Node, NodeKind } from '~/queries/schema/schema-general'
import { isHogQLQuery, isInsightQueryNode } from '~/queries/utils'
import { Breadcrumb, EndpointType } from '~/types'

import { endpointLogic } from './endpointLogic'
import type { endpointSceneLogicType } from './endpointSceneLogicType'

export enum EndpointTab {
    QUERY = 'query',
    CODE = 'code',
    CONFIGURATION = 'configuration',
    USAGE = 'usage',
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
    }),
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
    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.endpoint(':name')]: ({ name }: { name?: string }) => {
            const { searchParams } = router.values
            if (name) {
                actions.loadEndpoint(name)
            }
            if (searchParams.tab && searchParams.tab !== values.activeTab) {
                actions.setActiveTab(searchParams.tab as EndpointTab)
            } else if (!searchParams.tab && values.activeTab !== EndpointTab.QUERY) {
                actions.setActiveTab(EndpointTab.QUERY)
            }
        },
    })),
])
