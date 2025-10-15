import { actions, afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { campaignsLogicType } from './campaignsLogicType'
import type { HogFlow } from './hogflows/types'

export const campaignsLogic = kea<campaignsLogicType>([
    path(['products', 'messaging', 'frontend', 'campaignsLogic']),
    actions({
        toggleCampaignStatus: (campaign: HogFlow) => ({ campaign }),
        duplicateCampaign: (campaign: HogFlow) => ({ campaign }),
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
                toggleCampaignStatus: async ({ campaign }) => {
                    const updatedCampaign = await api.hogFlows.updateHogFlow(campaign.id, {
                        status: campaign.status === 'active' ? 'draft' : 'active',
                    })
                    return values.campaigns.map((c) => (c.id === updatedCampaign.id ? updatedCampaign : c))
                },
                duplicateCampaign: async ({ campaign }) => {
                    const duplicatedCampaign = await api.hogFlows.createHogFlow({
                        ...campaign,
                        status: 'draft',
                        name: `${campaign.name} (copy)`,
                    })
                    return [duplicatedCampaign, ...values.campaigns]
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
