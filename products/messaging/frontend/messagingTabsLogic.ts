import { actions, kea, path, reducers } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'

import type { messagingTabsLogicType } from './messagingTabsLogicType'

export type MessagingTab = 'broadcasts' | 'providers' | 'automations' | 'library'

export const messagingTabsLogic = kea<messagingTabsLogicType>([
    path(['products', 'messaging', 'frontend', 'messagingTabsLogic']),
    actions({
        setTab: (tab: MessagingTab, fromUrl = false) => ({ tab, fromUrl }),
    }),
    reducers({
        currentTab: ['broadcasts' as MessagingTab, { setTab: (_, { tab }) => tab }],
    }),
    actionToUrl(({ values }) => ({
        setTab: ({ fromUrl }) => {
            // do not override deeper urls like /messaging/broadcasts/new
            if (!fromUrl) {
                return (
                    {
                        automations: urls.messagingAutomations(),
                        broadcasts: urls.messagingBroadcasts(),
                        providers: urls.messagingProviders(),
                        library: urls.messagingLibrary(),
                    }[values.currentTab] ?? urls.messagingBroadcasts()
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
