import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { NEW_TEMPLATE } from './constants'
import type { messageTemplateLogicType } from './messageTemplateLogicType'
import { MessageTemplate } from './types'

export interface MessageTemplateLogicProps {
    id: string
    messageId?: string | null
}

export const messageTemplateLogic = kea<messageTemplateLogicType>([
    path(['products', 'workflows', 'frontend', 'messageTemplateLogic']),
    props({} as MessageTemplateLogicProps),
    key(({ id }) => id ?? 'new'),
    connect(() => ({
        values: [teamLogic, ['currentTeamIdStrict']],
    })),
    actions({
        setTemplate: (template: MessageTemplate) => ({ template }),
        setOriginalTemplate: (template: MessageTemplate) => ({ template }),
        duplicateTemplate: true,
        deleteTemplate: true,
    }),
    selectors({
        logicProps: [
            () => [(_, props: MessageTemplateLogicProps) => props],
            (props: MessageTemplateLogicProps): MessageTemplateLogicProps => props,
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
        submitTemplateFailure: () => {
            const errors = values.templateAllErrors
            if (errors?.content?.email?.subject) {
                lemonToast.error('Subject is required')
            }
        },
        saveTemplateSuccess: async ({ template }) => {
            lemonToast.success('Template saved')
            // Clear the unsaved-changes state before navigating so the beforeUnload guard
            // does not intercept the post-save redirect.
            actions.resetTemplate(template)
            actions.setOriginalTemplate(template)
            template.id && router.actions.replace(urls.workflowsLibraryTemplate(template.id))
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
            if (values.templateChanged) {
                lemonToast.error('Please save your changes before duplicating')
                return
            }
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
                endpoint: `environments/${values.currentTeamIdStrict}/messaging_templates`,
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
    beforeUnload(({ values, actions }) => ({
        // Guards both new and existing templates - a brand-new template only exists in form
        // state until "Create" is pressed, so leaving without saving would discard it entirely.
        enabled: (newLocation) => {
            if (!values.templateChanged) {
                return false
            }
            // Allow same-path changes (e.g. query params) through without warning.
            if (newLocation && newLocation.pathname === router.values.location.pathname) {
                return false
            }
            return true
        },
        message: 'Leave template?\nChanges you made will be discarded.',
        onConfirm: () => actions.resetTemplate(values.originalTemplate),
    })),
])
