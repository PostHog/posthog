import { actions, kea, path, props, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { campaignSceneLogicType } from './campaignSceneLogicType'

export const CampaignTabs = ['overview', 'workflow'] as const
export type CampaignTab = (typeof CampaignTabs)[number]

export interface CampaignSceneLogicProps {
    id?: string
    tab?: CampaignTab
}

export const campaignSceneLogic = kea<campaignSceneLogicType>([
    path(['products', 'messaging', 'frontend', 'campaignSceneLogic']),
    props({ id: 'new' } as CampaignSceneLogicProps),
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
            () => [(_, props) => props.id as CampaignSceneLogicProps['id']],
            (id): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Messaging,
                        name: 'Messaging',
                        path: urls.messaging(),
                    },
                    {
                        key: [Scene.Messaging, 'campaigns'],
                        name: 'Campaigns',
                        path: urls.messaging('campaigns'),
                    },
                    {
                        key: Scene.MessagingCampaign,
                        name: id == 'new' ? 'New campaign' : 'Manage campaign',
                    },
                ]
            },
        ],
    }),
    actionToUrl(({ props, values }) => ({
        setCurrentTab: () => [urls.messagingCampaign(props.id || 'new', values.currentTab)],
    })),
    urlToAction(({ actions, values }) => ({
        '/messaging/campaigns/:id/:tab': ({ tab }) => {
            if (tab !== values.currentTab) {
                actions.setCurrentTab(tab as CampaignTab)
            }
        },
    })),
])
