import { kea, key, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { nodeDetailsLogicType } from './nodeDetailsLogicType'
import { WorkflowNode } from './types'

export interface NodeDetailsLogicProps {
    workflowId: string
    node: WorkflowNode
    onNodeChange: (node: WorkflowNode) => void
}

export const nodeDetailsLogic = kea<nodeDetailsLogicType>([
    path(['products', 'messaging', 'frontend', 'Campaigns', 'Workflows', 'nodeDetailsLogic']),
    key(({ workflowId, node }) => `${workflowId}-${node.id}`),
    props({} as NodeDetailsLogicProps),
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
        node: {
            defaults: {
                ...props.node,
            },
            submit: async (node) => {
                props.onNodeChange(node)
            },
        },
    })),
])
