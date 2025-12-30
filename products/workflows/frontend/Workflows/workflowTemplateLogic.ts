import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { workflowLogic } from './workflowLogic'
import type { workflowTemplateLogicType } from './workflowTemplateLogicType'

export interface WorkflowTemplateLogicProps {
    id?: string
    templateId?: string
}

export const workflowTemplateLogic = kea<workflowTemplateLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'workflowTemplateLogic']),
    props({ id: 'new' } as WorkflowTemplateLogicProps),
    key((props) => props.id || 'new'),
    connect(() => ({
        values: [workflowLogic, ['workflow'], userLogic, ['user']],
    })),
    actions({
        showSaveAsTemplateModal: true,
        hideSaveAsTemplateModal: true,
        showUpdateTemplateModal: true,
        hideUpdateTemplateModal: true,
        setEditingTemplateId: (templateId: string | null) => ({ templateId }),
    }),
    forms(({ actions, values }) => ({
        templateForm: {
            defaults: {
                name: '',
                description: '',
                image_url: null as string | null,
                scope: 'team' as 'team' | 'global',
            },
            errors: ({ name }: { name: string }) => ({
                name: !name ? 'Name is required' : undefined,
            }),
            submit: async (formValues: {
                name: string
                description: string
                image_url: string | null
                scope: 'team' | 'global'
            }) => {
                const workflow = values.workflow
                if (!workflow) {
                    return
                }

                let scope: 'team' | 'global' = 'team'
                if (values.user?.is_staff) {
                    scope = formValues.scope ?? 'team'
                }

                try {
                    const templateId = values.editingTemplateId
                    
                    if (templateId) {
                        await api.hogFlowTemplates.updateHogFlowTemplate(templateId, {
                            ...workflow,
                            name: formValues.name || workflow.name || '',
                            description: formValues.description || workflow.description || '',
                            image_url: formValues.image_url || undefined,
                            scope,
                        })
                        lemonToast.success('Template updated successfully')
                        actions.hideUpdateTemplateModal()
                        router.actions.push(urls.workflows())
                    } else {
                        await api.hogFlowTemplates.createHogFlowTemplate({
                            ...workflow,
                            name: formValues.name || workflow.name || '',
                            description: formValues.description || workflow.description || '',
                            image_url: formValues.image_url || undefined,
                            scope,
                        })
                        lemonToast.success('Workflow template created')
                        actions.hideSaveAsTemplateModal()
                    }
                } catch (e: any) {
                    const errorMessage = e?.detail || e?.message || 'Failed to save workflow template'
                    lemonToast.error(errorMessage)
                    throw e
                }
            },
        },
    })),
    reducers({
        saveAsTemplateModalVisible: [
            false,
            {
                showSaveAsTemplateModal: () => true,
                hideSaveAsTemplateModal: () => false,
                submitTemplateFormSuccess: () => false,
            },
        ],
        updateTemplateModalVisible: [
            false,
            {
                showUpdateTemplateModal: () => true,
                hideUpdateTemplateModal: () => false,
                submitTemplateFormSuccess: () => false,
            },
        ],
        editingTemplateId: [
            null as string | null,
            {
                setEditingTemplateId: (_, { templateId }) => templateId,
                hideUpdateTemplateModal: () => null,
                hideSaveAsTemplateModal: () => null,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        showSaveAsTemplateModal: async () => {
            const workflow = values.workflow
            if (workflow) {
                actions.setTemplateFormValues({
                    name: workflow.name || '',
                    description: workflow.description || '',
                    image_url: null,
                    scope: 'team',
                })
            }
        },
        showUpdateTemplateModal: () => {
            // Form values are set in WorkflowTemplateScene
        },
    })),
])
