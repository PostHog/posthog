import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { NEW_TEMPLATE } from './constants'
import type { messageTemplateLogicType } from './messageTemplateLogicType'
import { MessageTemplate } from './messageTemplatesLogic'

export interface MessageTemplateLogicProps {
    logicKey?: string
    id?: string | null
    messageId?: string | null
}

export const messageTemplateLogic = kea<messageTemplateLogicType>([
    path(['products', 'messaging', 'frontend', 'messageTemplateLogic']),
    key(({ id }) => id ?? 'unknown'),
    props({} as MessageTemplateLogicProps),
    actions({
        setTemplate: (template: MessageTemplate) => ({ template }),
        setOriginalTemplate: (template: MessageTemplate) => ({ template }),
    }),
    selectors({
        breadcrumbs: [
            () => [(_, props) => props],
            (props: MessageTemplateLogicProps): Breadcrumb[] => {
                const { id } = props

                if (!id) {
                    return []
                }

                return [
                    {
                        key: Scene.Messaging,
                        name: 'Messaging',
                        path: urls.messaging(),
                    },
                    {
                        key: [Scene.Messaging, 'library'],
                        name: 'Library',
                        path: urls.messaging('library'),
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
    listeners(({ actions }) => ({
        saveTemplateSuccess: async ({ template }) => {
            lemonToast.success('Template saved')
            template.id && router.actions.replace(urls.messagingLibraryTemplate(template.id))
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
