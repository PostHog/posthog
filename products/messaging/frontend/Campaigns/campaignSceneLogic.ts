import { actions, connect, kea, path, props, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { campaignLogic } from './campaignLogic'
import type { campaignSceneLogicType } from './campaignSceneLogicType'
import { Workflow } from './Workflows/temporary_workflow_types_for_dev_to_be_deleted'

export const CampaignTabs = ['overview', 'workflow'] as const
export type CampaignTab = (typeof CampaignTabs)[number]

export interface CampaignSceneLogicProps {
    id?: string
}

export const campaignSceneLogic = kea<campaignSceneLogicType>([
    path(['products', 'messaging', 'frontend', 'campaignSceneLogic']),
    props({ id: 'new' } as CampaignSceneLogicProps),
    connect((props: CampaignSceneLogicProps) => ({
        values: [campaignLogic(props), ['campaign']],
        actions: [campaignLogic(props), ['updateCampaign']],
    })),
    actions({
        setCurrentTab: (tab: CampaignTab) => ({ tab }),
    }),
    reducers({
        currentTab: [
            'overview' as CampaignTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            (s) => [s.campaign],
            (campaign: Workflow): Breadcrumb[] => {
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
                    {
                        key: 'campaign',
                        name: campaign.name || 'Untitled Campaign',
                        onRename: async (name: string): Promise<void> => {
                            alert(`Renaming campaign to ${name}`)
                        },
                    },
                ]
            },
        ],
    }),
    actionToUrl(({ values }) => ({
        setCurrentTab: () => [urls.messagingCampaign(values.currentTab)],
    })),
    urlToAction(({ actions, values }) => ({
        '/messaging/campaigns/:id/:tab': ({ tab }) => {
            if (tab !== values.currentTab) {
                actions.setCurrentTab(tab as CampaignTab)
            }
        },
    })),
])
