import { actions, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { campaignsLogicType } from './campaignsLogicType'

export const campaignsLogic = kea<campaignsLogicType>([
    path(['products', 'messaging', 'frontend', 'campaignsLogic']),
    actions({
        editCampaign: (id: string | null) => ({ id }),
    }),
    reducers({
        campaignId: [null as string | null, { editCampaign: (_, { id }) => id }],
    }),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        key: Scene.MessagingCampaigns,
                        name: 'Messaging',
                        path: urls.messagingCampaigns(),
                    },
                    {
                        key: 'campaigns',
                        name: 'Campaigns',
                        path: urls.messagingCampaigns(),
                    },
                ]
            },
        ],
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
