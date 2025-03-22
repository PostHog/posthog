import { actions, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { automationsLogicType } from './automationsLogicType'

export const automationsLogic = kea<automationsLogicType>([
    path(['products', 'messaging', 'frontend', 'automationsLogic']),
    actions({
        editAutomation: (id: string | null) => ({ id }),
    }),
    reducers({
        automationId: [null as string | null, { editAutomation: (_, { id }) => id }],
    }),
    selectors({
        breadcrumbs: [
            (s) => [s.automationId],
            (automationId): Breadcrumb[] => {
                return [
                    {
                        key: Scene.MessagingAutomations,
                        name: 'Messaging',
                        path: urls.messagingAutomations(),
                    },
                    {
                        key: 'automations',
                        name: 'Automations',
                        path: urls.messagingAutomations(),
                    },
                    ...(automationId === 'new'
                        ? [
                              {
                                  key: 'new-automation',
                                  name: 'New automation',
                                  path: urls.messagingAutomationNew(),
                              },
                          ]
                        : automationId
                        ? [
                              {
                                  key: 'edit-automation',
                                  name: 'Edit automation',
                                  path: urls.messagingAutomation(automationId),
                              },
                          ]
                        : []),
                ]
            },
        ],
    }),
    urlToAction(({ actions }) => ({
        '/messaging/automations/new': () => {
            actions.editAutomation('new')
        },
        '/messaging/automations/:id': ({ id }) => {
            actions.editAutomation(id ?? null)
        },
        '/messaging/automations': () => {
            actions.editAutomation(null)
        },
    })),
])
