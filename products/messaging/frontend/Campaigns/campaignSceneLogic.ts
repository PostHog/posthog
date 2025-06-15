import { actions, kea, path, props, reducers } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'

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
