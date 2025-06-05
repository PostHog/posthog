import { actions, afterMount, connect, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import type { campaignLogicType } from './campaignLogicType'
import { campaignSceneLogic } from './campaignSceneLogic'
import { Workflow } from './Workflows/temporary_workflow_types_for_dev_to_be_deleted'

export interface CampaignLogicProps {
    id?: string
}

const DEFAULT_WORKFLOW: Workflow = {
    id: 'new',
    name: 'Untitled campaign',
    description: '',
    workflow: { nodes: [], edges: [] },
    created_at: null,
    updated_at: null,
    created_by: null,
    version: 1,
}

export const CampaignTabs = ['overview', 'workflow'] as const
export type CampaignTab = (typeof CampaignTabs)[number]

export const campaignLogic = kea<campaignLogicType>([
    path(['products', 'messaging', 'frontend', 'campaignLogic']),
    props({ id: 'new' } as CampaignLogicProps),
    key((props) => props.id || 'new'),
    connect(() => ({
        values: [campaignSceneLogic, ['currentTab']],
    })),
    actions({
        updateCampaignName: (name: string) => ({ name }),
        updateWorkflow: (workflow: Workflow['workflow']) => ({ workflow }),
    }),
    loaders(({ props }) => ({
        campaign: [
            { ...DEFAULT_WORKFLOW } as Workflow,
            {
                loadCampaign: async () => {
                    if (!props.id || props.id === 'new') {
                        return { ...DEFAULT_WORKFLOW }
                    }

                    // TODO: Add GET /hog_flows/{id} API call
                    return { ...DEFAULT_WORKFLOW, name: 'My campaign', description: 'Lorem ipsum dolor sit amet' }
                },
                updateCampaignName: ({ name }: { name: string }) => {
                    return { ...DEFAULT_WORKFLOW, name }
                },
            },
        ],
    })),
    afterMount(({ actions, props }) => {
        if (props.id && props.id !== 'new') {
            actions.loadCampaign()
        }
    }),
])
