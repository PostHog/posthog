import { WorkflowNodeData } from '@posthog/workflows'
import { Node } from '@xyflow/react'
import { kea, key, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { nodeDetailsLogicType } from './nodeDetailsLogicType'

export interface NodeDetailsLogicProps {
    workflowId: string
    node: Node<WorkflowNodeData> | null
    onNodeChange: (node: Node<WorkflowNodeData>) => void
}

export const nodeDetailsLogic = kea<nodeDetailsLogicType>([
    path(['products', 'messaging', 'frontend', 'Campaigns', 'Workflows', 'nodeDetailsLogic']),
    props({
        workflowId: 'new',
        node: null,
    } as NodeDetailsLogicProps),
    key(({ workflowId, node }) => `${workflowId}-${node?.id}`),
    selectors({
        breadcrumbs: [
            () => [(_, props) => props],
            (props: NodeDetailsLogicProps): Breadcrumb[] => {
                const { workflowId } = props

                if (!workflowId) {
                    return []
                }

                return [
                    {
                        key: Scene.MessagingCampaigns,
                        name: 'Messaging',
                        path: urls.messagingCampaigns(),
                    },
                    {
                        key: 'campaigns',
                        name: 'Campaigns',
                        path: urls.messagingCampaigns(),
                    },
                    ...(workflowId === 'new'
                        ? [
                              {
                                  key: 'new-campaign',
                                  name: 'New campaign',
                                  path: urls.messagingCampaignNew(),
                              },
                          ]
                        : [
                              {
                                  key: 'edit-campaign',
                                  name: 'Manage campaign',
                                  path: urls.messagingCampaign(workflowId),
                              },
                          ]),
                ]
            },
        ],
    }),
    forms(({ props }) => ({
        nodeDetails: {
            defaults: {
                ...props.node,
            },
            submit: async (node: Node<WorkflowNodeData>) => {
                props.onNodeChange(node)
            },
        },
    })),
])
