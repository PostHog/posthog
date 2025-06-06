import { actions, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { broadcastsLogicType } from './broadcastsLogicType'

export const broadcastsLogic = kea<broadcastsLogicType>([
    path(['products', 'messaging', 'frontend', 'broadcastsLogic']),
    actions({
        editBroadcast: (id: string | null) => ({ id }),
    }),
    reducers({
        broadcastId: [null as string | null, { editBroadcast: (_, { id }) => id }],
    }),
    selectors({
        breadcrumbs: [
            (s) => [s.broadcastId],
            (broadcastId): Breadcrumb[] => {
                return [
                    {
                        key: Scene.MessagingBroadcasts,
                        name: 'Messaging',
                        path: urls.messagingBroadcasts(),
                    },
                    {
                        key: 'broadcasts',
                        name: 'Broadcasts',
                        path: urls.messagingBroadcasts(),
                    },
                    ...(broadcastId === 'new'
                        ? [
                              {
                                  key: 'new-broadcast',
                                  name: 'New broadcast',
                                  path: urls.messagingBroadcastNew(),
                              },
                          ]
                        : broadcastId
                        ? [
                              {
                                  key: 'edit-broadcast',
                                  name: 'Manage broadcast',
                                  path: urls.messagingBroadcast(broadcastId),
                              },
                          ]
                        : []),
                ]
            },
        ],
    }),
    urlToAction(({ actions }) => ({
        '/messaging/broadcasts/new': () => {
            actions.editBroadcast('new')
        },
        '/messaging/broadcasts/:id': ({ id }) => {
            actions.editBroadcast(id ?? null)
        },
        '/messaging/broadcasts': () => {
            actions.editBroadcast(null)
        },
    })),
])
