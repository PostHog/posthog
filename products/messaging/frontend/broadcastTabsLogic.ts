import { actions, kea, path, reducers } from 'kea'

import type { broadcastTabsLogicType } from './broadcastTabsLogicType'

export type BroadcastTab = 'configuration' | 'logs'

export const broadcastTabsLogic = kea<broadcastTabsLogicType>([
    path(['products', 'messaging', 'frontend', 'broadcastTabsLogic']),
    actions({
        setTab: (tab: BroadcastTab) => ({ tab }),
    }),
    reducers({
        currentTab: ['configuration' as BroadcastTab, { setTab: (_, { tab }) => tab }],
    }),
])
