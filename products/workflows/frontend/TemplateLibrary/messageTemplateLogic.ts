import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'
import { Breadcrumb } from '~/types'

import { NEW_TEMPLATE } from './constants'
import type { messageTemplateLogicType } from './messageTemplateLogicType'
import { MessageTemplate } from './messageTemplatesLogic'

export interface MessageTemplateLogicProps {
    id: string
    messageId?: string | null
}

export const messageTemplateLogic = kea<messageTemplateLogicType>([
    path(['products', 'workflows', 'frontend', 'messageTemplateLogic']),
    key(({ id }) => id ?? 'unknown'),
    props({} as MessageTemplateLogicProps),
    actions({
        setTemplate: (template: MessageTemplate) => ({ template }),
        setOriginalTemplate: (template: MessageTemplate) => ({ template }),
        duplicateTemplate: true,
        deleteTemplate: true,
    }),
    selectors({
        breadcrumbs: [
            (_, p) => [p.id],
            (id): Breadcrumb[] => {
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
    forms(({ actions }) => ({
        template: {
            defaults: {
                ...NEW_TEMPLATE,
            },
            errors: (template: MessageTemplate) => ({
                name: !template.name ? 'Name is required' : undefined,
                content: {
                    email: {
                        subject: !template.content.email.subject ? 'Subject is required' : undefined,
                    },
                },
            }),
            submit: async (template) => {
                actions.saveTemplate(template)
            },
        },
    })),
    reducers({
        template: [
            { ...NEW_TEMPLATE } as MessageTemplate,
            {
                setTemplate: (_, { template }) => template,
            },
        ],
        originalTemplate: [
            { ...NEW_TEMPLATE } as MessageTemplate,
            {
                setOriginalTemplate: (_, { template }) => template,
                loadTemplateSuccess: (_, { template }) => {
                    return template
                },
            },
        ],
    }),
    loaders(({ props }) => ({
        template: {
            loadTemplate: async () => {
                if (!props.id || props.id === 'new') {
                    return {
                        ...NEW_TEMPLATE,
                    } as MessageTemplate
                }

                return await api.messaging.getTemplate(props.id)
            },
            saveTemplate: (template) => {
                if (template.id === 'new') {
                    return api.messaging.createTemplate(template)
                }
                return api.messaging.updateTemplate(template.id, template)
            },
        },
        message: {
            loadMessage: async () => {
                if (!props.messageId) {
                    return null
                }
                return await api.hogFunctions.get(props.messageId)
            },
        },
    })),
    listeners(({ actions, values }) => ({
        saveTemplateSuccess: async ({ template }) => {
            lemonToast.success('Template saved')
            template.id && router.actions.replace(urls.workflowsLibraryTemplate(template.id))
            actions.resetTemplate(template)
            actions.setOriginalTemplate(template)
        },
        loadMessageSuccess: async ({ message }) => {
            if (!message) {
                return
            }
            actions.setTemplateValues({
                name: message.name,
                description: message.description,
                content: {
                    email: message.inputs?.email?.value,
                },
            })
        },
        duplicateTemplate: async () => {
            const template = values.template
            try {
                const duplicatedTemplate = await api.messaging.createTemplate({
                    name: `${template.name} (copy)`,
                    description: template.description,
                    content: template.content,
                })
                lemonToast.success('Template duplicated successfully')
                router.actions.push(urls.workflowsLibraryTemplate(duplicatedTemplate.id))
            } catch {
                lemonToast.error('Failed to duplicate template')
            }
        },
        deleteTemplate: async () => {
            const template = values.template
            if (!template || template.id === 'new') {
                return
            }
            await deleteWithUndo({
                endpoint: `environments/@current/messaging_templates`,
                object: {
                    id: template.id,
                    name: template.name,
                },
                callback: (undo) => {
                    if (!undo) {
                        router.actions.push(urls.workflows('library'))
                    }
                },
            })
        },
    })),
    afterMount(({ props, actions }) => {
        if (props.id !== 'new') {
            actions.loadTemplate()
        }

        if (props.messageId) {
            actions.loadMessage()
        } else {
            // If we've previously loaded a message, reset the template to the default
            actions.resetTemplate(NEW_TEMPLATE)
        }
    }),
])
