import { WorkflowNodeData } from '@posthog/workflows'
import { Node } from '@xyflow/react'
import { kea, key, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { stepDetailsLogicType } from './stepDetailsLogicType'

export interface StepDetailsLogicProps {
    workflowId: string
    node: Node<WorkflowNodeData> | null
    onChange: (node: Node<WorkflowNodeData>) => void
}

export const stepDetailsLogic = kea<stepDetailsLogicType>([
    path(['products', 'messaging', 'frontend', 'Campaigns', 'Workflows', 'stepDetailsLogic']),
    props({
        workflowId: 'new',
        node: null,
    } as StepDetailsLogicProps),
    key(({ workflowId, node }) => `${workflowId}-${node?.id}`),
    selectors({
        breadcrumbs: [
            () => [(_, props) => props],
            (props: StepDetailsLogicProps): Breadcrumb[] => {
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
                props.onChange(node)
            },
        },
    })),
])
