import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { DeepPartialMap, ValidationErrorType, forms } from 'kea-forms'
import { lazyLoaders, loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { CyclotronJobInputsValidation } from 'lib/components/CyclotronJob/CyclotronJobInputsValidation'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { publicWebhooksHostOrigin } from 'lib/utils/apiHost'
import { LiquidRenderer } from 'lib/utils/liquid'
import { sanitizeInputs } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { EmailTemplate } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { HogFunctionTemplateType } from '~/types'

import { HogFlowActionSchema, isFunctionAction, isTriggerFunction } from './hogflows/steps/types'
import { type HogFlow, type HogFlowAction, HogFlowActionValidationResult, type HogFlowEdge } from './hogflows/types'
import type { workflowLogicType } from './workflowLogicType'
import { workflowSceneLogic } from './workflowSceneLogic'

export interface WorkflowLogicProps {
    id?: string
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

function getTemplatingError(value: string, templating?: 'liquid' | 'hog'): string | undefined {
    if (templating === 'liquid' && typeof value === 'string') {
        try {
            LiquidRenderer.parse(value)
        } catch (e: any) {
            return `Liquid template error: ${e.message}`
        }
    }
}

export function sanitizeWorkflow(
    workflow: HogFlow,
    hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
): HogFlow {
    // Sanitize all function-like actions the same as we would a hog function
    workflow.actions.forEach((action) => {
        if (isFunctionAction(action) || isTriggerFunction(action)) {
            const inputs = action.config.inputs
            const template = hogFunctionTemplatesById[action.config.template_id]
            if (template) {
                action.config.inputs = sanitizeInputs({
                    inputs_schema: template.inputs_schema,
                    inputs: inputs,
                })
            }
        }
    })
    return workflow
}

export const workflowLogic = kea<workflowLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'workflowLogic']),
    props({ id: 'new' } as WorkflowLogicProps),
    key((props) => props.id || 'new'),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
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
        triggerManualWorkflow: (variables: Record<string, string>) => ({ variables }),
        discardChanges: true,
    }),
    loaders(({ props, values }) => ({
        originalWorkflow: [
            null as HogFlow | null,
            {
                loadWorkflow: async () => {
                    if (!props.id || props.id === 'new') {
                        return { ...NEW_WORKFLOW }
                    }

                    return api.hogFlows.getHogFlow(props.id)
                },
                saveWorkflow: async (updates: HogFlow) => {
                    updates = sanitizeWorkflow(updates, values.hogFunctionTemplatesById)

                    if (!props.id || props.id === 'new') {
                        return api.hogFlows.createHogFlow(updates)
                    }

                    return api.hogFlows.updateHogFlow(props.id, updates)
                },
            },
        ],
    })),
    lazyLoaders(() => ({
        hogFunctionTemplatesById: [
            {} as Record<string, HogFunctionTemplateType>,
            {
                loadHogFunctionTemplatesById: async () => {
                    const allTemplates = await api.hogFunctions.listTemplates({
                        types: ['destination', 'source_webhook'],
                    })

                    const allTemplatesById = allTemplates.results.reduce(
                        (acc, template) => {
                            acc[template.id] = template
                            return acc
                        },
                        {} as Record<string, HogFunctionTemplateType>
                    )

                    return allTemplatesById
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
                    actions: actions.some((action) => !(values.actionValidationErrorsById[action.id]?.valid ?? true))
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
    })),

    selectors({
        logicProps: [() => [(_, props) => props], (props): WorkflowLogicProps => props],
        workflowLoading: [(s) => [s.originalWorkflowLoading], (originalWorkflowLoading) => originalWorkflowLoading],
        edgesByActionId: [
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

        actionValidationErrorsById: [
            (s) => [s.workflow, s.hogFunctionTemplatesById],
            (workflow, hogFunctionTemplatesById): Record<string, HogFlowActionValidationResult | null> => {
                return workflow.actions.reduce(
                    (acc, action) => {
                        const result: HogFlowActionValidationResult = {
                            valid: true,
                            schema: null,
                            errors: {},
                        }
                        const schemaValidation = HogFlowActionSchema.safeParse(action)

                        if (!schemaValidation.success) {
                            result.valid = false
                            result.schema = schemaValidation.error
                        } else if (action.type === 'function_email') {
                            // special case for function_email which has nested email inputs, so basic hog input validation is not enough
                            // TODO: modify email/native_email input type to flatten email inputs so we don't need this special case
                            const emailValue = action.config.inputs?.email?.value as any | undefined
                            const emailTemplating = action.config.inputs?.email?.templating

                            const emailTemplateErrors: Partial<EmailTemplate> = {
                                html: !emailValue?.html
                                    ? 'HTML is required'
                                    : getTemplatingError(emailValue?.html, emailTemplating),
                                subject: !emailValue?.subject
                                    ? 'Subject is required'
                                    : getTemplatingError(emailValue?.subject, emailTemplating),
                                from: !emailValue?.from?.email
                                    ? 'From is required'
                                    : getTemplatingError(emailValue?.from?.email, emailTemplating),
                                to: !emailValue?.to?.email
                                    ? 'To is required'
                                    : getTemplatingError(emailValue?.to?.email, emailTemplating),
                            }

                            const combinedErrors = Object.values(emailTemplateErrors)
                                .filter((v) => !!v)
                                .join(', ')

                            if (combinedErrors) {
                                result.valid = false
                                result.errors = {
                                    email: combinedErrors,
                                }
                            }
                        } else if (isFunctionAction(action) || isTriggerFunction(action)) {
                            const template = hogFunctionTemplatesById[action.config.template_id]
                            if (!template) {
                                result.valid = false
                                result.errors = {
                                    // This is a special case for the template_id field which might need to go to a generic error message
                                    _template_id: 'Template not found',
                                }
                            } else {
                                const configValidation = CyclotronJobInputsValidation.validate(
                                    action.config.inputs,
                                    template.inputs_schema ?? []
                                )
                                result.valid = configValidation.valid
                                result.errors = configValidation.errors
                            }
                        } else if (action.type === 'trigger') {
                            // custom validation here that we can't easily express in the schema
                            if (action.config.type === 'event') {
                                if (!action.config.filters.events?.length && !action.config.filters.actions?.length) {
                                    result.valid = false
                                    result.errors = {
                                        filters: 'At least one event or action is required',
                                    }
                                }
                            }
                        }

                        acc[action.id] = result
                        return acc
                    },
                    {} as Record<string, HogFlowActionValidationResult>
                )
            },
        ],

        triggerAction: [
            (s) => [s.workflow],
            (workflow): TriggerAction | null => {
                return (workflow.actions.find((action) => action.type === 'trigger') as TriggerAction) ?? null
            },
        ],

        workflowSanitized: [
            (s) => [s.workflow, s.hogFunctionTemplatesById],
            (workflow, hogFunctionTemplatesById): HogFlow => {
                return sanitizeWorkflow(workflow, hogFunctionTemplatesById)
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
            const actionEdges = values.edgesByActionId[actionId] ?? []
            const newEdges = values.workflow.edges.filter((e) => !actionEdges.includes(e))

            actions.setWorkflowValues({ edges: [...newEdges, ...edges] })
        },
        triggerManualWorkflow: async ({ variables }) => {
            if (!values.workflow.id || values.workflow.id === 'new') {
                lemonToast.error('You need to save the workflow before triggering it manually.')
                return
            }

            const webhookUrl = publicWebhooksHostOrigin() + '/public/webhooks/' + values.workflow.id

            lemonToast.info('Triggering workflow...')

            try {
                await fetch(webhookUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        user_id: String(values.user?.id),
                        variables,
                    }),
                    credentials: 'omit',
                })
            } catch (e) {
                lemonToast.error('Error triggering workflow: ' + (e as Error).message)
                return
            }

            lemonToast.success('Workflow triggered', {
                button: {
                    label: 'View logs',
                    action: () => router.actions.push(urls.workflow(values.workflow.id!, 'logs')),
                },
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadWorkflow()
    }),
])
