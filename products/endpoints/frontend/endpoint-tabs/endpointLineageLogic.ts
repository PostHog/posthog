import { afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { DataModelingEdge, DataModelingNode } from '~/types'

import type { endpointLineageLogicType } from './endpointLineageLogicType'

export interface EndpointLineageLogicProps {
    savedQueryId: string
}

export interface EndpointLineageGraph {
    nodes: DataModelingNode[]
    edges: DataModelingEdge[]
}

export const endpointLineageLogic = kea<endpointLineageLogicType>([
    path((savedQueryId) => ['products', 'endpoints', 'frontend', 'endpointLineageLogic', savedQueryId]),
    props({} as EndpointLineageLogicProps),
    key((props) => props.savedQueryId),
    loaders(({ props }) => ({
        lineage: {
            __default: null as EndpointLineageGraph | null,
            loadLineage: async () => await api.dataModelingNodes.lineage({ savedQueryId: props.savedQueryId }),
        },
    })),
    reducers({
        lineageMissing: [
            false,
            {
                loadLineage: () => false,
                loadLineageSuccess: () => false,
                // The backing model has no lineage node yet, which is not a failure the user can retry away.
                loadLineageFailure: (_, { errorObject }) => errorObject?.status === 404,
            },
        ],
        lineageFailed: [
            false,
            {
                loadLineage: () => false,
                loadLineageSuccess: () => false,
                loadLineageFailure: (_, { errorObject }) => errorObject?.status !== 404,
            },
        ],
    }),
    selectors({
        currentNodeId: [
            (s, p) => [s.lineage, p.savedQueryId],
            (lineage: EndpointLineageGraph | null, savedQueryId: string): string | undefined =>
                lineage?.nodes.find((node) => node.saved_query_id === savedQueryId)?.id,
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadLineage()
    }),
])
