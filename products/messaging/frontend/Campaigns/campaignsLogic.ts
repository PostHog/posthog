import { actions, afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { campaignsLogicType } from './campaignsLogicType'
import type { HogFlow } from './Workflows/types'

export const campaignsLogic = kea<campaignsLogicType>([
    path(['products', 'messaging', 'frontend', 'campaignsLogic']),
    actions({
        deleteCampaign: (campaign: HogFlow) => ({ campaign }),
        loadCampaigns: () => ({}),
    }),
    loaders(({ values }) => ({
        campaigns: [
            [] as HogFlow[],
            {
                loadCampaigns: async () => {
                    const response = await api.hogFlows.getHogFlows()
                    return response.results
                },
                deleteCampaign: async ({ campaign }) => {
                    await api.hogFlows.deleteHogFlow(campaign.id)
                    return values.campaigns.filter((c) => c.id !== campaign.id)
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadCampaigns()
    }),
])
