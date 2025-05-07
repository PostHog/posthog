import { actions, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, ProjectTreeRef } from '~/types'

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
            (s) => [s.campaignId],
            (campaignId): Breadcrumb[] => {
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
                    ...(campaignId === 'new'
                        ? [
                              {
                                  key: 'new-campaign',
                                  name: 'New campaign',
                                  path: urls.messagingCampaignNew(),
                              },
                          ]
                        : campaignId
                        ? [
                              {
                                  key: 'edit-campaign',
                                  name: 'Manage campaign',
                                  path: urls.messagingCampaign(campaignId),
                              },
                          ]
                        : []),
                ]
            },
        ],
        projectTreeRef: [
            (s) => [s.campaignId],
            (id): ProjectTreeRef => ({
                type: 'hog_function/campaign',
                ref: id === 'new' ? null : id,
            }),
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
