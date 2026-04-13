import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { DeepPartialMap, ValidationErrorType, forms } from 'kea-forms'
import { lazyLoaders, loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { CyclotronJobInputsValidation } from 'lib/components/CyclotronJob/CyclotronJobInputsValidation'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { publicWebhooksHostOrigin } from 'lib/utils/apiHost'
import { LiquidRenderer } from 'lib/utils/liquid'
import { sanitizeInputs } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { EmailTemplate } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { HogFunctionTemplateType } from '~/types'

import { getRegisteredTriggerTypes } from './hogflows/registry/triggers/triggerTypeRegistry'
import {
    DEFAULT_STATE,
    isOneTimeSchedule,
    ONE_TIME_RRULE,
    parseRRuleToState,
    stateToRRule,
} from './hogflows/steps/components/rrule-helpers'
import type { ScheduleState } from './hogflows/steps/components/rrule-helpers'
import {
    HogFlowActionSchema,
    SCHEDULED_TRIGGER_TYPES,
    isFunctionAction,
    isTriggerFunction,
} from './hogflows/steps/types'
import {
    type HogFlow,
    type HogFlowAction,
    HogFlowActionValidationResult,
    type HogFlowEdge,
    type HogFlowSchedule,
} from './hogflows/types'
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
    conversion: { window_minutes: null, filters: [] },
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
    path((key) => ['products', 'workflows', 'frontend', 'Workflows', 'workflowLogic', key]),
    props({ id: 'new', tabId: 'default' } as WorkflowLogicProps),
    key(
        (props) =>
            `workflow-${props.id || 'new'}-${props.tabId || 'default'}-${props.templateId || 'default'}-${props.editTemplateId || 'default'}`
    ),
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
        setScheduleState: (scheduleState: ScheduleState, source: 'picker' | 'natural_language' = 'picker') => ({
            scheduleState,
            source,
        }),
        setScheduleStartsAt: (startsAt: string | null) => ({ startsAt }),
        setScheduleStartsAtFromPicker: (pickerDate: string | null) => ({ pickerDate }),
        setScheduleTimezone: (timezone: string, previousTimezone?: string) => ({ timezone, previousTimezone }),
        setScheduleRepeating: (repeating: boolean) => ({ repeating }),
        setSchedules: (schedules: HogFlowSchedule[]) => ({ schedules }),
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
        schedules: [
            [] as HogFlowSchedule[],
            {
                setSchedules: (_, { schedules }) => schedules,
            },
        ],
        scheduleState: [
            { ...DEFAULT_STATE } as ScheduleState,
            {
                setScheduleState: (_, { scheduleState }) => scheduleState,
                setSchedules: (_, { schedules }) => {
                    const schedule = schedules[0]
                    if (schedule && !isOneTimeSchedule(schedule.rrule)) {
                        return parseRRuleToState(schedule.rrule)
                    }
                    return { ...DEFAULT_STATE }
                },
            },
        ],
        scheduleStartsAt: [
            null as string | null,
            {
                setScheduleStartsAt: (_, { startsAt }) => startsAt,
                setSchedules: (_, { schedules }) => schedules[0]?.starts_at ?? null,
            },
        ],
        scheduleTimezone: [
            dayjs.tz.guess() as string,
            {
                setScheduleTimezone: (_, { timezone }) => timezone,
                setSchedules: (_, { schedules }) => schedules[0]?.timezone ?? dayjs.tz.guess(),
            },
        ],
        isScheduleRepeating: [
            false as boolean,
            {
                setScheduleRepeating: (_, { repeating }) => repeating,
                setSchedules: (_, { schedules }) => {
                    const schedule = schedules[0]
                    return !!schedule && !isOneTimeSchedule(schedule.rrule)
                },
            },
        ],
        // Tracks which configuration methods the user touched during the current editing
        // session, so we can attribute saved schedules to the natural language input vs picker.
        scheduleConfigSources: [
            { picker: false, natural_language: false } as { picker: boolean; natural_language: boolean },
            {
                setScheduleState: (state, { source }) => ({ ...state, [source]: true }),
                setSchedules: () => ({ picker: false, natural_language: false }),
            },
        ],
    }),
    selectors({
        logicProps: [() => [(_, props: WorkflowLogicProps) => props], (props): WorkflowLogicProps => props],
        currentSchedule: [(s) => [s.schedules], (schedules): HogFlowSchedule | null => schedules[0] ?? null],
        pendingSchedule: [
            (s) => [s.currentSchedule, s.scheduleState, s.scheduleStartsAt, s.scheduleTimezone, s.isScheduleRepeating],
            (
                currentSchedule,
                scheduleState,
                scheduleStartsAt,
                scheduleTimezone,
                isScheduleRepeating
            ): { rrule: string; starts_at: string; timezone?: string } | null | false => {
                // Build what the schedule would look like from current reducer state
                if (!scheduleStartsAt) {
                    // No start date set - if there was a saved schedule, this means delete it
                    return currentSchedule ? null : false
                }

                const rrule = isScheduleRepeating ? stateToRRule(scheduleState, scheduleStartsAt) : ONE_TIME_RRULE
                const newSchedule = { rrule, starts_at: scheduleStartsAt, timezone: scheduleTimezone }

                // Compare with saved schedule to detect changes
                if (!currentSchedule) {
                    // No saved schedule exists, so any non-null value is a pending change
                    return newSchedule
                }

                const savedRRule = currentSchedule.rrule
                const savedStartsAt = currentSchedule.starts_at
                const savedTimezone = currentSchedule.timezone ?? dayjs.tz.guess()

                if (rrule === savedRRule && scheduleStartsAt === savedStartsAt && scheduleTimezone === savedTimezone) {
                    return false // No changes
                }

                return newSchedule
            },
        ],
        hasUnsavedChanges: [
            (s) => [s.workflowChanged, s.pendingSchedule],
            (formChanged, pendingSchedule): boolean => formChanged || pendingSchedule !== false,
        ],
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
            (s) => [s.workflow, s.hogFunctionTemplatesById, s.hogFunctionTemplatesByIdLoading, s.scheduleStartsAt],
            (
                workflow,
                hogFunctionTemplatesById,
                hogFunctionTemplatesByIdLoading,
                scheduleStartsAt
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
                            const registeredTypes = getRegisteredTriggerTypes()
                            const matchingType = registeredTypes.find((t) => t.matchConfig?.(action.config))

                            if (matchingType?.validate) {
                                const triggerValidation = matchingType.validate(action.config)
                                if (triggerValidation && !triggerValidation.valid) {
                                    result.valid = false
                                    result.errors = { ...result.errors, ...triggerValidation.errors }
                                }
                            } else if (action.config.type === 'event') {
                                if (!action.config.filters?.events?.length && !action.config.filters?.actions?.length) {
                                    result.valid = false
                                    result.errors = {
                                        filters: 'At least one event or action is required',
                                    }
                                }
                            } else if (action.config.type === 'schedule') {
                                if (!scheduleStartsAt) {
                                    result.valid = false
                                    result.errors = {
                                        schedule: 'A start date is required for schedule triggers',
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
    }),
    listeners(({ actions, values, props }) => ({
        setScheduleStartsAtFromPicker: ({ pickerDate }) => {
            if (!pickerDate) {
                actions.setScheduleStartsAt(null)
                return
            }
            // The picker returns browser-local time. Reinterpret as the schedule timezone.
            const wallClock = dayjs(pickerDate).startOf('minute').format('YYYY-MM-DDTHH:mm:ss')
            actions.setScheduleStartsAt(dayjs.tz(wallClock, values.scheduleTimezone).toISOString())
        },
        setScheduleTimezone: ({ timezone, previousTimezone }) => {
            // When timezone changes, keep the wall-clock time the same by reinterpreting
            // the current starts_at in the new timezone.
            const oldTz = previousTimezone ?? dayjs.tz.guess()
            if (values.scheduleStartsAt) {
                const wallClock = dayjs(values.scheduleStartsAt).tz(oldTz).format('YYYY-MM-DDTHH:mm:ss')
                actions.setScheduleStartsAt(dayjs.tz(wallClock, timezone).toISOString())
            }
        },
        resetWorkflow: () => {
            // Re-initialize schedule reducers from the saved schedule.
            // Using setSchedules resets all reducers atomically without triggering
            // the setScheduleTimezone listener's wall-clock reinterpretation.
            actions.setSchedules(values.schedules)
        },
        saveWorkflowPartial: async ({ workflow }) => {
            const merged = { ...values.workflow, ...workflow }
            if (merged.status === 'active' && values.workflowHasActionErrors) {
                lemonToast.error('Fix all errors before enabling')
                return
            }
            actions.saveWorkflow(merged)
        },
        loadWorkflowSuccess: async ({ originalWorkflow }) => {
            actions.resetWorkflow(originalWorkflow)
            const triggerType = originalWorkflow.trigger?.type
            if (originalWorkflow.id && SCHEDULED_TRIGGER_TYPES.includes(triggerType ?? '')) {
                try {
                    const schedules = await api.hogFlows.getHogFlowSchedules(originalWorkflow.id)
                    actions.setSchedules(schedules)
                } catch {
                    // Schedules are non-critical, don't block workflow loading
                }
            }
        },
        saveWorkflowSuccess: async ({ originalWorkflow }) => {
            // Save pending schedule changes
            const workflowId = originalWorkflow.id
            const pendingSchedule = values.pendingSchedule
            const existingScheduleId = values.currentSchedule?.id
            const hasScheduleChanges = pendingSchedule !== false && !!workflowId

            if (hasScheduleChanges) {
                try {
                    if (pendingSchedule === null && existingScheduleId) {
                        await api.hogFlows.deleteHogFlowSchedule(workflowId, existingScheduleId)
                    } else if (pendingSchedule !== null && existingScheduleId) {
                        await api.hogFlows.updateHogFlowSchedule(workflowId, existingScheduleId, pendingSchedule)
                    } else if (pendingSchedule !== null) {
                        await api.hogFlows.createHogFlowSchedule(workflowId, pendingSchedule)
                    }

                    if (pendingSchedule !== null) {
                        posthog.capture('workflows schedule saved', {
                            workflow_id: workflowId,
                            configured_via_picker: values.scheduleConfigSources.picker,
                            configured_via_natural_language: values.scheduleConfigSources.natural_language,
                        })
                    }

                    const schedules = await api.hogFlows.getHogFlowSchedules(workflowId)
                    actions.setSchedules(schedules)
                } catch (e) {
                    console.error('Failed to save schedule', e)
                    lemonToast.error('Workflow saved, but schedule could not be updated')
                }
            }

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

            lemonToast.info('Triggering workflow...')

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

                lemonToast.success('Workflow triggered', {
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

            lemonToast.info('Triggering batch workflow...')

            try {
                await api.hogFlows.createHogFlowBatchJob(values.workflow.id, {
                    variables,
                    filters,
                    scheduled_at: scheduledAt,
                })
                lemonToast.success('Batch workflow triggered', {
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
    })),
    afterMount(({ actions }) => {
        actions.loadWorkflow()
        actions.loadHogFunctionTemplatesById()
    }),
])
