import { actions, afterMount, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { campaignsLogicType } from './campaignsLogicType'
import type { HogFlow } from './Workflows/types'

export const campaignsLogic = kea<campaignsLogicType>([
    path(['products', 'messaging', 'frontend', 'campaignsLogic']),
    actions({
        editCampaign: (id: string | null) => ({ id }),
        deleteCampaign: (campaign: HogFlow) => ({ campaign }),
        loadCampaigns: () => ({}),
    }),
    reducers({
        campaignId: [null as string | null, { editCampaign: (_, { id }) => id }],
    }),
    loaders(({ actions }) => ({
        campaigns: [
            [] as HogFlow[],
            {
                loadCampaigns: async () => {
                    const response = await api.hogFlows.getHogFlows()
                    return response.results
                },
                deleteCampaign: async ({ campaign }) => {
                    await api.hogFlows.deleteHogFlow(campaign.id)
                    return actions.loadCampaigns()
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadCampaigns()
    }),
])
