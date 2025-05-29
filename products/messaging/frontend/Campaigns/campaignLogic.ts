import { Workflow, WorkflowEdge, WorkflowNode } from '@posthog/workflows'
import { actions, afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb, PropertyFilterType, PropertyOperator } from '~/types'

import type { campaignLogicType } from './campaignLogicType'

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
    name: 'Untitled campaign',
    description: '',
    workflow: { nodes: initialNodes, edges: initialEdges },
    created_at: null,
    updated_at: null,
    created_by: null,
    version: 1,
}

export enum CampaignTabs {
    Overview = 'overview',
    Workflow = 'workflow',
}

export const CAMPAIGN_TAB_TO_NAME: Record<CampaignTabs, string> = {
    [CampaignTabs.Overview]: 'Overview',
    [CampaignTabs.Workflow]: 'Workflow',
}

export const campaignLogic = kea<campaignLogicType>([
    path(['products', 'messaging', 'frontend', 'campaignLogic']),
    props({ id: 'new' } as CampaignLogicProps),
    key((props) => props.id || 'new'),
    actions({
        setCurrentTab: (tab: CampaignTabs = CampaignTabs.Overview) => ({ tab }),
        updateCampaignName: (name: string) => ({ name }),
        updateWorkflow: (workflow: Workflow['workflow']) => ({ workflow }),
    }),
    reducers({
        currentTab: [
            CampaignTabs.Overview,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    }),
    loaders(({ props }) => ({
        campaign: [
            { ...DEFAULT_WORKFLOW } as Workflow,
            {
                loadCampaign: async () => {
                    if (!props.id || props.id === 'new') {
                        return { ...DEFAULT_WORKFLOW }
                    }

                    const campaign = await api.hogFunctions.get(props.id)
                    return { ...DEFAULT_WORKFLOW, name: campaign.name, description: campaign.description }
                },
                updateCampaignName: ({ name }: { name: string }) => {
                    return { ...DEFAULT_WORKFLOW, name }
                },
                updateCampaign: ({ workflow }: { workflow: Workflow['workflow'] }) => {
                    return { ...DEFAULT_WORKFLOW, workflow }
                },
            },
        ],
    })),
    selectors(() => ({
        breadcrumbs: [
            // Optional if you'd like the breadcrumbs to show the current tab
            (s) => [s.campaign],
            (campaign): Breadcrumb[] => {
                return [
                    { name: 'Campaigns', key: 'campaigns', path: urls.messagingCampaigns() },
                    {
                        name: campaign.name || 'Untitled campaign',
                        key: 'campaign',
                        onRename: async (name) => {
                            alert(name)
                        },
                    },
                ]
            },
        ],
    })),
    actionToUrl(({ props, values }) => {
        return {
            setCurrentTab: () => [urls.messagingCampaign(props.id || 'new', values.currentTab)],
        }
    }),
    urlToAction(({ actions, values }) => ({
        '/messaging/campaigns/:id/:tab': ({ tab }) => {
            if (tab !== values.currentTab) {
                actions.setCurrentTab(tab as CampaignTabs)
            }
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.id && props.id !== 'new') {
            actions.loadCampaign()
        }
    }),
])
