import { kea, key, path, props, selectors } from 'kea'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { libraryTemplateLogicType } from './libraryTemplateLogicType'

export interface LibraryTemplateLogicProps {
    logicKey?: string
    id?: string | null
}

export const libraryTemplateLogic = kea<libraryTemplateLogicType>([
    path(['products', 'messaging', 'frontend', 'libraryTemplateLogic']),
    key(({ id }) => id ?? 'unknown'),
    props({} as LibraryTemplateLogicProps),
    selectors({
        breadcrumbs: [
            () => [(_, props) => props],
            (props: LibraryTemplateLogicProps): Breadcrumb[] => {
                const { id } = props

                if (!id) {
                    return []
                }

                return [
                    {
                        key: Scene.MessagingLibrary,
                        name: 'Messaging',
                        path: urls.messagingLibrary(),
                    },
                    {
                        key: 'library',
                        name: 'Library',
                        path: urls.messagingLibrary(),
                    },
                    ...(id === 'new'
                        ? [
                              {
                                  key: 'new-template',
                                  name: 'New template',
                                  path: urls.messagingLibraryTemplateNew(),
                              },
                          ]
                        : [
                              {
                                  key: 'edit-template',
                                  name: 'Manage template',
                                  path: urls.messagingLibraryTemplate(id),
                              },
                          ]),
                ]
            },
        ],
    }),
])
