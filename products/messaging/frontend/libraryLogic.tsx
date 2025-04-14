import { afterMount, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, HogFunctionKind, HogFunctionTypeType, UserBasicType } from '~/types'

import type { libraryLogicType } from './libraryLogicType'

export interface MessageTemplate {
    id: string
    name: string
    description: string
    type: string
    content: Record<string, any>
    created_at: string
    updated_at: string
}

export interface Message {
    id: string
    created_by: UserBasicType | null
    created_at: string | null
    name: string
    description: string
    inputs: Record<string, any>
    created_by_id: string
    template_id: string
    type: HogFunctionTypeType
    kind: HogFunctionKind
}

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
                        key: 'library',
                        name: 'Library',
                        path: urls.messagingLibrary(),
                    },
                ]
            },
        ],
    }),
    loaders(() => ({
        messages: [
            [] as Message[],
            {
                loadMessages: async () => {
                    const response = await api.messaging.getMessages()
                    return response.results
                },
            },
        ],
        templates: [
            [] as MessageTemplate[],
            {
                loadTemplates: async () => {
                    const response = await api.messaging.getTemplates()
                    return response.results
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadMessages()
        actions.loadTemplates()
    }),
])
