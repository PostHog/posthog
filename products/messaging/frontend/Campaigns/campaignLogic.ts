import { actions, afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { campaignLogicType } from './campaignLogicType'
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
    actions({
        setCurrentTab: (tab: CampaignTab = 'overview') => ({ tab }),
        updateCampaignName: (name: string) => ({ name }),
        updateWorkflow: (workflow: Workflow['workflow']) => ({ workflow }),
    }),
    reducers({
        currentTab: [
            'overview' as CampaignTab,
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

                    // TODO: Replace with hogflow API call
                    const campaign = await api.hogFunctions.get(props.id)
                    return { ...DEFAULT_WORKFLOW, name: campaign.name, description: campaign.description }
                },
                updateCampaignName: ({ name }: { name: string }) => {
                    return { ...DEFAULT_WORKFLOW, name }
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
                actions.setCurrentTab(tab as CampaignTab)
            }
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.id && props.id !== 'new') {
            actions.loadCampaign()
        }
    }),
])
