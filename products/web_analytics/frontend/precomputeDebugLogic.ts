import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import { getCurrentTeamId } from '~/lib/utils/getAppContext'

import { webAnalyticsPrecomputeDebug } from './generated/api'
import type { PrecomputeDebugResponseApi } from './generated/api.schemas'
import type { precomputeDebugLogicType } from './precomputeDebugLogicType'

export const precomputeDebugLogic = kea<precomputeDebugLogicType>([
    path(['products', 'web_analytics', 'frontend', 'precomputeDebugLogic']),

    loaders({
        debugState: [
            null as PrecomputeDebugResponseApi | null,
            {
                loadDebugState: async () => {
                    return await webAnalyticsPrecomputeDebug(String(getCurrentTeamId()))
                },
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadDebugState()
    }),
])
