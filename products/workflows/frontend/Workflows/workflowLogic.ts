import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { DeepPartialMap, ValidationErrorType, forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { publicWebhooksHostOrigin } from 'lib/utils/apiHost'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { deleteFromTree } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'

import { type HogFlow, type HogFlowAction, type HogFlowEdge } from './hogflows/types'
import {
    type TemplateFormDefaults,
    determineTemplateScope,
    getActionValidationErrors,
    getDefaultTemplateFormValues,
    loadHogFunctionTemplatesById,
    sanitizeWorkflowCore,
} from './workflowEditorUtils'
import type { workflowLogicType } from './workflowLogicType'
import { workflowSceneLogic } from './workflowSceneLogic'

export interface WorkflowLogicProps {
    id?: string
    templateId?: string
}

export const TRIGGER_NODE_ID = 'trigger_node'
export const EXIT_NODE_ID = 'exit_node'

export type TriggerAction = Extract<HogFlowAction, { type: 'trigger' }>

const NEW_WORKFLOW: HogFlow = {
    id: 'new',
    name: 'New workflow',
    actions: [
        {
            id: TRIGGER_NODE_ID,
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
            id: EXIT_NODE_ID,
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
            from: TRIGGER_NODE_ID,
            to: EXIT_NODE_ID,
            type: 'continue',
        },
    ],
    conversion: { window_minutes: 0, filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    team_id: -1,
    created_at: '',
    updated_at: '',
}

// Re-export for backwards compatibility
export function sanitizeWorkflow(workflow: HogFlow, hogFunctionTemplatesById: Record<string, any>): HogFlow {
    return sanitizeWorkflowCore(workflow, hogFunctionTemplatesById) as HogFlow
}

export const workflowLogic = kea<workflowLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'workflowLogic']),
    props({ id: 'new' } as WorkflowLogicProps),
    key((props) => props.id || 'new'),
    connect({
        values: [userLogic, ['user'], projectLogic, ['currentProjectId']],
    }),
    actions({
        partialSetWorkflowActionConfig: (actionId: string, config: Partial<HogFlowAction['config']>) => ({
            actionId,
            config,
        }),
        setWorkflowActionConfig: (actionId: string, config: HogFlowAction['config']) => ({ actionId, config }),
        setWorkflowAction: (actionId: string, action: HogFlowAction) => ({ actionId, action }),
        setWorkflowActionEdges: (actionId: string, edges: HogFlow['edges']) => ({ actionId, edges }),
        // NOTE: This is a wrapper for setWorkflowValues, to get around some weird typegen issues
        setWorkflowInfo: (workflow: Partial<HogFlow>) => ({ workflow }),
        saveWorkflowPartial: (workflow: Partial<HogFlow>) => ({ workflow }),
        triggerManualWorkflow: (variables: Record<string, any>, scheduledAt?: string) => ({
            variables,
            scheduledAt,
        }),
        triggerBatchWorkflow: (variables: Record<string, any>, scheduledAt?: string) => ({
            variables,
            scheduledAt,
        }),
        discardChanges: true,
        duplicate: true,
        deleteWorkflow: true,
        showSaveAsTemplateModal: true,
        hideSaveAsTemplateModal: true,
    }),
    loaders(({ props, values }) => ({
        originalWorkflow: [
            null as HogFlow | null,
            {
                loadWorkflow: async () => {
                    if (!props.id || props.id === 'new') {
                        if (props.templateId) {
                            const templateWorkflow = await api.hogFlowTemplates.getHogFlowTemplate(props.templateId)

                            const newWorkflow = {
                                ...templateWorkflow,
                                name: templateWorkflow.name,
                                status: 'draft' as const,
                                version: 1,
                            }
                            delete (newWorkflow as any).id
                            delete (newWorkflow as any).team_id
                            delete (newWorkflow as any).created_at
                            delete (newWorkflow as any).updated_at
                            delete (newWorkflow as any).created_by

                            return newWorkflow
                        }
                        return { ...NEW_WORKFLOW }
                    }

                    return api.hogFlows.getHogFlow(props.id)
                },
                saveWorkflow: async (updates: HogFlow) => {
                    updates = sanitizeWorkflowCore(updates, values.workflowHogFunctionTemplatesById) as HogFlow

                    if (!props.id || props.id === 'new') {
                        const result = await api.hogFlows.createHogFlow(updates)

                        if (props.templateId) {
                            posthog.capture('hog_flow_created_from_template', {
                                workflow_id: result.id,
                                template_id: props.templateId,
                            })
                        }
                        return result
                    }

                    return api.hogFlows.updateHogFlow(props.id, updates)
                },
            },
        ],
        workflowHogFunctionTemplatesById: [
            {} as Record<string, any>,
            {
                loadWorkflowHogFunctionTemplatesById: async () => {
                    return loadHogFunctionTemplatesById()
                },
            },
        ],
    })),
    forms(({ actions, values }) => ({
        workflow: {
            defaults: NEW_WORKFLOW,
            errors: ({ name, actions }) => {
                const errors = {
                    name: !name ? 'Name is required' : undefined,
                    actions: actions.some(
                        (action) => !(values.workflowActionValidationErrorsById[action.id]?.valid ?? true)
                    )
                        ? 'Some fields need work'
                        : undefined,
                } as DeepPartialMap<HogFlow, ValidationErrorType>

                return errors
            },
            submit: async (values) => {
                if (!values) {
                    return
                }

                actions.saveWorkflow(values)
            },
        },
        saveAsTemplateForm: {
            defaults: getDefaultTemplateFormValues(),
            errors: ({ name }: TemplateFormDefaults) => ({
                name: !name ? 'Name is required' : undefined,
            }),
            submit: async (formValues: TemplateFormDefaults) => {
                const workflow = values.workflow
                if (!workflow) {
                    return
                }

                const scope = determineTemplateScope(values.user?.is_staff, formValues.scope)

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
    selectors({
        logicProps: [() => [(_, props: WorkflowLogicProps) => props], (props): WorkflowLogicProps => props],
        workflowLoading: [(s) => [s.originalWorkflowLoading], (originalWorkflowLoading) => originalWorkflowLoading],
        workflowEdgesByActionId: [
            (s) => [s.workflow],
            (workflow): Record<string, HogFlowEdge[]> => {
                return workflow.edges.reduce(
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

        workflowActionValidationErrorsById: [
            (s) => [s.workflow, s.workflowHogFunctionTemplatesById],
            (workflow, workflowHogFunctionTemplatesById) => {
                return getActionValidationErrors(workflow, workflowHogFunctionTemplatesById)
            },
        ],

        workflowTriggerAction: [
            (s) => [s.workflow],
            (workflow): TriggerAction | null => {
                return (workflow.actions.find((action) => action.type === 'trigger') as TriggerAction) ?? null
            },
        ],

        workflowSanitized: [
            (s) => [s.workflow, s.workflowHogFunctionTemplatesById],
            (workflow, workflowHogFunctionTemplatesById): HogFlow => {
                // TODOdin: Can we improve type safety on this and avoid casting? (also check other uses of sanitizeWorkflowCore)
                // Consider just passing in and returning actions
                return sanitizeWorkflowCore(workflow, workflowHogFunctionTemplatesById) as HogFlow
            },
        ],
    }),
    reducers({
        saveAsTemplateModalVisible: [
            false,
            {
                showSaveAsTemplateModal: () => true,
                hideSaveAsTemplateModal: () => false,
                submitSaveAsTemplateFormSuccess: () => false,
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        saveWorkflowPartial: async ({ workflow }) => {
            actions.saveWorkflow({
                ...values.workflow,
                ...workflow,
            })
        },
        loadWorkflowSuccess: async ({ originalWorkflow }) => {
            actions.resetWorkflow(originalWorkflow)
        },
        saveWorkflowSuccess: async ({ originalWorkflow }) => {
            lemonToast.success('Workflow saved')
            if (props.id === 'new' && originalWorkflow.id) {
                router.actions.replace(
                    urls.workflow(
                        originalWorkflow.id,
                        workflowSceneLogic.findMounted()?.values.currentTab || 'workflow'
                    )
                )
            }

            actions.resetWorkflow(originalWorkflow)
        },
        discardChanges: () => {
            if (!values.originalWorkflow) {
                return
            }

            LemonDialog.open({
                title: 'Discard changes',
                description: 'Are you sure?',
                primaryButton: {
                    children: 'Discard',
                    onClick: () => actions.resetWorkflow(values.originalWorkflow ?? NEW_WORKFLOW),
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        },
        setWorkflowInfo: async ({ workflow }) => {
            actions.setWorkflowValues(workflow)
        },
        setWorkflowActionConfig: async ({ actionId, config }) => {
            const action = values.workflow.actions.find((action) => action.id === actionId)
            if (!action) {
                return
            }

            action.config = { ...config } as HogFlowAction['config']

            const changes = { actions: [...values.workflow.actions] } as Partial<HogFlow>
            if (action.type === 'trigger') {
                changes.trigger = action.config as TriggerAction['config']
            }

            actions.setWorkflowValues(changes)
        },
        partialSetWorkflowActionConfig: async ({ actionId, config }) => {
            const action = values.workflow.actions.find((action) => action.id === actionId)
            if (!action) {
                return
            }

            actions.setWorkflowActionConfig(actionId, { ...action.config, ...config } as HogFlowAction['config'])
        },
        setWorkflowAction: async ({ actionId, action }) => {
            const newActions = values.workflow.actions.map((a) => (a.id === actionId ? action : a))
            actions.setWorkflowValues({ actions: newActions })
        },
        setWorkflowActionEdges: async ({ actionId, edges }) => {
            // Helper method - Replaces all edges related to the action with the new edges
            const actionEdges = values.workflowEdgesByActionId[actionId] ?? []
            const newEdges = values.workflow.edges.filter((e) => !actionEdges.includes(e))

            actions.setWorkflowValues({ edges: [...newEdges, ...edges] })
        },
        duplicate: async () => {
            const workflow = values.originalWorkflow
            if (!workflow) {
                return
            }
            const newWorkflow = {
                ...workflow,
                name: `${workflow.name} (copy)`,
                status: 'draft' as const,
            }
            delete (newWorkflow as any).id
            delete (newWorkflow as any).team_id
            delete (newWorkflow as any).created_at
            delete (newWorkflow as any).updated_at

            const createdWorkflow = await api.hogFlows.createHogFlow(newWorkflow)
            lemonToast.success('Workflow duplicated')
            router.actions.push(urls.workflow(createdWorkflow.id, 'workflow'))
        },
        deleteWorkflow: async () => {
            const workflow = values.originalWorkflow
            if (!workflow) {
                return
            }
            LemonDialog.open({
                title: 'Delete workflow?',
                description: `Are you sure you want to delete "${workflow.name}"? This action cannot be undone.${
                    workflow.status === 'active' ? ' In-progress workflows will end immediately.' : ''
                }`,
                primaryButton: {
                    children: 'Delete',
                    type: 'primary',
                    status: 'danger',
                    onClick: async () => {
                        try {
                            await api.hogFlows.deleteHogFlow(workflow.id)
                            lemonToast.success(`Workflow "${workflow.name}" deleted`)
                            router.actions.push(urls.workflows())
                            deleteFromTree('hog_flow/', workflow.id)
                        } catch (error: any) {
                            lemonToast.error(
                                `Failed to delete workflow: ${error.detail || error.message || 'Unknown error'}`
                            )
                        }
                    },
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        },
        triggerManualWorkflow: async ({ variables }) => {
            if (!values.workflow.id || values.workflow.id === 'new') {
                lemonToast.error('You need to save the workflow before triggering it manually.')
                return
            }

            const webhookUrl = publicWebhooksHostOrigin() + '/public/webhooks/' + values.workflow.id

            const isScheduleTrigger = 'scheduled_at' in (values.workflow.trigger || {})
            lemonToast.info(isScheduleTrigger ? 'Scheduling workflow...' : 'Triggering workflow...')

            try {
                await fetch(webhookUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        user_id: values.user?.email,
                        $variables: variables,
                    }),
                    credentials: 'omit',
                })

                lemonToast.success(`Workflow ${isScheduleTrigger ? 'scheduled' : 'triggered'}`, {
                    button: {
                        label: 'View logs',
                        action: () => router.actions.push(urls.workflow(values.workflow.id!, 'logs')),
                    },
                })
            } catch (e) {
                lemonToast.error('Error triggering workflow: ' + (e as Error).message)
                return
            }
        },
        triggerBatchWorkflow: async ({ variables }) => {
            if (!values.workflow.id || values.workflow.id === 'new') {
                lemonToast.error('You need to save the workflow before triggering it manually.')
                return
            }

            const isScheduleTrigger = 'scheduled_at' in (values.workflow.trigger || {})
            lemonToast.info(isScheduleTrigger ? 'Scheduling batch workflow...' : 'Triggering batch workflow...')

            try {
                await api.hogFlows.createHogFlowBatchJob(values.workflow.id, {
                    variables,
                })
                lemonToast.success('Batch workflow job created')
                router.actions.push(urls.workflow(values.workflow.id!, 'logs'))
            } catch (e) {
                lemonToast.error('Error creating batch workflow job: ' + (e as Error).message)
                return
            }
        },
        showSaveAsTemplateModal: async () => {
            const workflow = values.workflow
            if (workflow) {
                actions.setSaveAsTemplateFormValues(
                    getDefaultTemplateFormValues(workflow.name || '', workflow.description || '', null)
                )
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadWorkflow()
        actions.loadWorkflowHogFunctionTemplatesById()
    }),
])
