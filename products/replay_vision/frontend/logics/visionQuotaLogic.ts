import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { environmentVisionQuotaRetrieve } from '../generated/api'
import type { VisionQuotaApi } from '../generated/api.schemas'
import type { visionQuotaLogicType } from './visionQuotaLogicType'

export const visionQuotaLogic = kea<visionQuotaLogicType>([
    path(['products', 'replay_vision', 'frontend', 'logics', 'visionQuotaLogic']),

    loaders({
        quota: [
            null as VisionQuotaApi | null,
            {
                loadQuota: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    try {
                        return await environmentVisionQuotaRetrieve(String(teamId))
                    } catch {
                        return null
                    }
                },
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadQuota()
    }),
])
