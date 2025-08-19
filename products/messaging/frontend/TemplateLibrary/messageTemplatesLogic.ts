import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { EmailTemplate } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import { UserBasicType } from '~/types'

import type { messageTemplatesLogicType } from './messageTemplatesLogicType'

export interface MessageTemplate {
    id: string
    name: string
    description: string
    content: {
        templating: 'liquid' | 'hog'
        email: EmailTemplate
    }
    created_at: string | null
    updated_at: string | null
    created_by: UserBasicType | null
}

export const messageTemplatesLogic = kea<messageTemplatesLogicType>([
    path(['products', 'messaging', 'frontend', 'library', 'messageTemplatesLogic']),
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
                        endpoint: `environments/@current/messaging_templates`,
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
                createTemplate: async ({ template }: { template: Partial<MessageTemplate> }) => {
                    try {
                        const newTemplate = await api.messaging.createTemplate(template)
                        lemonToast.success('Template created successfully')
                        return [...values.templates, newTemplate]
                    } catch {
                        lemonToast.error('Failed to create template')
                        return values.templates
                    }
                },
                updateTemplate: async ({
                    templateId,
                    template,
                }: {
                    templateId: string
                    template: Partial<MessageTemplate>
                }) => {
                    try {
                        const updatedTemplate = await api.messaging.updateTemplate(templateId, template)
                        lemonToast.success('Template updated successfully')
                        return values.templates.map((t: MessageTemplate) => (t.id === templateId ? updatedTemplate : t))
                    } catch {
                        lemonToast.error('Failed to update template')
                        return values.templates
                    }
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadTemplates()
    }),
])
