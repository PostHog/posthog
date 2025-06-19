import { actions, kea, path, reducers } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'

import type { messagingTabsLogicType } from './messagingTabsLogicType'

export type MessagingTab = 'campaigns' | 'library' | 'senders'

export const messagingTabsLogic = kea<messagingTabsLogicType>([
    path(['products', 'messaging', 'frontend', 'messagingTabsLogic']),
    actions({
        setTab: (tab: MessagingTab, fromUrl = false) => ({ tab, fromUrl }),
    }),
    reducers({
        currentTab: ['campaigns' as MessagingTab, { setTab: (_, { tab }) => tab }],
    }),
    actionToUrl(({ values }) => ({
        setTab: ({ fromUrl }) => {
            // do not override deeper urls like /messaging/campaigns/new
            if (!fromUrl) {
                return (
                    {
                        campaigns: urls.messagingCampaigns(),
                        library: urls.messagingLibrary(),
                        senders: urls.messagingSenders(),
                    }[values.currentTab] ?? urls.messagingCampaigns()
                )
            }
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/messaging/:tab': ({ tab }) => {
            if (tab !== values.currentTab) {
                actions.setTab(tab as MessagingTab, true)
            }
        },
        '/messaging/:tab/*': ({ tab }) => {
            if (tab !== values.currentTab) {
                actions.setTab(tab as MessagingTab, true)
            }
        },
    })),
])
