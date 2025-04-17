import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { HogFunctionKind, HogFunctionTypeType, UserBasicType } from '~/types'

import type { messagesLogicType } from './messagesLogicType'

export interface Message {
    id: string
    created_by: UserBasicType | null
    created_at: string | null
    name: string
    description: string
    content: Record<string, any>
    created_by_id: string
    template_id: string
    type: HogFunctionTypeType
    kind: HogFunctionKind
}

export const messagesLogic = kea<messagesLogicType>([
    path(['products', 'messaging', 'frontend', 'library', 'messagesLogic']),
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
    })),
    afterMount(({ actions }) => {
        actions.loadMessages()
    }),
])
