import { actions, kea, path, reducers } from 'kea'
import { urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'

import type { campaignsLogicType } from './campaignsLogicType'

export const campaignsLogic = kea<campaignsLogicType>([
    path(['products', 'messaging', 'frontend', 'campaignsLogic']),
    actions({
        editCampaign: (id: string | null) => ({ id }),
    }),
    reducers({
        campaignId: [null as string | null, { editCampaign: (_, { id }) => id }],
    }),
    urlToAction(({ actions }) => ({
        [urls.messagingCampaignNew()]: () => {
            actions.editCampaign('new')
        },
        [`${urls.messagingCampaigns()}/:id`]: ({ id }) => {
            actions.editCampaign(id ?? null)
        },
        [urls.messagingCampaigns()]: () => {
            actions.editCampaign(null)
        },
    })),
])
