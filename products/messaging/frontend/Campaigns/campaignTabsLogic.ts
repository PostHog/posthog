import { actions, kea, path, reducers } from 'kea'

import type { campaignTabsLogicType } from './campaignTabsLogicType'

export type CampaignTab = 'configuration' | 'logs'

export const campaignTabsLogic = kea<campaignTabsLogicType>([
    path(['products', 'messaging', 'frontend', 'campaignTabsLogic']),
    actions({
        setTab: (tab: CampaignTab) => ({ tab }),
    }),
    reducers({
        currentTab: ['configuration' as CampaignTab, { setTab: (_, { tab }) => tab }],
    }),
])
