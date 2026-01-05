import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { userLogic } from 'scenes/userLogic'

import type { HogFlowTemplate } from './hogflows/types'
import { workflowLogic } from './workflowLogic'
import type { workflowTemplateLogicType } from './workflowTemplateLogicType'
import { workflowTemplatesLogic } from './workflowTemplatesLogic'

export interface WorkflowTemplateLogicProps {
    id?: string
    templateId?: string
    editTemplateId?: string
}

export const workflowTemplateLogic = kea<workflowTemplateLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'workflowTemplateLogic']),
    props({ id: 'new' } as WorkflowTemplateLogicProps),
    key((props) => `${props.id || 'new'}-${props.editTemplateId || ''}`),
    connect(() => ({
        values: [workflowLogic, ['workflow'], userLogic, ['user']],
        actions: [workflowTemplatesLogic, ['loadWorkflowTemplates']],
    })),
    actions({
        showSaveAsTemplateModal: true,
        hideSaveAsTemplateModal: true,
        updateTemplate: (workflowTemplate: HogFlowTemplate) => ({ workflowTemplate }),
    }),
    forms(({ actions, values, props }) => ({
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

                if (props.editTemplateId) {
                    try {
                        const updatedWorkflow = {
                            ...workflow,
                            id: props.editTemplateId,
                            name: formValues.name || workflow.name || '',
                            description: formValues.description || workflow.description || '',
                            image_url: formValues.image_url || undefined,
                            scope: formValues.scope || undefined,
                        }

                        await actions.updateTemplate(updatedWorkflow)

                        actions.hideSaveAsTemplateModal()
                    } catch (e: any) {
                        const errorMessage = e?.detail || e?.message || 'Failed to update template'
                        lemonToast.error(errorMessage)
                        throw e
                    }
                    return
                }

                // Otherwise, create a new template
                let scope: 'team' | 'global' = 'team'
                if (values.user?.is_staff) {
                    scope = formValues.scope ?? 'team'
                }

                try {
                    await api.hogFlowTemplates.createHogFlowTemplate({
                        ...workflow,
                        name: formValues.name || workflow.name || '',
                        description: formValues.description || workflow.description || '',
                        image_url: formValues.image_url || undefined,
                        scope,
                    })
                    lemonToast.success('Workflow template created')
                    actions.hideSaveAsTemplateModal()
                } catch (e: any) {
                    const errorMessage = e?.detail || e?.message || 'Failed to create workflow template'
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
    }),
    selectors({
        isEditMode: [
            () => [(_, props: WorkflowTemplateLogicProps) => props],
            (props: WorkflowTemplateLogicProps): boolean => !!props.editTemplateId,
        ],
        editTemplateId: [
            () => [(_, props: WorkflowTemplateLogicProps) => props],
            (props: WorkflowTemplateLogicProps): string | undefined => props.editTemplateId,
        ],
    }),
    listeners(({ actions, values, props }) => ({
        showSaveAsTemplateModal: async () => {
            const workflow = values.workflow
            if (workflow) {
                if (props.editTemplateId) {
                    // In edit mode, use workflow values for name/description, but load template for image_url and scope
                    try {
                        const template = await api.hogFlowTemplates.getHogFlowTemplate(props.editTemplateId)
                        actions.setTemplateFormValues({
                            name: workflow.name,
                            description: workflow.description || '', // Use current workflow description
                            image_url: template.image_url || null,
                            scope: template.scope || 'team',
                        })
                    } catch (e: any) {
                        const errorMessage = e?.detail || e?.message || 'Failed to load template'
                        lemonToast.error(errorMessage)
                        actions.hideSaveAsTemplateModal()
                        return
                    }
                } else {
                    actions.setTemplateFormValues({
                        name: workflow.name || '',
                        description: workflow.description || '',
                        image_url: null,
                        scope: 'team',
                    })
                }
            }
        },
        updateTemplate: async ({ workflowTemplate }) => {
            // Remove any undefined fields
            Object.keys(workflowTemplate).forEach((key) => {
                if (workflowTemplate[key as keyof typeof workflowTemplate] === undefined) {
                    delete workflowTemplate[key as keyof typeof workflowTemplate]
                }
            })

            await api.hogFlowTemplates.updateHogFlowTemplate(workflowTemplate.id, workflowTemplate)
            lemonToast.success('Template updated')

            // Update the template list in workflowTemplatesLogic
            const templatesLogic = workflowTemplatesLogic.findMounted()
            if (templatesLogic) {
                await templatesLogic.actions.loadWorkflowTemplates()
            }

            // Reload the workflow to reflect the updated template
            const workflowLogicInstance = workflowLogic.findMounted({
                id: props.id || 'new',
                editTemplateId: props.editTemplateId,
            })
            if (workflowLogicInstance) {
                await workflowLogicInstance.actions.loadWorkflow()
            }
        },
    })),
])
