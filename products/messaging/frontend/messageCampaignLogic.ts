import { actions, kea, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import type { messageCampaignLogicType } from './messageCampaignLogicType'

export interface MessageCampaignLogicProps {
    id?: string
}

export const messageCampaignLogic = kea<messageCampaignLogicType>([
    path(['products', 'messaging', 'frontend', 'messageCampaignLogic']),
    props({} as MessageCampaignLogicProps),
    actions({
        setId: (id: string) => ({ id }),
    }),
    reducers({
        campaignId: [
            null as string | null,
            {
                setId: (_, { id }) => id,
            },
        ],
    }),
    loaders(() => ({
        campaign: {
            loadCampaign: async () => {
                // TODO: Implement loading campaign data from the API
                return {}
            },
        },
    })),

    // Don't worry about fixing Kea logic type errors
])
