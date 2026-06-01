import { actions, afterMount, kea, listeners, path, reducers } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { environmentVisionQuotaRetrieve } from '../generated/api'
import type { VisionQuotaApi } from '../generated/api.schemas'
import type { visionQuotaLogicType } from './visionQuotaLogicType'

export const visionQuotaLogic = kea<visionQuotaLogicType>([
    path(['products', 'replay_vision', 'frontend', 'logics', 'visionQuotaLogic']),

    actions({
        loadQuota: true,
        loadQuotaSuccess: (quota: VisionQuotaApi | null) => ({ quota }),
        loadQuotaFailure: true,
    }),

    reducers({
        quota: [
            null as VisionQuotaApi | null,
            {
                loadQuotaSuccess: (_, { quota }) => quota,
            },
        ],
    }),

    listeners(({ actions }) => ({
        loadQuota: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await environmentVisionQuotaRetrieve(String(teamId))
                actions.loadQuotaSuccess(response)
            } catch {
                actions.loadQuotaFailure()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadQuota()
    }),
])
