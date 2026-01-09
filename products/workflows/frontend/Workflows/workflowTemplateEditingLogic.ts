import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { DeepPartialMap, ValidationErrorType, forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

import { type HogFlowAction, type HogFlowEdge, type HogFlowTemplate } from './hogflows/types'
import {
    type TemplateFormDefaults,
    type WorkflowCore,
    getActionValidationErrors,
    getDefaultTemplateFormValues,
    loadHogFunctionTemplatesById,
    sanitizeWorkflowCore,
} from './workflowEditorUtils'
import type { workflowTemplateEditingLogicType } from './workflowTemplateEditingLogicType'

export interface WorkflowTemplateEditorLogicProps {
    editTemplateId?: string
}

// Create a default template structure (similar to NEW_WORKFLOW but without status)
// TODOdin: remove this, we're only in the business of editing templates here, not creating them
const NEW_TEMPLATE: Omit<HogFlowTemplate, 'id' | 'team_id' | 'created_at' | 'updated_at' | 'created_by'> = {
    name: 'New template',
    actions: [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Trigger',
            description: 'User performs an action to start the workflow.',
            created_at: 0,
            updated_at: 0,
            config: {
                type: 'event',
                filters: {},
            },
        },
        {
            id: 'exit_node',
            type: 'exit',
            name: 'Exit',
            description: 'User moved through the workflow without errors.',
            config: {
                reason: 'Default exit',
            },
            created_at: 0,
            updated_at: 0,
        },
    ],
    edges: [
        {
            from: 'trigger_node',
            to: 'exit_node',
            type: 'continue',
        },
    ],
    conversion: { window_minutes: 0, filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    description: '',
    image_url: null,
    scope: 'team',
    variables: [],
}

export type TriggerAction = Extract<HogFlowAction, { type: 'trigger' }>

export const workflowTemplateEditingLogic = kea<workflowTemplateEditingLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'workflowTemplateEditingLogic']),
    props({} as WorkflowTemplateEditorLogicProps),
    key((props) => props.editTemplateId ?? 'disabled'),
    connect({
        values: [userLogic, ['user'], projectLogic, ['currentProjectId']],
    }),
    actions({
        partialSetTemplateActionConfig: (actionId: string, config: Partial<HogFlowAction['config']>) => ({
            actionId,
            config,
        }),
        setTemplateActionConfig: (actionId: string, config: HogFlowAction['config']) => ({ actionId, config }),
        setTemplateAction: (actionId: string, action: HogFlowAction) => ({ actionId, action }),
        setTemplateActionEdges: (actionId: string, edges: HogFlowTemplate['edges']) => ({ actionId, edges }),
        setTemplateInfo: (template: Partial<HogFlowTemplate>) => ({ template }),
        saveTemplatePartial: (workflow: Partial<HogFlowTemplate>) => ({ workflow }),
        discardChanges: true,
        showUpdateTemplateModal: true,
        hideUpdateTemplateModal: true,
        updateTemplate: (workflowTemplate: HogFlowTemplate) => ({ workflowTemplate }),
    }),
    loaders(({ props, values }) => ({
        originalTemplate: [
            null as HogFlowTemplate | null,
            {
                loadTemplate: async () => {
                    if (!props.editTemplateId) {
                        return null
                    }
                    const template = await api.hogFlowTemplates.getHogFlowTemplate(props.editTemplateId)
                    return template
                },
                saveTemplate: async (updates: HogFlowTemplate) => {
                    if (!props.editTemplateId) {
                        return updates
                    }
                    updates = sanitizeWorkflowCore(
                        updates as WorkflowCore,
                        values.templateHogFunctionTemplatesById
                    ) as HogFlowTemplate

                    return api.hogFlowTemplates.updateHogFlowTemplate(props.editTemplateId, updates)
                },
            },
        ],
        templateHogFunctionTemplatesById: [
            {} as Record<string, any>,
            {
                loadTemplateHogFunctionTemplatesById: async () => {
                    return loadHogFunctionTemplatesById()
                },
            },
        ],
    })),
    forms(({ actions, values, props }) => ({
        workflowTemplate: {
            defaults: NEW_TEMPLATE as HogFlowTemplate,
            errors: ({ name, actions }) => {
                const errors = {
                    name: !name ? 'Name is required' : undefined,
                    actions: actions.some(
                        (action) => !(values.templateActionValidationErrorsById[action.id]?.valid ?? true)
                    )
                        ? 'Some fields need work'
                        : undefined,
                } as DeepPartialMap<HogFlowTemplate, ValidationErrorType>

                return errors
            },
            submit: async (values) => {
                if (!values) {
                    return
                }

                actions.saveTemplate(values)
            },
        },
        updateTemplateForm: {
            defaults: getDefaultTemplateFormValues(),
            errors: ({ name }: TemplateFormDefaults) => ({
                name: !name ? 'Name is required' : undefined,
            }),
            submit: async (formValues: TemplateFormDefaults) => {
                const workflowTemplate = values.workflowTemplate
                const editTemplateId = props.editTemplateId
                if (!workflowTemplate || !editTemplateId) {
                    return
                }

                try {
                    const updatedWorkflow = {
                        ...workflowTemplate,
                        id: editTemplateId,
                        name: formValues.name || workflowTemplate.name || '',
                        description: formValues.description || workflowTemplate.description || '',
                        image_url: formValues.image_url || undefined,
                        scope: formValues.scope || undefined,
                    }

                    await actions.updateTemplate(updatedWorkflow)

                    actions.hideUpdateTemplateModal()
                } catch (e: any) {
                    const errorMessage = e?.detail || e?.message || 'Failed to update template'
                    lemonToast.error(errorMessage)
                    throw e
                }
            },
        },
    })),
    selectors({
        logicProps: [
            () => [(_, props: WorkflowTemplateEditorLogicProps) => props],
            (props): WorkflowTemplateEditorLogicProps => props,
        ],
        templateLoading: [(s) => [s.originalTemplateLoading], (originalTemplateLoading) => originalTemplateLoading],
        template: [(s) => [s.workflowTemplate], (workflowTemplate) => workflowTemplate as HogFlowTemplate],
        originalWorkflow: [(s) => [s.originalTemplate], (originalTemplate) => originalTemplate],
        workflowLoading: [(s) => [s.originalTemplateLoading], (originalTemplateLoading) => originalTemplateLoading],
        templateEdgesByActionId: [
            (s) => [s.workflowTemplate],
            (workflowTemplate): Record<string, HogFlowEdge[]> => {
                return workflowTemplate.edges.reduce(
                    (acc, edge) => {
                        if (!acc[edge.from]) {
                            acc[edge.from] = []
                        }
                        acc[edge.from].push(edge)

                        if (!acc[edge.to]) {
                            acc[edge.to] = []
                        }
                        acc[edge.to].push(edge)

                        return acc
                    },
                    {} as Record<string, HogFlowEdge[]>
                )
            },
        ],

        templateActionValidationErrorsById: [
            (s) => [s.workflowTemplate, s.templateHogFunctionTemplatesById],
            (workflowTemplate, templateHogFunctionTemplatesById) => {
                return getActionValidationErrors(workflowTemplate as WorkflowCore, templateHogFunctionTemplatesById)
            },
        ],

        templateTriggerAction: [
            (s) => [s.workflowTemplate],
            (workflowTemplate): TriggerAction | null => {
                return (workflowTemplate.actions.find((action) => action.type === 'trigger') as TriggerAction) ?? null
            },
        ],

        templateSanitized: [
            (s) => [s.workflowTemplate, s.templateHogFunctionTemplatesById],
            (workflowTemplate, templateHogFunctionTemplatesById): HogFlowTemplate => {
                return sanitizeWorkflowCore(
                    workflowTemplate as WorkflowCore,
                    templateHogFunctionTemplatesById
                ) as HogFlowTemplate
            },
        ],
    }),
    reducers({
        updateTemplateModalVisible: [
            false,
            {
                showUpdateTemplateModal: () => true,
                hideUpdateTemplateModal: () => false,
                submitUpdateTemplateFormSuccess: () => false,
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        saveTemplatePartial: async ({ workflow }) => {
            actions.saveTemplate({
                ...values.template,
                ...workflow,
            })
        },
        loadTemplateSuccess: async ({ originalTemplate }) => {
            actions.resetWorkflowTemplate(originalTemplate ?? undefined)
        },
        saveTemplateSuccess: async ({ originalTemplate }) => {
            lemonToast.success('Template saved')
            actions.resetWorkflowTemplate(originalTemplate)
        },
        discardChanges: () => {
            if (!values.originalTemplate) {
                return
            }

            LemonDialog.open({
                title: 'Discard changes',
                description: 'Are you sure?',
                primaryButton: {
                    children: 'Discard',
                    onClick: () =>
                        actions.resetWorkflowTemplate(values.originalTemplate ?? (NEW_TEMPLATE as HogFlowTemplate)),
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        },
        setTemplateInfo: async ({ template }) => {
            actions.setWorkflowTemplateValues(template)
        },
        setTemplateActionConfig: async ({ actionId, config }) => {
            const action = values.workflowTemplate.actions.find((action) => action.id === actionId)
            if (!action) {
                return
            }

            action.config = { ...config } as HogFlowAction['config']

            const changes = { actions: [...values.workflowTemplate.actions] } as Partial<HogFlowTemplate>
            if (action.type === 'trigger') {
                changes.trigger = action.config as TriggerAction['config']
            }

            actions.setWorkflowTemplateValues(changes)
        },
        partialSetTemplateActionConfig: async ({ actionId, config }) => {
            const action = values.workflowTemplate.actions.find((action) => action.id === actionId)
            if (!action) {
                return
            }

            actions.setTemplateActionConfig(actionId, { ...action.config, ...config } as HogFlowAction['config'])
        },
        setTemplateAction: async ({ actionId, action }) => {
            const newActions = values.workflowTemplate.actions.map((a) => (a.id === actionId ? action : a))
            actions.setWorkflowTemplateValues({ actions: newActions })
        },
        setTemplateActionEdges: async ({ actionId, edges }) => {
            // Helper method - Replaces all edges related to the action with the new edges
            const actionEdges = values.templateEdgesByActionId[actionId] ?? []
            const newEdges = values.workflowTemplate.edges.filter((e) => !actionEdges.includes(e))

            actions.setWorkflowTemplateValues({ edges: [...newEdges, ...edges] })
        },
        showUpdateTemplateModal: async () => {
            const workflowTemplate = values.workflowTemplate
            if (workflowTemplate && props.editTemplateId) {
                // Load template to get image_url and scope
                try {
                    const template = await api.hogFlowTemplates.getHogFlowTemplate(props.editTemplateId)
                    actions.setUpdateTemplateFormValues({
                        name: workflowTemplate.name,
                        description: workflowTemplate.description || '',
                        image_url: template.image_url || null,
                        scope: template.scope || 'team',
                    })
                } catch (e: any) {
                    const errorMessage = e?.detail || e?.message || 'Failed to load template'
                    lemonToast.error(errorMessage)
                    actions.hideUpdateTemplateModal()
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
            const { workflowTemplatesLogic } = await import('./workflowTemplatesLogic')
            const templatesLogic = workflowTemplatesLogic.findMounted()
            if (templatesLogic) {
                await templatesLogic.actions.loadWorkflowTemplates()
            }

            // Reload the template to reflect the updated template
            await actions.loadTemplate()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadTemplate()
        actions.loadTemplateHogFunctionTemplatesById()
    }),
])
