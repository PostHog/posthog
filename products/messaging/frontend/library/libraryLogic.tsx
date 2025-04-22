import { kea, path, selectors } from 'kea'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { libraryLogicType } from './libraryLogicType'

export const libraryLogic = kea<libraryLogicType>([
    path(['products', 'messaging', 'frontend', 'libraryLogic']),
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
