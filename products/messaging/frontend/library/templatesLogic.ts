import { afterMount, connect, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { projectLogic } from 'scenes/projectLogic'

import { HogFunctionKind, HogFunctionTypeType, UserBasicType } from '~/types'

import type { templatesLogicType } from './templatesLogicType'

export interface MessageTemplate {
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

export const templatesLogic = kea<templatesLogicType>([
    path(['products', 'messaging', 'frontend', 'library', 'templatesLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    loaders(({ values, actions }) => ({
        templates: [
            [] as MessageTemplate[],
            {
                loadTemplates: async () => {
                    const response = await api.messaging.getTemplates()
                    return response.results
                },
                deleteTemplate: async (template: MessageTemplate) => {
                    await deleteWithUndo({
                        endpoint: `projects/${values.currentProjectId}/hog_functions`,
                        object: {
                            id: template.id,
                            name: template.name,
                        },
                        callback: (undo) => {
                            if (undo) {
                                actions.loadTemplates()
                            }
                        },
                    })
                    return values.templates.filter((t: MessageTemplate) => t.id !== template.id)
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadTemplates()
    }),
])
