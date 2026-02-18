import { actions, afterMount, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { DeepPartialMap, ValidationErrorType, forms } from 'kea-forms'
import { lazyLoaders, loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { CyclotronJobInputsValidation } from 'lib/components/CyclotronJob/CyclotronJobInputsValidation'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { publicWebhooksHostOrigin } from 'lib/utils/apiHost'
import { LiquidRenderer } from 'lib/utils/liquid'
import { sanitizeInputs } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { EmailTemplate } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { HogFunctionTemplateType } from '~/types'

import { HogFlowActionSchema, isFunctionAction, isTriggerFunction } from './hogflows/steps/types'
import { type HogFlow, type HogFlowAction, HogFlowActionValidationResult, type HogFlowEdge } from './hogflows/types'
import type { workflowLogicType } from './workflowLogicType'
import { workflowSceneLogic } from './workflowSceneLogic'
import { workflowsLogic } from './workflowsLogic'

export interface WorkflowLogicProps {
    id?: string
    tabId?: string
    templateId?: string
    editTemplateId?: string
}

export const TRIGGER_NODE_ID = 'trigger_node'
export const EXIT_NODE_ID = 'exit_node'

export type TriggerAction = Extract<HogFlowAction, { type: 'trigger' }>

export const NEW_WORKFLOW: HogFlow = {
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

// Fields added by the server during validation (not part of user edits)
const SERVER_ADDED_KEYS = new Set(['bytecode', 'order'])

function isEmptyValue(v: unknown): boolean {
    if (v === null || v === undefined || v === false || v === '') {
        return true
    }
    if (Array.isArray(v) && v.length === 0) {
        return true
    }
    return false
}

function normalizeForComparison(obj: unknown): unknown {
    if (Array.isArray(obj)) {
        return obj.map(normalizeForComparison)
    }
    if (obj !== null && typeof obj === 'object') {
        const sorted: Record<string, unknown> = {}
        for (const key of Object.keys(obj as Record<string, unknown>).sort()) {
            if (SERVER_ADDED_KEYS.has(key)) {
                continue
            }
            const val = (obj as Record<string, unknown>)[key]
            // Skip empty values that may be server defaults not present in frontend state
            if (isEmptyValue(val)) {
                continue
            }
            sorted[key] = normalizeForComparison(val)
        }
        return sorted
    }
    return obj
}

function configsEqual(a: unknown, b: unknown): boolean {
    return JSON.stringify(normalizeForComparison(a)) === JSON.stringify(normalizeForComparison(b))
}

export const workflowLogic = kea<workflowLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'workflowLogic']),
    props({ id: 'new', tabId: 'default' } as WorkflowLogicProps),
    key((props) => `workflow-${props.id || 'new'}-${props.tabId}`),
    connect(() => ({
        values: [userLogic, ['user'], projectLogic, ['currentProjectId']],
        actions: [workflowsLogic, ['archiveWorkflow']],
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
        saveMetadataField: (field: 'name' | 'description', value: string) => ({ field, value }),
        saveWorkflowPartial: (workflow: Partial<HogFlow>) => ({ workflow }),
        triggerManualWorkflow: (variables: Record<string, any>, scheduledAt?: string | null) => ({
            variables,
            scheduledAt,
        }),
        triggerBatchWorkflow: (
            variables: Record<string, any>,
            filters: Extract<HogFlowAction['config'], { type: 'batch' }>['filters'],
            scheduledAt?: string | null
        ) => ({
            variables,
            filters,
            scheduledAt,
        }),
        discardChanges: true,
        duplicate: true,
        saveDraftNow: true,
        publishWorkflow: true,
        discardDraft: true,
        metadataSaved: (updates: Partial<HogFlow>) => ({ updates }),
    }),
    loaders(({ props, values }) => ({
        originalWorkflow: [
            null as HogFlow | null,
            {
                loadWorkflow: async () => {
                    if (!props.id || props.id === 'new') {
                        if (props.editTemplateId) {
                            // Editing a template - load it and add a temporary status field for the editor
                            const templateWorkflow = await api.hogFlowTemplates.getHogFlowTemplate(props.editTemplateId)
                            return {
                                ...templateWorkflow,
                                status: 'draft' as const, // Temporary status for editor compatibility, won't be saved
                            } as HogFlow
                        }
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
                    updates = sanitizeWorkflow(updates, values.hogFunctionTemplatesById)

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
        draftSaveResult: [
            null as HogFlow | null,
            {
                saveDraftToServer: async () => {
                    if (!props.id || props.id === 'new') {
                        return null
                    }
                    const workflow = sanitizeWorkflow({ ...values.workflow }, values.hogFunctionTemplatesById)
                    const draftData: Partial<HogFlow> = {}
                    const draftFields: (keyof HogFlow)[] = [
                        'name',
                        'description',
                        'trigger_masking',
                        'conversion',
                        'exit_condition',
                        'edges',
                        'actions',
                        'variables',
                    ]
                    for (const field of draftFields) {
                        ;(draftData as any)[field] = workflow[field]
                    }
                    return api.hogFlows.saveDraft(props.id, draftData)
                },
            },
        ],
        publishResult: [
            null as HogFlow | null,
            {
                publishDraftToServer: async () => {
                    if (!props.id || props.id === 'new') {
                        return null
                    }
                    return api.hogFlows.publishDraft(props.id)
                },
            },
        ],
        discardDraftResult: [
            null as HogFlow | null,
            {
                discardDraftOnServer: async () => {
                    if (!props.id || props.id === 'new') {
                        return null
                    }
                    return api.hogFlows.discardDraft(props.id)
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
            errors: ({ name, actions, status }) => {
                const errors = {
                    name: !name ? 'Name is required' : undefined,
                    actions:
                        status === 'active' &&
                        actions.some((action) => !(values.actionValidationErrorsById[action.id]?.valid ?? true))
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
    reducers({
        originalWorkflow: {
            metadataSaved: (state: HogFlow | null, { updates }: { updates: Partial<HogFlow> }) =>
                state ? { ...state, ...updates } : state,
        },
        draftSavedAt: [
            null as string | null,
            {
                loadWorkflowSuccess: (_, { originalWorkflow }) => originalWorkflow?.draft_updated_at ?? null,
                saveDraftToServerSuccess: (_, { draftSaveResult }) => draftSaveResult?.draft_updated_at ?? null,
                publishDraftToServerSuccess: () => null,
                discardDraftOnServerSuccess: () => null,
            },
        ],
        hydratedFromDraft: [
            false,
            {
                loadWorkflowSuccess: (_, { originalWorkflow }) => !!originalWorkflow?.draft,
                saveWorkflowSuccess: () => false,
                publishDraftToServerSuccess: () => false,
                discardDraftOnServerSuccess: () => false,
            },
        ],
        draftExistsOnServer: [
            false,
            {
                loadWorkflowSuccess: (_, { originalWorkflow }) => !!originalWorkflow?.draft,
                saveDraftToServerSuccess: () => true,
                publishDraftToServerSuccess: () => false,
                discardDraftOnServerSuccess: () => false,
                saveWorkflowSuccess: () => false,
            },
        ],
    }),
    selectors({
        logicProps: [() => [(_, props: WorkflowLogicProps) => props], (props): WorkflowLogicProps => props],
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
            (s) => [s.workflow, s.hogFunctionTemplatesById, s.hogFunctionTemplatesByIdLoading],
            (
                workflow,
                hogFunctionTemplatesById,
                hogFunctionTemplatesByIdLoading
            ): Record<string, HogFlowActionValidationResult | null> => {
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
                                html:
                                    !emailValue?.html && !emailValue?.text
                                        ? 'HTML or plain text is required'
                                        : emailValue?.html
                                          ? getTemplatingError(emailValue?.html, emailTemplating)
                                          : undefined,
                                text: emailValue?.text
                                    ? getTemplatingError(emailValue?.text, emailTemplating)
                                    : undefined,
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
                        }

                        if (
                            (isFunctionAction(action) || isTriggerFunction(action)) &&
                            !hogFunctionTemplatesByIdLoading
                        ) {
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
                        }

                        if (action.type === 'trigger') {
                            // custom validation here that we can't easily express in the schema
                            if (action.config.type === 'event') {
                                if (!action.config.filters.events?.length && !action.config.filters.actions?.length) {
                                    result.valid = false
                                    result.errors = {
                                        filters: 'At least one event or action is required',
                                    }
                                }
                            } else if (action.config.type === 'schedule') {
                                if (!action.config.scheduled_at) {
                                    result.valid = false
                                    result.errors = {
                                        scheduled_at: 'A scheduled time is required',
                                    }
                                }
                            } else if (action.config.type === 'batch') {
                                if (!action.config.filters.properties?.length) {
                                    result.valid = false
                                    result.errors = {
                                        filters: 'At least one property filter is required for batch workflows',
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

        workflowHasActionErrors: [
            (s) => [s.workflow, s.actionValidationErrorsById],
            (
                workflow: HogFlow,
                actionValidationErrorsById: Record<string, HogFlowActionValidationResult | null>
            ): boolean => {
                return workflow.actions.some((action) => !(actionValidationErrorsById[action.id]?.valid ?? true))
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

        workflowContentChanged: [
            (s) => [s.workflow, s.originalWorkflow],
            (workflow, originalWorkflow): boolean => {
                if (!originalWorkflow) {
                    return false
                }
                const contentFields: (keyof HogFlow)[] = [
                    'trigger_masking',
                    'conversion',
                    'exit_condition',
                    'edges',
                    'actions',
                    'variables',
                ]
                return contentFields.some(
                    (field) =>
                        JSON.stringify(normalizeForComparison(workflow[field])) !==
                        JSON.stringify(normalizeForComparison(originalWorkflow[field]))
                )
            },
        ],

        hasPendingDraft: [(s) => [s.draftExistsOnServer], (draftExistsOnServer): boolean => draftExistsOnServer],

        isDraftSaving: [(s) => [s.draftSaveResultLoading], (loading): boolean => loading],

        isDraftPublishing: [(s) => [s.publishResultLoading], (loading): boolean => loading],

        canPublish: [
            (s) => [s.draftExistsOnServer, s.workflowHasActionErrors],
            (draftExistsOnServer, hasErrors): boolean => draftExistsOnServer && !hasErrors,
        ],

        draftChangedActionIds: [
            (s) => [s.workflow, s.originalWorkflow],
            (workflow, originalWorkflow): Set<string> => {
                if (!originalWorkflow || originalWorkflow.status !== 'active') {
                    return new Set()
                }
                const changed = new Set<string>()
                const liveActions = originalWorkflow.actions
                const liveActionsById = new Map(liveActions.map((a) => [a.id, a]))
                const currentActionsById = new Map(workflow.actions.map((a) => [a.id, a]))

                for (const action of workflow.actions) {
                    if (action.type === 'trigger' || action.type === 'exit') {
                        continue
                    }
                    const liveAction = liveActionsById.get(action.id)
                    if (!liveAction) {
                        changed.add(action.id)
                    } else if (!configsEqual(liveAction.config, action.config)) {
                        changed.add(action.id)
                    }
                }
                // Actions removed in draft
                for (const action of liveActions) {
                    if (action.type === 'trigger' || action.type === 'exit') {
                        continue
                    }
                    if (!currentActionsById.has(action.id)) {
                        changed.add(action.id)
                    }
                }
                return changed
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        saveWorkflowPartial: async ({ workflow }) => {
            const merged = { ...values.workflow, ...workflow }
            if (merged.status === 'active' && values.workflowHasActionErrors) {
                lemonToast.error('Fix all errors before enabling')
                return
            }
            actions.saveWorkflow(merged)
        },
        loadWorkflowSuccess: async ({ originalWorkflow }) => {
            if (originalWorkflow?.draft) {
                // Hydrate form with draft data, keeping identity fields from live record
                const hydrated = {
                    ...originalWorkflow,
                    ...originalWorkflow.draft,
                    id: originalWorkflow.id,
                    status: originalWorkflow.status,
                    version: originalWorkflow.version,
                    team_id: originalWorkflow.team_id,
                    created_at: originalWorkflow.created_at,
                    updated_at: originalWorkflow.updated_at,
                    created_by: originalWorkflow.created_by,
                    draft: originalWorkflow.draft,
                    draft_updated_at: originalWorkflow.draft_updated_at,
                }
                actions.resetWorkflow(hydrated)
            } else {
                actions.resetWorkflow(originalWorkflow)
            }
        },
        saveWorkflowSuccess: async ({ originalWorkflow }) => {
            const tasksToMarkAsCompleted: SetupTaskId[] = []
            lemonToast.success('Workflow saved')
            if (props.id === 'new' && originalWorkflow.id) {
                router.actions.replace(
                    urls.workflow(
                        originalWorkflow.id,
                        workflowSceneLogic.findMounted()?.values.currentTab || 'workflow'
                    )
                )
            }

            // Mark workflow creation task as completed everytime it's saved for completeness
            tasksToMarkAsCompleted.push(SetupTaskId.CreateFirstWorkflow)

            // Check trigger configuration
            const trigger = originalWorkflow.actions.find((a) => a.type === 'trigger')
            if (trigger) {
                const config = trigger.config as any
                const hasValidTrigger =
                    (config.type === 'event' &&
                        (config.filters?.events?.length > 0 || config.filters?.actions?.length > 0)) ||
                    (config.type === 'schedule' && config.scheduled_at) ||
                    (config.type === 'batch' && config.filters?.properties?.length > 0)
                if (hasValidTrigger) {
                    globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.ConfigureWorkflowTrigger)
                }
            }

            // Check if workflow has actions beyond trigger and exit
            const actionNodes = originalWorkflow.actions.filter((a) => a.type !== 'trigger' && a.type !== 'exit')
            if (actionNodes.length > 0) {
                tasksToMarkAsCompleted.push(SetupTaskId.AddWorkflowAction)
            }

            // Check if workflow is active (launched)
            if (originalWorkflow.status === 'active') {
                tasksToMarkAsCompleted.push(SetupTaskId.LaunchWorkflow)
            }

            // Make sure we submit all the tasks for completion at once in the end
            if (tasksToMarkAsCompleted.length > 0) {
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(tasksToMarkAsCompleted)
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
        triggerBatchWorkflow: async ({ variables, filters, scheduledAt }) => {
            if (!values.workflow.id || values.workflow.id === 'new') {
                lemonToast.error('You need to save the workflow before triggering it manually.')
                return
            }

            const isScheduleTrigger = 'scheduled_at' in (values.workflow.trigger || {})
            lemonToast.info(isScheduleTrigger ? 'Scheduling batch workflow...' : 'Triggering batch workflow...')

            try {
                await api.hogFlows.createHogFlowBatchJob(values.workflow.id, {
                    variables,
                    filters,
                    scheduled_at: scheduledAt,
                })
                lemonToast.success(`Batch workflow ${scheduledAt ? 'scheduled' : 'triggered'}`, {
                    button: {
                        label: 'View logs',
                        action: () => router.actions.push(urls.workflow(values.workflow.id!, 'logs')),
                    },
                })
            } catch (e) {
                lemonToast.error('Error creating batch workflow job: ' + (e as Error).message)
                return
            }
        },
        saveDraftNow: async () => {
            if (props.id === 'new' || !props.id) {
                // Auto-create workflow on server as draft
                if (!values.workflow.name) {
                    return
                }
                const toCreate = sanitizeWorkflow({ ...values.workflow }, values.hogFunctionTemplatesById)
                toCreate.status = 'draft'
                delete (toCreate as any).id
                delete (toCreate as any).team_id
                delete (toCreate as any).created_at
                delete (toCreate as any).updated_at
                try {
                    const created = await api.hogFlows.createHogFlow(toCreate)
                    lemonToast.success('Workflow auto-saved')
                    router.actions.replace(
                        urls.workflow(created.id, workflowSceneLogic.findMounted()?.values.currentTab || 'workflow')
                    )
                } catch (e) {
                    // Silently fail - user can still manually save
                    console.error('Auto-create workflow failed:', e)
                }
                return
            }
            if (values.workflowContentChanged) {
                if (values.workflow.status === 'active') {
                    actions.saveDraftToServer()
                } else {
                    // Draft-status workflows save directly - no live version to protect
                    actions.saveWorkflow(sanitizeWorkflow({ ...values.workflow }, values.hogFunctionTemplatesById))
                }
            }
        },
        saveDraftToServerSuccess: () => {
            lemonToast.success('Draft saved')
        },
        publishWorkflow: () => {
            actions.publishDraftToServer()
        },
        publishDraftToServerSuccess: () => {
            lemonToast.success('Workflow published')
            actions.loadWorkflow()
        },
        discardDraft: () => {
            LemonDialog.open({
                title: 'Discard changes',
                description: 'Are you sure you want to discard all changes? The live workflow will not be affected.',
                primaryButton: {
                    children: 'Discard',
                    onClick: () => {
                        if (values.draftExistsOnServer) {
                            actions.discardDraftOnServer()
                        } else {
                            actions.loadWorkflow()
                        }
                    },
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        },
        discardDraftOnServerSuccess: () => {
            lemonToast.success('Draft discarded')
            actions.loadWorkflow()
        },
        saveMetadataField: ({ field, value }) => {
            if (!props.id || props.id === 'new') {
                return
            }
            if ((window as any).__workflowMetadataTimer) {
                clearTimeout((window as any).__workflowMetadataTimer)
            }
            ;(window as any).__workflowMetadataTimer = setTimeout(async () => {
                try {
                    const updates = { [field]: value } as Partial<HogFlow>
                    await api.hogFlows.updateHogFlow(props.id!, updates)
                    actions.metadataSaved(updates)
                    lemonToast.success('Saved')
                } catch (e) {
                    console.error('Metadata save failed:', e)
                }
            }, 2000)
        },
        // Autosave: debounce 10s after changes
        setWorkflowValues: () => {
            if ((window as any).__workflowAutosaveTimer) {
                clearTimeout((window as any).__workflowAutosaveTimer)
            }
            ;(window as any).__workflowAutosaveTimer = setTimeout(() => {
                actions.saveDraftNow()
            }, 10000)
        },
    })),
    beforeUnmount(() => {
        if ((window as any).__workflowAutosaveTimer) {
            clearTimeout((window as any).__workflowAutosaveTimer)
            delete (window as any).__workflowAutosaveTimer
        }
        if ((window as any).__workflowMetadataTimer) {
            clearTimeout((window as any).__workflowMetadataTimer)
            delete (window as any).__workflowMetadataTimer
        }
    }),
    afterMount(({ actions }) => {
        actions.loadWorkflow()
        actions.loadHogFunctionTemplatesById()
    }),
])
