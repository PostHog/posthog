import { kea, path, selectors } from 'kea'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { messageLibraryLogicType } from './messageLibraryLogicType'

export const messageLibraryLogic = kea<messageLibraryLogicType>([
    path(['products', 'messaging', 'frontend', 'messageLibraryLogic']),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        key: Scene.MessagingLibrary,
                        name: 'Messaging',
                        path: urls.messagingLibrary(),
                    },
                    {
                        key: 'templates',
                        name: 'Templates',
                        path: urls.messagingLibrary(),
                    },
                ]
            },
        ],
    }),
])
