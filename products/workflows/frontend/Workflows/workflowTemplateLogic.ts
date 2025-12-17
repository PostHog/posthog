import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

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
        values: [workflowLogic, ['workflow']],
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

                await api.hogFlowTemplates.createHogFlowTemplate({
                    ...workflow,
                    name: formValues.name || workflow.name || '',
                    description: formValues.description || workflow.description || '',
                    image_url: formValues.image_url || undefined,
                    scope: formValues.scope || 'team',
                })
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
