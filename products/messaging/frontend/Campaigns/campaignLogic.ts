import { actions, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { PropertyFilterType, PropertyOperator } from '~/types'

import type { campaignLogicType } from './campaignLogicType'
import { Workflow, WorkflowEdge, WorkflowNode } from './Workflows/types'

export interface CampaignLogicProps {
    id?: string
}

// Initial node setup - just one starting node
const initialNodes: WorkflowNode[] = [
    {
        id: 'start-node',
        type: 'trigger',
        data: {
            name: 'Trigger',
            description: 'Trigger',
            config: {
                filters: {
                    match_type: 'all',
                    properties: [
                        {
                            key: '$event',
                            value: '$pageview',
                            type: PropertyFilterType.Event,
                            operator: PropertyOperator.Exact,
                        },
                    ],
                },
            },
        },
        position: { x: 250, y: 100 },
    },
]

// Initial edges setup - empty array
const initialEdges: WorkflowEdge[] = []

const DEFAULT_WORKFLOW: Workflow = {
    id: 'default',
    name: 'Default Workflow',
    description: 'Default workflow',
    json: { nodes: initialNodes, edges: initialEdges },
    created_at: null,
    updated_at: null,
    created_by: null,
}

export const campaignLogic = kea<campaignLogicType>([
    path(['products', 'messaging', 'frontend', 'campaignLogic']),
    props({} as CampaignLogicProps),
    key((props) => `campaign_${props.id || 'new'}`),
    actions({
        updateWorkflowJson: (json: Workflow['json']) => ({ json }),
    }),
    loaders({
        workflow: [
            { ...DEFAULT_WORKFLOW } as Workflow,
            {
                loadWorkflowJson: async () => {
                    return { ...DEFAULT_WORKFLOW }
                },
                updateWorkflowJson: ({ json }: { json: Workflow['json'] }) => {
                    return { ...DEFAULT_WORKFLOW, json }
                },
            },
        ],
    }),
])
