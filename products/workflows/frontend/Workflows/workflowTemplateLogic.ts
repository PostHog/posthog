import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { HogFunctionTemplateType } from '~/types'

import { isFunctionAction, isTriggerFunction } from './hogflows/steps/types'
import { type HogFlow, type HogFlowTemplate } from './hogflows/types'
import { workflowLogic } from './workflowLogic'
import type { workflowTemplateLogicType } from './workflowTemplateLogicType'

export interface WorkflowTemplateLogicProps {
    id?: string
    templateId?: string
}

function workflowToTemplate(
    workflow: HogFlow,
    hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
): Omit<HogFlowTemplate, 'created_by'> {
    const newTemplate = {
        ...workflow,
        name: `${workflow.name}`,
        actions: workflow.actions.map((action) => ({
            ...action,
            config: { ...action.config } as typeof action.config,
        })) as typeof workflow.actions,
    }
    delete (newTemplate as any).id
    delete (newTemplate as any).created_at
    delete (newTemplate as any).updated_at
    delete (newTemplate as any).status

    newTemplate.actions.forEach((action) => {
        if (isFunctionAction(action) || isTriggerFunction(action)) {
            const template = hogFunctionTemplatesById[action.config.template_id]
            if (template) {
                // Reset inputs to defaults from the template
                const defaultInputs: Record<string, { value: any }> = {}
                template.inputs_schema?.forEach((schema) => {
                    if (schema.default !== undefined) {
                        defaultInputs[schema.key] = { value: schema.default }
                    }
                })
                action.config = {
                    ...action.config,
                    inputs: defaultInputs,
                }
            }
        }
    })
    return newTemplate
}

export const workflowTemplateLogic = kea<workflowTemplateLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'workflowTemplateLogic']),
    props({ id: 'new' } as WorkflowTemplateLogicProps),
    key((props) => props.id || 'new'),
    connect(() => ({
        values: [workflowLogic, ['workflow', 'hogFunctionTemplatesById']],
    })),
    actions({
        showSaveAsTemplateModal: true,
        hideSaveAsTemplateModal: true,
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

                const template = workflowToTemplate(workflow, values.hogFunctionTemplatesById)
                template.name = formValues.name || workflow.name || ''
                template.description = formValues.description || workflow.description || ''
                template.image_url = formValues.image_url || undefined
                template.scope = formValues.scope || 'team'

                await api.hogFlowTemplates.createHogFlowTemplate(template)
                lemonToast.success('Workflow template created')
                actions.hideSaveAsTemplateModal()
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
        submitTemplateFormSuccess: async () => {
            actions.hideSaveAsTemplateModal()
        },
    })),
])
