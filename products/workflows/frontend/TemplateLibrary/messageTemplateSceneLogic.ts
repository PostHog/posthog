import { kea, path, props, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'
import { Breadcrumb } from '~/types'

import type { messageTemplateSceneLogicType } from './messageTemplateSceneLogicType'

export interface MessageTemplateSceneLogicProps {
    id: string
    messageId?: string | null
    tabId?: string
}

export const messageTemplateSceneLogic = kea<messageTemplateSceneLogicType>([
    path(['products', 'workflows', 'frontend', 'messageTemplateSceneLogic']),
    props({} as MessageTemplateSceneLogicProps),
    tabAwareScene(),
    selectors({
        breadcrumbs: [
            (_, p) => [p.id],
            (id: string): Breadcrumb[] => {
                return [
                    {
                        key: [Scene.Workflows, 'library'],
                        name: 'Library',
                        path: urls.workflows('library'),
                        iconType: 'workflows',
                    },
                    ...(id === 'new'
                        ? [
                              {
                                  key: 'new-template',
                                  name: 'New template',
                                  path: urls.workflowsLibraryTemplateNew(),
                                  iconType: 'workflows' as FileSystemIconType,
                              },
                          ]
                        : [
                              {
                                  key: 'edit-template',
                                  name: 'Manage template',
                                  path: urls.workflowsLibraryTemplate(id),
                                  iconType: 'workflows' as FileSystemIconType,
                              },
                          ]),
                ]
            },
        ],
    }),
])
