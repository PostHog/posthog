import { actions, kea, path, props, reducers } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'

import { CampaignTab } from './campaignLogic'
import type { campaignSceneLogicType } from './campaignSceneLogicType'

export interface CampaignSceneLogicProps {
    id?: string
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
