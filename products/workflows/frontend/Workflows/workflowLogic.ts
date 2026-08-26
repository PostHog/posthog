import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { DeepPartialMap, ValidationErrorType, forms } from 'kea-forms'
import type { DeepPartial, FieldName } from 'kea-forms'
import { lazyLoaders, loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'
import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import api, { ApiError } from 'lib/api'
import { CyclotronJobInputsValidation } from 'lib/components/CyclotronJob/CyclotronJobInputsValidation'
import { tryShowMCPHint } from 'lib/components/MCPHint/mcpHintLogic'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { publicWebhooksHostOrigin } from 'lib/utils/apiHost'
import { LiquidRenderer } from 'lib/utils/liquid'
import { objectsEqual } from 'lib/utils/objects'
import { sanitizeInputs } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import type { EmailFieldErrors } from 'scenes/hog-functions/email-templater/types'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AccessControlLevel, HogFunctionTemplateType } from '~/types'

import { resourceEditedLogic } from 'products/notifications/frontend/resourceEditedLogic'

import type { ResourceEditedEvent, UserBasicType, UserType } from '../../../../frontend/src/types'
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
import { openPublishConfirmDialog } from './PublishImpactDialog'
import { workflowSceneLogic } from './workflowSceneLogic'
import { workflowsLogic } from './workflowsLogic'

export interface WorkflowLogicProps {
    id?: string
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

// Step types that depend on person data and so cannot run for person-less (row-scoped)
// data-warehouse-table triggers. Module-scoped to avoid reallocating on every selector recompute.
export const PERSON_DEPENDENT_ACTION_TYPES = new Set(['wait_until_condition', 'random_cohort_branch'])

// Trigger types whose runs have no person attached: a synced warehouse row, a materialized view
// row, and a Slack poster are all things no PostHog person is attached to. Keep in sync with the
// backend's ROW_SCOPED_TRIGGER_TYPES, which is the authoritative check.
export const ROW_SCOPED_TRIGGER_TYPES = new Set(['data-warehouse-table', 'data-warehouse-view', 'slack-message'])

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

/**
 * The content the editor should show: the staged draft overlaid on the live row. The draft blob is
 * a full snapshot of the content fields, so the merge is a plain spread. The draft bookkeeping
 * fields stay off the form value: they are read-only server state, and a form that carried them
 * would leak them back into save payloads.
 */
export function withStagedDraft(workflow: HogFlow): HogFlow {
    if (!workflow.draft) {
        return workflow
    }
    const { draft, draft_updated_at, ...rest } = workflow
    return { ...rest, ...draft } as HogFlow
}

// Mirrors DRAFT_CONTENT_FIELDS in products/workflows/backend/api/hog_flow.py: the fields the draft
// cycle stages and publish promotes. Keep the two lists in sync.
const WORKFLOW_CONTENT_FIELDS = [
    'actions',
    'edges',
    'trigger',
    'trigger_masking',
    'conversion',
    'exit_condition',
    'email_sending_rate_limit',
    'abort_action',
    'variables',
] as const

// The fields the editor writes through the form. Edits that land while a save is in flight are
// re-applied from these after the response rebaselines the form, so the round-trip can't drop them.
const WORKFLOW_EDITABLE_FIELDS = [...WORKFLOW_CONTENT_FIELDS, 'name', 'description'] as const

function pickWorkflowEdits(workflow: HogFlow): Partial<HogFlow> {
    const result: Record<string, unknown> = {}
    for (const field of WORKFLOW_EDITABLE_FIELDS) {
        result[field] = workflow[field]
    }
    return result as Partial<HogFlow>
}

function omitWorkflowContent(workflow: HogFlow): Partial<HogFlow> {
    const result: Record<string, unknown> = { ...workflow }
    for (const field of WORKFLOW_CONTENT_FIELDS) {
        delete result[field]
    }
    return result as Partial<HogFlow>
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface workflowLogicValues {
    currentProjectId: number | null // projectLogic
    user: UserType | null // userLogic
    actionValidationErrorsById: Record<string, HogFlowActionValidationResult | null>
    autoSaveBlockedByValidation: boolean
    autoSaveEnabled: boolean
    currentSchedule: HogFlowSchedule | null
    deferredResourceEdited: ResourceEditedEvent | null
    draftActionPending: 'discard' | 'publish' | null
    edgesByActionId: Record<string, HogFlowEdge[]>
    externallyEdited: boolean
    hasStagedDraft: boolean
    hasUnsavedChanges: boolean
    hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
    hogFunctionTemplatesByIdLoading: boolean
    isAutoSave: boolean
    isAutoSavePending: boolean
    isRowScopedTrigger: boolean
    isScheduleRepeating: boolean
    isSyncingExternalEdit: boolean
    isWorkflowSubmitting: boolean
    isWorkflowValid: boolean
    lastSavedAt: string | null
    logicProps: WorkflowLogicProps
    originalWorkflow: HogFlow | null
    originalWorkflowLoading: boolean
    pendingSchedule:
        | {
              rrule: string
              starts_at: string
              timezone?: string
          }
        | false
        | null
    saveAttemptedActionIds: string[] | null
    saveBaseUpdatedAt: string | null
    scheduleConfigSources: {
        natural_language: boolean
        picker: boolean
    }
    scheduleStartsAt: string | null
    scheduleState: ScheduleState
    scheduleTimezone: string
    schedules: HogFlowSchedule[]
    showWorkflowErrors: boolean
    triggerAction: TriggerAction | null
    workflow: HogFlow
    workflowAllErrors: Record<string, any>
    workflowChanged: boolean
    workflowEditVersion: number
    workflowErrors: DeepPartialMap<HogFlow, ValidationErrorType>
    workflowHasActionErrors: boolean
    workflowHasErrors: boolean
    workflowLoading: boolean
    workflowManualErrors: Record<string, any>
    workflowSanitized: HogFlow
    workflowTouched: boolean
    workflowTouches: Record<string, boolean>
    workflowUserAccessLevel: AccessControlLevel | null
    workflowValidationErrors: DeepPartialMap<HogFlow, ValidationErrorType>
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface workflowLogicActions {
    resourceEdited: (event: ResourceEditedEvent) => {
        event: ResourceEditedEvent
    } // resourceEditedLogic
    archiveWorkflow: (workflow: HogFlow) => {
        workflow: HogFlow
    } // workflowsLogic
    autoSaveWorkflow: () => {
        value: true
    }
    clearAutoSavePending: () => {
        value: true
    }
    confirmDiscardDraft: () => {
        value: true
    }
    confirmPublishDraft: (confirmToken: string) => {
        confirmToken: string
    }
    discardChanges: () => {
        value: true
    }
    discardDraft: () => {
        value: true
    }
    duplicate: () => {
        value: true
    }
    keepMyWorkflowVersion: () => {
        value: true
    }
    loadHogFunctionTemplatesById: () => any
    loadHogFunctionTemplatesByIdFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadHogFunctionTemplatesByIdSuccess: (
        hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>,
        payload?: any
    ) => {
        hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
        payload?: any
    }
    loadWorkflow: () => any
    loadWorkflowFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadWorkflowSuccess: (
        originalWorkflow:
            | HogFlow
            | {
                  abort_action?: string | undefined
                  actions: (
                      | {
                            config: {
                                conditions: {
                                    filters: {
                                        actions?: any[] | undefined
                                        events?: any[] | undefined
                                        properties?: any[] | undefined
                                    }
                                    name?: string | undefined
                                }[]
                                delay_duration?: string | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'conditional_branch'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                delay_duration?: string | undefined
                                delay_until?:
                                    | {
                                          bytecode?: any
                                          bytecode_error?: string | undefined
                                          expression: string
                                          fallback_timezone?: string | null | undefined
                                          offset?: string | undefined
                                          timezone?: string | null | undefined
                                          use_person_timezone?: boolean | undefined
                                      }
                                    | undefined
                                max_delay_duration?: string | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'delay'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                reason?: string | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'exit'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                mappings?:
                                    | {
                                          disabled?: boolean | undefined
                                          filters?: any
                                          inputs?:
                                              | Record<
                                                    string,
                                                    {
                                                        bytecode?: any
                                                        order?: number | undefined
                                                        secret?: boolean | undefined
                                                        templating?: 'hog' | 'liquid' | undefined
                                                        value: any
                                                    }
                                                >
                                              | null
                                              | undefined
                                          inputs_schema?:
                                              | {
                                                    choices?:
                                                        | {
                                                              label: string
                                                              value: string
                                                          }[]
                                                        | undefined
                                                    default?: any
                                                    description?: string | undefined
                                                    hidden?: boolean | undefined
                                                    integration?: string | undefined
                                                    integration_field?: string | undefined
                                                    integration_key?: string | undefined
                                                    key: string
                                                    label: string
                                                    required?: boolean | undefined
                                                    requiredScopes?: string | undefined
                                                    requires_field?: string | undefined
                                                    secret?: boolean | undefined
                                                    templating?: boolean | undefined
                                                    type:
                                                        | 'boolean'
                                                        | 'choice'
                                                        | 'customer_analytics_account_properties'
                                                        | 'customer_analytics_account_relationships'
                                                        | 'dictionary'
                                                        | 'email'
                                                        | 'integration'
                                                        | 'integration_field'
                                                        | 'integration_multi'
                                                        | 'json'
                                                        | 'native_email'
                                                        | 'non_failure_status_codes'
                                                        | 'number'
                                                        | 'posthog_assignee'
                                                        | 'posthog_business_hours'
                                                        | 'posthog_ticket_tags'
                                                        | 'string'
                                                        | 'task_mcp_installations'
                                                        | 'task_model'
                                                        | 'task_repository'
                                                }[]
                                              | undefined
                                          name: string
                                      }[]
                                    | undefined
                                template_id: string
                                template_uuid?: string | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'function'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                message_category_id?: string | undefined
                                message_category_type?: 'marketing' | 'transactional' | undefined
                                template_id: 'template-email'
                                template_uuid?: string | undefined
                                tracking_enabled?: boolean | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'function_email'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                message_category_id?: string | undefined
                                message_category_type?: 'marketing' | 'transactional' | undefined
                                template_id: 'template-native-push'
                                template_uuid?: string | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'function_push'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                message_category_id?: string | undefined
                                message_category_type?: 'marketing' | 'transactional' | undefined
                                template_id: 'template-twilio'
                                template_uuid?: string | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'function_sms'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                cohorts: {
                                    name?: string | undefined
                                    percentage: number
                                }[]
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'random_cohort_branch'
                            updated_at?: number | undefined
                        }
                      | {
                            config:
                                | {
                                      type: 'schedule'
                                  }
                                | {
                                      filters: {
                                          all_roles_unassigned?: boolean | undefined
                                          assigned_to_user_ids?: number[] | undefined
                                          audience_type?: 'accounts' | 'persons' | undefined
                                          properties: any[]
                                          tag_names?: string[] | undefined
                                      }
                                      type: 'batch'
                                  }
                                | {
                                      filters: {
                                          actions?: any[] | undefined
                                          events?: any[] | undefined
                                          filter_test_accounts?: boolean | undefined
                                          properties?: any[] | undefined
                                      }
                                      type: 'event'
                                  }
                                | {
                                      filters: {
                                          properties?: any[] | undefined
                                      }
                                      type: 'slack-message'
                                  }
                                | {
                                      filters: {
                                          properties?: any[] | undefined
                                      }
                                      key_property?: string | undefined
                                      table_name: string
                                      type: 'data-warehouse-table'
                                  }
                                | {
                                      filters: {
                                          properties?: any[] | undefined
                                      }
                                      key_property?: string | undefined
                                      table_name: string
                                      type: 'data-warehouse-view'
                                  }
                                | {
                                      inputs: Record<
                                          string,
                                          {
                                              bytecode?: any
                                              order?: number | undefined
                                              secret?: boolean | undefined
                                              templating?: 'hog' | 'liquid' | undefined
                                              value: any
                                          }
                                      >
                                      template_id: string
                                      template_uuid?: string | undefined
                                      type: 'manual'
                                  }
                                | {
                                      inputs: Record<
                                          string,
                                          {
                                              bytecode?: any
                                              order?: number | undefined
                                              secret?: boolean | undefined
                                              templating?: 'hog' | 'liquid' | undefined
                                              value: any
                                          }
                                      >
                                      template_id: string
                                      template_uuid?: string | undefined
                                      type: 'tracking_pixel'
                                  }
                                | {
                                      inputs: Record<
                                          string,
                                          {
                                              bytecode?: any
                                              order?: number | undefined
                                              secret?: boolean | undefined
                                              templating?: 'hog' | 'liquid' | undefined
                                              value: any
                                          }
                                      >
                                      template_id: string
                                      template_uuid?: string | undefined
                                      type: 'webhook'
                                  }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'trigger'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                condition: {
                                    filters?:
                                        | {
                                              actions?: any[] | undefined
                                              events?: any[] | undefined
                                              properties?: any[] | undefined
                                          }
                                        | null
                                        | undefined
                                    name?: string | undefined
                                }
                                events?:
                                    | {
                                          filters?:
                                              | {
                                                    actions?: any[] | undefined
                                                    events?: any[] | undefined
                                                    properties?: any[] | undefined
                                                }
                                              | null
                                              | undefined
                                          name?: string | undefined
                                      }[]
                                    | undefined
                                max_wait_duration: string
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'wait_until_condition'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                day:
                                    | (
                                          | 'friday'
                                          | 'monday'
                                          | 'saturday'
                                          | 'sunday'
                                          | 'thursday'
                                          | 'tuesday'
                                          | 'wednesday'
                                      )[]
                                    | 'any'
                                    | 'weekday'
                                    | 'weekend'
                                fallback_timezone?: string | null | undefined
                                time: [string, string] | 'any'
                                timezone: string | null
                                use_person_timezone?: boolean | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'wait_until_time_window'
                            updated_at?: number | undefined
                        }
                  )[]
                  conversion?:
                      | {
                            bytecode?: (number | string)[] | undefined
                            events?:
                                | {
                                      filters?: any
                                      name?: string | undefined
                                  }[]
                                | undefined
                            filters: any
                            window_minutes: number | null
                        }
                      | undefined
                  created_at: string
                  created_by?: UserBasicType | null | undefined
                  description?: string | undefined
                  edges: {
                      from: string
                      index?: number | undefined
                      to: string
                      type: 'branch' | 'continue'
                  }[]
                  email_sending_rate_limit?:
                      | {
                            count: number
                            period: 'hour' | 'minute'
                        }
                      | null
                      | undefined
                  exit_condition:
                      | 'exit_on_conversion'
                      | 'exit_on_trigger_not_matched'
                      | 'exit_on_trigger_not_matched_or_conversion'
                      | 'exit_only_at_end'
                  id: string
                  image_url?: string | null | undefined
                  name: string
                  scope?: 'global' | 'organization' | 'team' | null | undefined
                  status: 'draft'
                  tags: string[]
                  team_id: number
                  trigger?:
                      | {
                            type: 'schedule'
                        }
                      | {
                            filters: {
                                all_roles_unassigned?: boolean | undefined
                                assigned_to_user_ids?: number[] | undefined
                                audience_type?: 'accounts' | 'persons' | undefined
                                properties: any[]
                                tag_names?: string[] | undefined
                            }
                            type: 'batch'
                        }
                      | {
                            filters: {
                                actions?: any[] | undefined
                                events?: any[] | undefined
                                filter_test_accounts?: boolean | undefined
                                properties?: any[] | undefined
                            }
                            type: 'event'
                        }
                      | {
                            filters: {
                                properties?: any[] | undefined
                            }
                            type: 'slack-message'
                        }
                      | {
                            filters: {
                                properties?: any[] | undefined
                            }
                            key_property?: string | undefined
                            table_name: string
                            type: 'data-warehouse-table'
                        }
                      | {
                            filters: {
                                properties?: any[] | undefined
                            }
                            key_property?: string | undefined
                            table_name: string
                            type: 'data-warehouse-view'
                        }
                      | {
                            inputs: Record<
                                string,
                                {
                                    bytecode?: any
                                    order?: number | undefined
                                    secret?: boolean | undefined
                                    templating?: 'hog' | 'liquid' | undefined
                                    value: any
                                }
                            >
                            template_id: string
                            template_uuid?: string | undefined
                            type: 'manual'
                        }
                      | {
                            inputs: Record<
                                string,
                                {
                                    bytecode?: any
                                    order?: number | undefined
                                    secret?: boolean | undefined
                                    templating?: 'hog' | 'liquid' | undefined
                                    value: any
                                }
                            >
                            template_id: string
                            template_uuid?: string | undefined
                            type: 'tracking_pixel'
                        }
                      | {
                            inputs: Record<
                                string,
                                {
                                    bytecode?: any
                                    order?: number | undefined
                                    secret?: boolean | undefined
                                    templating?: 'hog' | 'liquid' | undefined
                                    value: any
                                }
                            >
                            template_id: string
                            template_uuid?: string | undefined
                            type: 'webhook'
                        }
                      | undefined
                  trigger_masking?:
                      | {
                            bytecode: (number | string)[]
                            hash: string
                            threshold: number | null
                            ttl: number | null
                        }
                      | null
                      | undefined
                  updated_at: string
                  variables?:
                      | {
                            choices?:
                                | {
                                      label: string
                                      value: string
                                  }[]
                                | undefined
                            default?: any
                            description?: string | undefined
                            hidden?: boolean | undefined
                            integration?: string | undefined
                            integration_field?: string | undefined
                            integration_key?: string | undefined
                            key: string
                            label: string
                            required?: boolean | undefined
                            requiredScopes?: string | undefined
                            requires_field?: string | undefined
                            secret?: boolean | undefined
                            templating?: boolean | undefined
                            type:
                                | 'boolean'
                                | 'choice'
                                | 'customer_analytics_account_properties'
                                | 'customer_analytics_account_relationships'
                                | 'dictionary'
                                | 'email'
                                | 'integration'
                                | 'integration_field'
                                | 'integration_multi'
                                | 'json'
                                | 'native_email'
                                | 'non_failure_status_codes'
                                | 'number'
                                | 'posthog_assignee'
                                | 'posthog_business_hours'
                                | 'posthog_ticket_tags'
                                | 'string'
                                | 'task_mcp_installations'
                                | 'task_model'
                                | 'task_repository'
                        }[]
                      | null
                      | undefined
                  version: number
              },
        payload?: any
    ) => {
        originalWorkflow:
            | HogFlow
            | {
                  abort_action?: string | undefined
                  actions: (
                      | {
                            config: {
                                conditions: {
                                    filters: {
                                        actions?: any[] | undefined
                                        events?: any[] | undefined
                                        properties?: any[] | undefined
                                    }
                                    name?: string | undefined
                                }[]
                                delay_duration?: string | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'conditional_branch'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                delay_duration?: string | undefined
                                delay_until?:
                                    | {
                                          bytecode?: any
                                          bytecode_error?: string | undefined
                                          expression: string
                                          fallback_timezone?: string | null | undefined
                                          offset?: string | undefined
                                          timezone?: string | null | undefined
                                          use_person_timezone?: boolean | undefined
                                      }
                                    | undefined
                                max_delay_duration?: string | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'delay'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                reason?: string | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'exit'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                mappings?:
                                    | {
                                          disabled?: boolean | undefined
                                          filters?: any
                                          inputs?:
                                              | Record<
                                                    string,
                                                    {
                                                        bytecode?: any
                                                        order?: number | undefined
                                                        secret?: boolean | undefined
                                                        templating?: 'hog' | 'liquid' | undefined
                                                        value: any
                                                    }
                                                >
                                              | null
                                              | undefined
                                          inputs_schema?:
                                              | {
                                                    choices?:
                                                        | {
                                                              label: string
                                                              value: string
                                                          }[]
                                                        | undefined
                                                    default?: any
                                                    description?: string | undefined
                                                    hidden?: boolean | undefined
                                                    integration?: string | undefined
                                                    integration_field?: string | undefined
                                                    integration_key?: string | undefined
                                                    key: string
                                                    label: string
                                                    required?: boolean | undefined
                                                    requiredScopes?: string | undefined
                                                    requires_field?: string | undefined
                                                    secret?: boolean | undefined
                                                    templating?: boolean | undefined
                                                    type:
                                                        | 'boolean'
                                                        | 'choice'
                                                        | 'customer_analytics_account_properties'
                                                        | 'customer_analytics_account_relationships'
                                                        | 'dictionary'
                                                        | 'email'
                                                        | 'integration'
                                                        | 'integration_field'
                                                        | 'integration_multi'
                                                        | 'json'
                                                        | 'native_email'
                                                        | 'non_failure_status_codes'
                                                        | 'number'
                                                        | 'posthog_assignee'
                                                        | 'posthog_business_hours'
                                                        | 'posthog_ticket_tags'
                                                        | 'string'
                                                        | 'task_mcp_installations'
                                                        | 'task_model'
                                                        | 'task_repository'
                                                }[]
                                              | undefined
                                          name: string
                                      }[]
                                    | undefined
                                template_id: string
                                template_uuid?: string | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'function'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                message_category_id?: string | undefined
                                message_category_type?: 'marketing' | 'transactional' | undefined
                                template_id: 'template-email'
                                template_uuid?: string | undefined
                                tracking_enabled?: boolean | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'function_email'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                message_category_id?: string | undefined
                                message_category_type?: 'marketing' | 'transactional' | undefined
                                template_id: 'template-native-push'
                                template_uuid?: string | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'function_push'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                message_category_id?: string | undefined
                                message_category_type?: 'marketing' | 'transactional' | undefined
                                template_id: 'template-twilio'
                                template_uuid?: string | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'function_sms'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                cohorts: {
                                    name?: string | undefined
                                    percentage: number
                                }[]
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'random_cohort_branch'
                            updated_at?: number | undefined
                        }
                      | {
                            config:
                                | {
                                      type: 'schedule'
                                  }
                                | {
                                      filters: {
                                          all_roles_unassigned?: boolean | undefined
                                          assigned_to_user_ids?: number[] | undefined
                                          audience_type?: 'accounts' | 'persons' | undefined
                                          properties: any[]
                                          tag_names?: string[] | undefined
                                      }
                                      type: 'batch'
                                  }
                                | {
                                      filters: {
                                          actions?: any[] | undefined
                                          events?: any[] | undefined
                                          filter_test_accounts?: boolean | undefined
                                          properties?: any[] | undefined
                                      }
                                      type: 'event'
                                  }
                                | {
                                      filters: {
                                          properties?: any[] | undefined
                                      }
                                      type: 'slack-message'
                                  }
                                | {
                                      filters: {
                                          properties?: any[] | undefined
                                      }
                                      key_property?: string | undefined
                                      table_name: string
                                      type: 'data-warehouse-table'
                                  }
                                | {
                                      filters: {
                                          properties?: any[] | undefined
                                      }
                                      key_property?: string | undefined
                                      table_name: string
                                      type: 'data-warehouse-view'
                                  }
                                | {
                                      inputs: Record<
                                          string,
                                          {
                                              bytecode?: any
                                              order?: number | undefined
                                              secret?: boolean | undefined
                                              templating?: 'hog' | 'liquid' | undefined
                                              value: any
                                          }
                                      >
                                      template_id: string
                                      template_uuid?: string | undefined
                                      type: 'manual'
                                  }
                                | {
                                      inputs: Record<
                                          string,
                                          {
                                              bytecode?: any
                                              order?: number | undefined
                                              secret?: boolean | undefined
                                              templating?: 'hog' | 'liquid' | undefined
                                              value: any
                                          }
                                      >
                                      template_id: string
                                      template_uuid?: string | undefined
                                      type: 'tracking_pixel'
                                  }
                                | {
                                      inputs: Record<
                                          string,
                                          {
                                              bytecode?: any
                                              order?: number | undefined
                                              secret?: boolean | undefined
                                              templating?: 'hog' | 'liquid' | undefined
                                              value: any
                                          }
                                      >
                                      template_id: string
                                      template_uuid?: string | undefined
                                      type: 'webhook'
                                  }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'trigger'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                condition: {
                                    filters?:
                                        | {
                                              actions?: any[] | undefined
                                              events?: any[] | undefined
                                              properties?: any[] | undefined
                                          }
                                        | null
                                        | undefined
                                    name?: string | undefined
                                }
                                events?:
                                    | {
                                          filters?:
                                              | {
                                                    actions?: any[] | undefined
                                                    events?: any[] | undefined
                                                    properties?: any[] | undefined
                                                }
                                              | null
                                              | undefined
                                          name?: string | undefined
                                      }[]
                                    | undefined
                                max_wait_duration: string
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'wait_until_condition'
                            updated_at?: number | undefined
                        }
                      | {
                            config: {
                                day:
                                    | (
                                          | 'friday'
                                          | 'monday'
                                          | 'saturday'
                                          | 'sunday'
                                          | 'thursday'
                                          | 'tuesday'
                                          | 'wednesday'
                                      )[]
                                    | 'any'
                                    | 'weekday'
                                    | 'weekend'
                                fallback_timezone?: string | null | undefined
                                time: [string, string] | 'any'
                                timezone: string | null
                                use_person_timezone?: boolean | undefined
                            }
                            created_at?: number | undefined
                            description: string
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            id: string
                            name: string
                            on_error?: 'abort' | 'continue' | null | undefined
                            output_variable?:
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }
                                | {
                                      key: string
                                      label?: string | null | undefined
                                      result_path?: string | null | undefined
                                      spread?: boolean | null | undefined
                                  }[]
                                | null
                                | undefined
                            type: 'wait_until_time_window'
                            updated_at?: number | undefined
                        }
                  )[]
                  conversion?:
                      | {
                            bytecode?: (number | string)[] | undefined
                            events?:
                                | {
                                      filters?: any
                                      name?: string | undefined
                                  }[]
                                | undefined
                            filters: any
                            window_minutes: number | null
                        }
                      | undefined
                  created_at: string
                  created_by?: UserBasicType | null | undefined
                  description?: string | undefined
                  edges: {
                      from: string
                      index?: number | undefined
                      to: string
                      type: 'branch' | 'continue'
                  }[]
                  email_sending_rate_limit?:
                      | {
                            count: number
                            period: 'hour' | 'minute'
                        }
                      | null
                      | undefined
                  exit_condition:
                      | 'exit_on_conversion'
                      | 'exit_on_trigger_not_matched'
                      | 'exit_on_trigger_not_matched_or_conversion'
                      | 'exit_only_at_end'
                  id: string
                  image_url?: string | null | undefined
                  name: string
                  scope?: 'global' | 'organization' | 'team' | null | undefined
                  status: 'draft'
                  tags: string[]
                  team_id: number
                  trigger?:
                      | {
                            type: 'schedule'
                        }
                      | {
                            filters: {
                                all_roles_unassigned?: boolean | undefined
                                assigned_to_user_ids?: number[] | undefined
                                audience_type?: 'accounts' | 'persons' | undefined
                                properties: any[]
                                tag_names?: string[] | undefined
                            }
                            type: 'batch'
                        }
                      | {
                            filters: {
                                actions?: any[] | undefined
                                events?: any[] | undefined
                                filter_test_accounts?: boolean | undefined
                                properties?: any[] | undefined
                            }
                            type: 'event'
                        }
                      | {
                            filters: {
                                properties?: any[] | undefined
                            }
                            type: 'slack-message'
                        }
                      | {
                            filters: {
                                properties?: any[] | undefined
                            }
                            key_property?: string | undefined
                            table_name: string
                            type: 'data-warehouse-table'
                        }
                      | {
                            filters: {
                                properties?: any[] | undefined
                            }
                            key_property?: string | undefined
                            table_name: string
                            type: 'data-warehouse-view'
                        }
                      | {
                            inputs: Record<
                                string,
                                {
                                    bytecode?: any
                                    order?: number | undefined
                                    secret?: boolean | undefined
                                    templating?: 'hog' | 'liquid' | undefined
                                    value: any
                                }
                            >
                            template_id: string
                            template_uuid?: string | undefined
                            type: 'manual'
                        }
                      | {
                            inputs: Record<
                                string,
                                {
                                    bytecode?: any
                                    order?: number | undefined
                                    secret?: boolean | undefined
                                    templating?: 'hog' | 'liquid' | undefined
                                    value: any
                                }
                            >
                            template_id: string
                            template_uuid?: string | undefined
                            type: 'tracking_pixel'
                        }
                      | {
                            inputs: Record<
                                string,
                                {
                                    bytecode?: any
                                    order?: number | undefined
                                    secret?: boolean | undefined
                                    templating?: 'hog' | 'liquid' | undefined
                                    value: any
                                }
                            >
                            template_id: string
                            template_uuid?: string | undefined
                            type: 'webhook'
                        }
                      | undefined
                  trigger_masking?:
                      | {
                            bytecode: (number | string)[]
                            hash: string
                            threshold: number | null
                            ttl: number | null
                        }
                      | null
                      | undefined
                  updated_at: string
                  variables?:
                      | {
                            choices?:
                                | {
                                      label: string
                                      value: string
                                  }[]
                                | undefined
                            default?: any
                            description?: string | undefined
                            hidden?: boolean | undefined
                            integration?: string | undefined
                            integration_field?: string | undefined
                            integration_key?: string | undefined
                            key: string
                            label: string
                            required?: boolean | undefined
                            requiredScopes?: string | undefined
                            requires_field?: string | undefined
                            secret?: boolean | undefined
                            templating?: boolean | undefined
                            type:
                                | 'boolean'
                                | 'choice'
                                | 'customer_analytics_account_properties'
                                | 'customer_analytics_account_relationships'
                                | 'dictionary'
                                | 'email'
                                | 'integration'
                                | 'integration_field'
                                | 'integration_multi'
                                | 'json'
                                | 'native_email'
                                | 'non_failure_status_codes'
                                | 'number'
                                | 'posthog_assignee'
                                | 'posthog_business_hours'
                                | 'posthog_ticket_tags'
                                | 'string'
                                | 'task_mcp_installations'
                                | 'task_model'
                                | 'task_repository'
                        }[]
                      | null
                      | undefined
                  version: number
              }
        payload?: any
    }
    markAutoSave: (isAutoSave: boolean) => {
        isAutoSave: boolean
    }
    markSaveAttempted: (actionIds: string[]) => {
        actionIds: string[]
    }
    partialSetWorkflowActionConfig: (
        actionId: string,
        config: Partial<HogFlowAction['config']>
    ) => {
        actionId: string
        config: Partial<
            | {
                  cohorts: {
                      name?: string | undefined
                      percentage: number
                  }[]
              }
            | {
                  reason?: string | undefined
              }
            | {
                  type: 'schedule'
              }
            | {
                  conditions: {
                      filters: {
                          actions?: any[] | undefined
                          events?: any[] | undefined
                          properties?: any[] | undefined
                      }
                      name?: string | undefined
                  }[]
                  delay_duration?: string | undefined
              }
            | {
                  filters: {
                      all_roles_unassigned?: boolean | undefined
                      assigned_to_user_ids?: number[] | undefined
                      audience_type?: 'accounts' | 'persons' | undefined
                      properties: any[]
                      tag_names?: string[] | undefined
                  }
                  type: 'batch'
              }
            | {
                  filters: {
                      actions?: any[] | undefined
                      events?: any[] | undefined
                      filter_test_accounts?: boolean | undefined
                      properties?: any[] | undefined
                  }
                  type: 'event'
              }
            | {
                  filters: {
                      properties?: any[] | undefined
                  }
                  type: 'slack-message'
              }
            | {
                  condition: {
                      filters?:
                          | {
                                actions?: any[] | undefined
                                events?: any[] | undefined
                                properties?: any[] | undefined
                            }
                          | null
                          | undefined
                      name?: string | undefined
                  }
                  events?:
                      | {
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            name?: string | undefined
                        }[]
                      | undefined
                  max_wait_duration: string
              }
            | {
                  delay_duration?: string | undefined
                  delay_until?:
                      | {
                            bytecode?: any
                            bytecode_error?: string | undefined
                            expression: string
                            fallback_timezone?: string | null | undefined
                            offset?: string | undefined
                            timezone?: string | null | undefined
                            use_person_timezone?: boolean | undefined
                        }
                      | undefined
                  max_delay_duration?: string | undefined
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  mappings?:
                      | {
                            disabled?: boolean | undefined
                            filters?: any
                            inputs?:
                                | Record<
                                      string,
                                      {
                                          bytecode?: any
                                          order?: number | undefined
                                          secret?: boolean | undefined
                                          templating?: 'hog' | 'liquid' | undefined
                                          value: any
                                      }
                                  >
                                | null
                                | undefined
                            inputs_schema?:
                                | {
                                      choices?:
                                          | {
                                                label: string
                                                value: string
                                            }[]
                                          | undefined
                                      default?: any
                                      description?: string | undefined
                                      hidden?: boolean | undefined
                                      integration?: string | undefined
                                      integration_field?: string | undefined
                                      integration_key?: string | undefined
                                      key: string
                                      label: string
                                      required?: boolean | undefined
                                      requiredScopes?: string | undefined
                                      requires_field?: string | undefined
                                      secret?: boolean | undefined
                                      templating?: boolean | undefined
                                      type:
                                          | 'boolean'
                                          | 'choice'
                                          | 'customer_analytics_account_properties'
                                          | 'customer_analytics_account_relationships'
                                          | 'dictionary'
                                          | 'email'
                                          | 'integration'
                                          | 'integration_field'
                                          | 'integration_multi'
                                          | 'json'
                                          | 'native_email'
                                          | 'non_failure_status_codes'
                                          | 'number'
                                          | 'posthog_assignee'
                                          | 'posthog_business_hours'
                                          | 'posthog_ticket_tags'
                                          | 'string'
                                          | 'task_mcp_installations'
                                          | 'task_model'
                                          | 'task_repository'
                                  }[]
                                | undefined
                            name: string
                        }[]
                      | undefined
                  template_id: string
                  template_uuid?: string | undefined
              }
            | {
                  filters: {
                      properties?: any[] | undefined
                  }
                  key_property?: string | undefined
                  table_name: string
                  type: 'data-warehouse-table'
              }
            | {
                  filters: {
                      properties?: any[] | undefined
                  }
                  key_property?: string | undefined
                  table_name: string
                  type: 'data-warehouse-view'
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  template_id: string
                  template_uuid?: string | undefined
                  type: 'manual'
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  template_id: string
                  template_uuid?: string | undefined
                  type: 'tracking_pixel'
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  template_id: string
                  template_uuid?: string | undefined
                  type: 'webhook'
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  message_category_id?: string | undefined
                  message_category_type?: 'marketing' | 'transactional' | undefined
                  template_id: 'template-native-push'
                  template_uuid?: string | undefined
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  message_category_id?: string | undefined
                  message_category_type?: 'marketing' | 'transactional' | undefined
                  template_id: 'template-twilio'
                  template_uuid?: string | undefined
              }
            | {
                  day:
                      | ('friday' | 'monday' | 'saturday' | 'sunday' | 'thursday' | 'tuesday' | 'wednesday')[]
                      | 'any'
                      | 'weekday'
                      | 'weekend'
                  fallback_timezone?: string | null | undefined
                  time: [string, string] | 'any'
                  timezone: string | null
                  use_person_timezone?: boolean | undefined
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  message_category_id?: string | undefined
                  message_category_type?: 'marketing' | 'transactional' | undefined
                  template_id: 'template-email'
                  template_uuid?: string | undefined
                  tracking_enabled?: boolean | undefined
              }
        >
    }
    publishDraft: () => {
        value: true
    }
    replayDeferredResourceEdited: () => {
        value: true
    }
    resetWorkflow: (values?: HogFlow) => {
        values?: HogFlow
    }
    saveWorkflow: (updates: HogFlow) => HogFlow
    saveWorkflowFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    saveWorkflowPartial: (workflow: Partial<HogFlow>) => {
        workflow: Partial<HogFlow>
    }
    saveWorkflowSuccess: (
        originalWorkflow: HogFlow,
        payload?: HogFlow
    ) => {
        originalWorkflow: HogFlow
        payload?: HogFlow
    }
    setAutoSaveEnabled: (enabled: boolean) => {
        enabled: boolean
    }
    setDeferredResourceEdited: (event: ResourceEditedEvent | null) => {
        event: ResourceEditedEvent | null
    }
    setDraftActionPending: (pending: 'discard' | 'publish' | null) => {
        pending: 'discard' | 'publish' | null
    }
    setExternallyEdited: (externallyEdited: boolean) => {
        externallyEdited: boolean
    }
    setSaveBaseUpdatedAt: (updatedAt: string | null) => {
        updatedAt: string | null
    }
    setScheduleRepeating: (repeating: boolean) => {
        repeating: boolean
    }
    setScheduleStartsAt: (startsAt: string | null) => {
        startsAt: string | null
    }
    setScheduleStartsAtFromPicker: (pickerDate: string | null) => {
        pickerDate: string | null
    }
    setScheduleState: (
        scheduleState: ScheduleState,
        source?: 'natural_language' | 'picker'
    ) => {
        scheduleState: ScheduleState
        source: 'natural_language' | 'picker'
    }
    setScheduleTimezone: (
        timezone: string,
        previousTimezone?: string
    ) => {
        previousTimezone: string | undefined
        timezone: string
    }
    setSchedules: (schedules: HogFlowSchedule[]) => {
        schedules: HogFlowSchedule[]
    }
    setSyncingExternalEdit: (syncing: boolean) => {
        syncing: boolean
    }
    setWorkflowAction: (
        actionId: string,
        action: HogFlowAction
    ) => {
        action: HogFlowAction
        actionId: string
    }
    setWorkflowActionConfig: (
        actionId: string,
        config: HogFlowAction['config']
    ) => {
        actionId: string
        config:
            | {
                  cohorts: {
                      name?: string | undefined
                      percentage: number
                  }[]
              }
            | {
                  reason?: string | undefined
              }
            | {
                  type: 'schedule'
              }
            | {
                  conditions: {
                      filters: {
                          actions?: any[] | undefined
                          events?: any[] | undefined
                          properties?: any[] | undefined
                      }
                      name?: string | undefined
                  }[]
                  delay_duration?: string | undefined
              }
            | {
                  filters: {
                      all_roles_unassigned?: boolean | undefined
                      assigned_to_user_ids?: number[] | undefined
                      audience_type?: 'accounts' | 'persons' | undefined
                      properties: any[]
                      tag_names?: string[] | undefined
                  }
                  type: 'batch'
              }
            | {
                  filters: {
                      actions?: any[] | undefined
                      events?: any[] | undefined
                      filter_test_accounts?: boolean | undefined
                      properties?: any[] | undefined
                  }
                  type: 'event'
              }
            | {
                  filters: {
                      properties?: any[] | undefined
                  }
                  type: 'slack-message'
              }
            | {
                  condition: {
                      filters?:
                          | {
                                actions?: any[] | undefined
                                events?: any[] | undefined
                                properties?: any[] | undefined
                            }
                          | null
                          | undefined
                      name?: string | undefined
                  }
                  events?:
                      | {
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            name?: string | undefined
                        }[]
                      | undefined
                  max_wait_duration: string
              }
            | {
                  delay_duration?: string | undefined
                  delay_until?:
                      | {
                            bytecode?: any
                            bytecode_error?: string | undefined
                            expression: string
                            fallback_timezone?: string | null | undefined
                            offset?: string | undefined
                            timezone?: string | null | undefined
                            use_person_timezone?: boolean | undefined
                        }
                      | undefined
                  max_delay_duration?: string | undefined
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  mappings?:
                      | {
                            disabled?: boolean | undefined
                            filters?: any
                            inputs?:
                                | Record<
                                      string,
                                      {
                                          bytecode?: any
                                          order?: number | undefined
                                          secret?: boolean | undefined
                                          templating?: 'hog' | 'liquid' | undefined
                                          value: any
                                      }
                                  >
                                | null
                                | undefined
                            inputs_schema?:
                                | {
                                      choices?:
                                          | {
                                                label: string
                                                value: string
                                            }[]
                                          | undefined
                                      default?: any
                                      description?: string | undefined
                                      hidden?: boolean | undefined
                                      integration?: string | undefined
                                      integration_field?: string | undefined
                                      integration_key?: string | undefined
                                      key: string
                                      label: string
                                      required?: boolean | undefined
                                      requiredScopes?: string | undefined
                                      requires_field?: string | undefined
                                      secret?: boolean | undefined
                                      templating?: boolean | undefined
                                      type:
                                          | 'boolean'
                                          | 'choice'
                                          | 'customer_analytics_account_properties'
                                          | 'customer_analytics_account_relationships'
                                          | 'dictionary'
                                          | 'email'
                                          | 'integration'
                                          | 'integration_field'
                                          | 'integration_multi'
                                          | 'json'
                                          | 'native_email'
                                          | 'non_failure_status_codes'
                                          | 'number'
                                          | 'posthog_assignee'
                                          | 'posthog_business_hours'
                                          | 'posthog_ticket_tags'
                                          | 'string'
                                          | 'task_mcp_installations'
                                          | 'task_model'
                                          | 'task_repository'
                                  }[]
                                | undefined
                            name: string
                        }[]
                      | undefined
                  template_id: string
                  template_uuid?: string | undefined
              }
            | {
                  filters: {
                      properties?: any[] | undefined
                  }
                  key_property?: string | undefined
                  table_name: string
                  type: 'data-warehouse-table'
              }
            | {
                  filters: {
                      properties?: any[] | undefined
                  }
                  key_property?: string | undefined
                  table_name: string
                  type: 'data-warehouse-view'
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  template_id: string
                  template_uuid?: string | undefined
                  type: 'manual'
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  template_id: string
                  template_uuid?: string | undefined
                  type: 'tracking_pixel'
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  template_id: string
                  template_uuid?: string | undefined
                  type: 'webhook'
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  message_category_id?: string | undefined
                  message_category_type?: 'marketing' | 'transactional' | undefined
                  template_id: 'template-native-push'
                  template_uuid?: string | undefined
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  message_category_id?: string | undefined
                  message_category_type?: 'marketing' | 'transactional' | undefined
                  template_id: 'template-twilio'
                  template_uuid?: string | undefined
              }
            | {
                  day:
                      | ('friday' | 'monday' | 'saturday' | 'sunday' | 'thursday' | 'tuesday' | 'wednesday')[]
                      | 'any'
                      | 'weekday'
                      | 'weekend'
                  fallback_timezone?: string | null | undefined
                  time: [string, string] | 'any'
                  timezone: string | null
                  use_person_timezone?: boolean | undefined
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  message_category_id?: string | undefined
                  message_category_type?: 'marketing' | 'transactional' | undefined
                  template_id: 'template-email'
                  template_uuid?: string | undefined
                  tracking_enabled?: boolean | undefined
              }
    }
    setWorkflowActionEdges: (
        actionId: string,
        edges: HogFlow['edges']
    ) => {
        actionId: string
        edges: {
            from: string
            index?: number | undefined
            to: string
            type: 'branch' | 'continue'
        }[]
    }
    setWorkflowInfo: (workflow: Partial<HogFlow>) => {
        workflow: Partial<HogFlow>
    }
    setWorkflowManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setWorkflowValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setWorkflowValues: (values: DeepPartial<HogFlow>) => {
        values: DeepPartial<HogFlow>
    }
    submitWorkflow: () => {
        value: boolean
    }
    submitWorkflowFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitWorkflowRequest: (workflow: HogFlow) => {
        workflow: HogFlow
    }
    submitWorkflowSuccess: (workflow: HogFlow) => {
        workflow: HogFlow
    }
    touchWorkflowField: (key: string) => {
        key: string
    }
    triggerBatchWorkflow: (
        variables: Record<string, any>,
        filters: Extract<
            HogFlowAction['config'],
            {
                type: 'batch'
            }
        >['filters']
    ) => {
        filters: {
            all_roles_unassigned?: boolean | undefined
            assigned_to_user_ids?: number[] | undefined
            audience_type?: 'accounts' | 'persons' | undefined
            properties: any[]
            tag_names?: string[] | undefined
        }
        variables: Record<string, any>
    }
    triggerManualWorkflow: (variables: Record<string, any>) => {
        variables: Record<string, any>
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface workflowLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        logicProps: (arg: WorkflowLogicProps) => WorkflowLogicProps
        workflowUserAccessLevel: (originalWorkflow: HogFlow | null) => AccessControlLevel | null
        currentSchedule: (schedules: HogFlowSchedule[]) => HogFlowSchedule | null
        pendingSchedule: (
            currentSchedule: HogFlowSchedule | null,
            scheduleState: ScheduleState,
            scheduleStartsAt: string | null,
            scheduleTimezone: string,
            isScheduleRepeating: boolean
        ) =>
            | {
                  rrule: string
                  starts_at: string
                  timezone?: string
              }
            | false
            | null
        hasUnsavedChanges: (
            workflowChanged: boolean,
            pendingSchedule:
                | {
                      rrule: string
                      starts_at: string
                      timezone?: string
                  }
                | false
                | null
        ) => boolean
        workflowLoading: (originalWorkflowLoading: boolean) => boolean
        edgesByActionId: (workflow: HogFlow) => Record<string, HogFlowEdge[]>
        actionValidationErrorsById: (
            workflow: HogFlow,
            hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>,
            hogFunctionTemplatesByIdLoading: boolean,
            scheduleStartsAt: string | null,
            saveAttemptedActionIds: string[] | null
        ) => Record<string, HogFlowActionValidationResult | null>
        workflowHasActionErrors: (
            workflow: HogFlow,
            actionValidationErrorsById: Record<string, HogFlowActionValidationResult | null>
        ) => boolean
        autoSaveBlockedByValidation: (workflow: HogFlow) => boolean
        triggerAction: (workflow: HogFlow) => TriggerAction | null
        isRowScopedTrigger: (
            triggerAction:
                | ({
                      config:
                          | {
                                type: 'schedule'
                            }
                          | {
                                filters: {
                                    all_roles_unassigned?: boolean | undefined
                                    assigned_to_user_ids?: number[] | undefined
                                    audience_type?: 'accounts' | 'persons' | undefined
                                    properties: any[]
                                    tag_names?: string[] | undefined
                                }
                                type: 'batch'
                            }
                          | {
                                filters: {
                                    actions?: any[] | undefined
                                    events?: any[] | undefined
                                    filter_test_accounts?: boolean | undefined
                                    properties?: any[] | undefined
                                }
                                type: 'event'
                            }
                          | {
                                filters: {
                                    properties?: any[] | undefined
                                }
                                type: 'slack-message'
                            }
                          | {
                                filters: {
                                    properties?: any[] | undefined
                                }
                                key_property?: string | undefined
                                table_name: string
                                type: 'data-warehouse-table'
                            }
                          | {
                                filters: {
                                    properties?: any[] | undefined
                                }
                                key_property?: string | undefined
                                table_name: string
                                type: 'data-warehouse-view'
                            }
                          | {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                template_id: string
                                template_uuid?: string | undefined
                                type: 'manual'
                            }
                          | {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                template_id: string
                                template_uuid?: string | undefined
                                type: 'tracking_pixel'
                            }
                          | {
                                inputs: Record<
                                    string,
                                    {
                                        bytecode?: any
                                        order?: number | undefined
                                        secret?: boolean | undefined
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: any
                                    }
                                >
                                template_id: string
                                template_uuid?: string | undefined
                                type: 'webhook'
                            }
                      created_at?: number | undefined
                      description: string
                      filters?:
                          | {
                                actions?: any[] | undefined
                                events?: any[] | undefined
                                properties?: any[] | undefined
                            }
                          | null
                          | undefined
                      id: string
                      name: string
                      on_error?: 'abort' | 'continue' | null | undefined
                      output_variable?:
                          | {
                                key: string
                                label?: string | null | undefined
                                result_path?: string | null | undefined
                                spread?: boolean | null | undefined
                            }
                          | {
                                key: string
                                label?: string | null | undefined
                                result_path?: string | null | undefined
                                spread?: boolean | null | undefined
                            }[]
                          | null
                          | undefined
                      type: 'trigger'
                      updated_at?: number | undefined
                  } & Record<string, unknown>)
                | null
        ) => boolean
        workflowSanitized: (
            workflow: HogFlow,
            hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
        ) => HogFlow
        hasStagedDraft: (originalWorkflow: HogFlow | null) => boolean
    }
}

export type workflowLogicType = MakeLogicType<
    workflowLogicValues,
    workflowLogicActions,
    WorkflowLogicProps,
    workflowLogicMeta
>

export const workflowLogic = kea<workflowLogicType>([
    path((key) => ['products', 'workflows', 'frontend', 'Workflows', 'workflowLogic', key]),
    props({ id: 'new' } as WorkflowLogicProps),
    key(
        (props) => `workflow-${props.id || 'new'}-${props.templateId || 'default'}-${props.editTemplateId || 'default'}`
    ),
    connect(() => ({
        values: [userLogic, ['user'], projectLogic, ['currentProjectId']],
        actions: [workflowsLogic, ['archiveWorkflow'], resourceEditedLogic, ['resourceEdited']],
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
        markSaveAttempted: (actionIds: string[]) => ({ actionIds }),
        triggerManualWorkflow: (variables: Record<string, any>) => ({
            variables,
        }),
        triggerBatchWorkflow: (
            variables: Record<string, any>,
            filters: Extract<HogFlowAction['config'], { type: 'batch' }>['filters']
        ) => ({
            variables,
            filters,
        }),
        discardChanges: true,
        duplicate: true,
        autoSaveWorkflow: true,
        markAutoSave: (isAutoSave: boolean) => ({ isAutoSave }),
        setAutoSaveEnabled: (enabled: boolean) => ({ enabled }),
        clearAutoSavePending: true,
        setExternallyEdited: (externallyEdited: boolean) => ({ externallyEdited }),
        setSyncingExternalEdit: (syncing: boolean) => ({ syncing }),
        setSaveBaseUpdatedAt: (updatedAt: string | null) => ({ updatedAt }),
        keepMyWorkflowVersion: true,
        publishDraft: true,
        confirmPublishDraft: (confirmToken: string) => ({ confirmToken }),
        discardDraft: true,
        confirmDiscardDraft: true,
        setDraftActionPending: (pending: 'publish' | 'discard' | null) => ({ pending }),
        setDeferredResourceEdited: (event: ResourceEditedEvent | null) => ({ event }),
        replayDeferredResourceEdited: true,
    }),
    loaders(({ props, values, actions }) => ({
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

                    // The form's clean baseline: the staged draft merged over the live row. Sanitized
                    // like `updates` so untouched steps compare equal. Cloned via JSON round-trip,
                    // not structuredClone: the clone only feeds the comparison, and structuredClone
                    // can yield objects whose constructors fail fast-equals' check, making every
                    // save look like a content change.
                    const baseline = values.originalWorkflow
                        ? sanitizeWorkflow(
                              JSON.parse(JSON.stringify(withStagedDraft(values.originalWorkflow))),
                              values.hogFunctionTemplatesById
                          )
                        : null
                    const contentChanged =
                        !baseline ||
                        WORKFLOW_CONTENT_FIELDS.some(
                            (field) => !objectsEqual((updates as any)[field], (baseline as any)[field])
                        )
                    const isStatusTransition =
                        !!values.originalWorkflow && updates.status !== values.originalWorkflow.status
                    // Content edits on an active workflow stage into its draft (publish promotes them).
                    // Metadata-only saves (rename, description) must not: staging the unchanged content
                    // would create a phantom draft identical to live.
                    const stagingDraft =
                        values.originalWorkflow?.status === 'active' && updates.status === 'active' && contentChanged
                    // A status transition (enable/disable) toggles the lifecycle only. The button is
                    // disabled while the form is dirty, so content in the payload is at best a no-op
                    // re-send of the live row and at worst (with a staged draft merged into the form)
                    // a silent deploy of unpublished content. Metadata-only saves on active workflows
                    // strip content the same way, so unchanged content never routes to a draft.
                    const payload: Partial<HogFlow> =
                        isStatusTransition || (values.originalWorkflow?.status === 'active' && !contentChanged)
                            ? omitWorkflowContent(updates)
                            : updates
                    // Draft writes race against other draft writes, not the live row, so the staleness
                    // baseline follows the routing: the draft's own stamp once one is staged.
                    const loadedBase = stagingDraft
                        ? (values.originalWorkflow?.draft_updated_at ?? values.originalWorkflow?.updated_at)
                        : values.originalWorkflow?.updated_at

                    try {
                        return await api.hogFlows.updateHogFlow(props.id, {
                            ...payload,
                            ...(stagingDraft ? { stage_draft: true } : {}),
                            // A staged save's metadata still writes live; fence that write with the
                            // live stamp so it can't overwrite a concurrent metadata edit the
                            // draft-stamp baseline wouldn't catch.
                            ...(stagingDraft && values.originalWorkflow?.updated_at
                                ? { base_live_updated_at: values.originalWorkflow.updated_at }
                                : {}),
                            // Let the server reject the save if a newer copy exists (optimistic concurrency).
                            // saveBaseUpdatedAt overrides the loaded timestamp after the user picks "Keep mine".
                            base_updated_at: values.saveBaseUpdatedAt ?? loadedBase ?? null,
                        })
                    } catch (error) {
                        if (error instanceof ApiError && error.status === 409) {
                            if (values.isAutoSave && values.pendingSchedule === false) {
                                // An auto-save losing the race is not a decision point: the user never
                                // asked to overwrite anything, so reconcile to the newer copy silently.
                                // A pending schedule change is the exception: only a manual save
                                // persists it, and the reload would wipe it, so that gets the banner.
                                actions.setSyncingExternalEdit(true)
                                actions.loadWorkflow()
                            } else {
                                // A newer version exists (SSE event likely missed): surface the reconcile
                                // banner, which carries the actionable Reload / Keep mine choice. No toast,
                                // as it would just duplicate the banner (the global kea handler already
                                // skips 409).
                                actions.setExternallyEdited(true)
                            }
                        }
                        throw error
                    }
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
        isAutoSave: [
            false as boolean,
            {
                markAutoSave: (_, { isAutoSave }) => isAutoSave,
                submitWorkflow: () => false,
                saveWorkflowPartial: () => false,
            },
        ],
        lastSavedAt: [
            null as string | null,
            {
                saveWorkflowSuccess: () => dayjs().toISOString(),
                // Staged drafts don't bump the live updated_at, so the draft stamp is the real last
                // save. The cast collapses the loader's union: its template/new branches build
                // literals without the draft bookkeeping fields.
                loadWorkflowSuccess: (_, { originalWorkflow }) =>
                    (originalWorkflow as HogFlow | null)?.draft_updated_at ?? originalWorkflow?.updated_at ?? null,
            },
        ],
        isAutoSavePending: [
            false as boolean,
            {
                autoSaveWorkflow: () => true,
                clearAutoSavePending: () => false,
                saveWorkflowSuccess: () => false,
                saveWorkflowFailure: () => false,
                resetWorkflow: () => false,
                setAutoSaveEnabled: (_, { enabled }) => (!enabled ? false : _),
            },
        ],
        autoSaveEnabled: [
            true as boolean,
            {
                setAutoSaveEnabled: (_, { enabled }) => enabled,
            },
        ],
        // Bumped on every form write. A save records the version it captured, so its response can
        // tell whether the user kept editing while the request was in flight.
        workflowEditVersion: [
            0,
            {
                setWorkflowValue: (state) => state + 1,
                setWorkflowValues: (state) => state + 1,
            },
        ],
        // Gates when per-field step messages become visible: the action ids that were present at
        // the last save/enable attempt. Every step is validated the whole time (so the node badge
        // and enable-gate work), but a step only shows its messages once the user has tried to
        // save or enable with that step in place, which is the point where they can act on them.
        // A step added later stays quiet until the next attempt.
        saveAttemptedActionIds: [
            null as string[] | null,
            {
                markSaveAttempted: (_, { actionIds }) => actionIds,
                loadWorkflowSuccess: () => null,
            },
        ],
        // Set when another channel (another UI tab, MCP, or the API) saved this workflow while we had
        // unsaved local edits that auto-save can't flush (toggled off, validation errors, or a pending
        // schedule change). Surfaces a non-destructive "reload / keep mine" banner. Cleared whenever
        // we reload or save, since both reconcile us with the server copy.
        externallyEdited: [
            false as boolean,
            {
                setExternallyEdited: (_, { externallyEdited }) => externallyEdited,
                loadWorkflowSuccess: () => false,
                saveWorkflowSuccess: () => false,
            },
        ],
        // True while we silently reconcile to an external edit (clean local state). Drives a brief
        // overlay so the canvas is disabled and visibly "working" during the reload, like auto-save.
        isSyncingExternalEdit: [
            false as boolean,
            {
                setSyncingExternalEdit: (_, { syncing }) => syncing,
                loadWorkflowSuccess: () => false,
                loadWorkflowFailure: () => false,
            },
        ],
        // Overrides the base timestamp sent with the next save. Set when the user chooses "Keep mine" on
        // the conflict banner — we adopt the latest server updated_at so their save deliberately wins
        // instead of dead-ending on a 409. Reset once any load or save reconciles us with the server.
        saveBaseUpdatedAt: [
            null as string | null,
            {
                setSaveBaseUpdatedAt: (_, { updatedAt }) => updatedAt,
                loadWorkflowSuccess: () => null,
                saveWorkflowSuccess: () => null,
            },
        ],
        // Which staged-draft action is in flight, driving the banner buttons' loading/disabled state
        // so publish and discard can't race each other or double-submit.
        draftActionPending: [
            null as 'publish' | 'discard' | null,
            {
                setDraftActionPending: (_, { pending }) => pending,
            },
        ],
        // A resource_edited event parked while our own save/reload was in flight. Replayed once the
        // flight settles, so a genuine external edit landing in that window is reconciled instead of
        // dropped. Latest event wins: the comparison is against timestamps, so older ones are moot.
        deferredResourceEdited: [
            null as ResourceEditedEvent | null,
            {
                setDeferredResourceEdited: (_, { event }) => event,
            },
        ],
    }),
    selectors({
        logicProps: [
            () => [(_, props: WorkflowLogicProps) => props],
            (props: WorkflowLogicProps): WorkflowLogicProps => props,
        ],
        workflowUserAccessLevel: [
            (s) => [s.originalWorkflow],
            (originalWorkflow: HogFlow | null): AccessControlLevel | null =>
                originalWorkflow?.user_access_level ?? null,
        ],
        currentSchedule: [
            (s) => [s.schedules],
            (schedules: HogFlowSchedule[]): HogFlowSchedule | null => schedules[0] ?? null,
        ],
        pendingSchedule: [
            (s) => [s.currentSchedule, s.scheduleState, s.scheduleStartsAt, s.scheduleTimezone, s.isScheduleRepeating],
            (
                currentSchedule: HogFlowSchedule | null,
                scheduleState: ScheduleState,
                scheduleStartsAt: string | null,
                scheduleTimezone: string,
                isScheduleRepeating: boolean
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
            (
                formChanged: boolean,
                pendingSchedule:
                    | {
                          rrule: string
                          starts_at: string
                          timezone?: string
                      }
                    | false
                    | null
            ): boolean => formChanged || pendingSchedule !== false,
        ],
        workflowLoading: [
            (s) => [s.originalWorkflowLoading],
            (originalWorkflowLoading: boolean) => originalWorkflowLoading,
        ],
        edgesByActionId: [
            (s) => [s.workflow],
            (workflow: HogFlow): Record<string, HogFlowEdge[]> => {
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
            (s) => [
                s.workflow,
                s.hogFunctionTemplatesById,
                s.hogFunctionTemplatesByIdLoading,
                s.scheduleStartsAt,
                s.saveAttemptedActionIds,
            ],
            (
                workflow: HogFlow,
                hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>,
                hogFunctionTemplatesByIdLoading: boolean,
                scheduleStartsAt: string | null,
                saveAttemptedActionIds: string[] | null
            ): Record<string, HogFlowActionValidationResult | null> => {
                // Warehouse- and Slack-triggered workflows are person-less ("row-scoped").
                // Person-dependent step types make no sense without a person, so we block them at
                // save time.
                const triggerAction = workflow.actions.find((a) => a.type === 'trigger')
                const isRowScopedTrigger =
                    triggerAction?.type === 'trigger' && ROW_SCOPED_TRIGGER_TYPES.has(triggerAction.config?.type)

                return workflow.actions.reduce(
                    (acc, action) => {
                        const result: HogFlowActionValidationResult = {
                            valid: true,
                            schema: null,
                            errors: {},
                            warnings: {},
                        }

                        if (isRowScopedTrigger && PERSON_DEPENDENT_ACTION_TYPES.has(action.type)) {
                            result.valid = false
                            result.errors = {
                                _action:
                                    'This step relies on person data, which is not available for data warehouse table triggers',
                            }
                            acc[action.id] = result
                            return acc
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

                            const bodyError =
                                !emailValue?.html && !emailValue?.text
                                    ? 'Add some content to the email body'
                                    : ((emailValue?.html
                                          ? getTemplatingError(emailValue?.html, emailTemplating)
                                          : undefined) ??
                                      (emailValue?.text
                                          ? getTemplatingError(emailValue?.text, emailTemplating)
                                          : undefined))

                            const emailErrors: EmailFieldErrors = {
                                body: bodyError,
                                subject: !emailValue?.subject
                                    ? 'Add a subject line'
                                    : getTemplatingError(emailValue?.subject, emailTemplating),
                                from: !emailValue?.from?.integrationId
                                    ? 'Choose an email sender, or connect a new one'
                                    : (getTemplatingError(emailValue?.from?.email, emailTemplating) ??
                                      getTemplatingError(emailValue?.from?.name, emailTemplating)),
                                to: !emailValue?.to?.email
                                    ? 'Add a recipient'
                                    : getTemplatingError(emailValue?.to?.email, emailTemplating),
                            }

                            const hasEmailErrors = Object.values(emailErrors).some((v) => !!v)

                            if (hasEmailErrors) {
                                result.valid = false
                                // Placed on each input by the templater, not joined into one blob under
                                // the whole field. Held back until a save/enable attempt made with this
                                // step present, so opening or adding a template-started step (which
                                // always lacks a sender) reads as clean.
                                if (saveAttemptedActionIds?.includes(action.id)) {
                                    result.emailErrors = emailErrors
                                }
                            }
                        } else if (isFunctionAction(action) && action.config.template_id === 'template-native-push') {
                            // Native push needs at least one delivery channel; without one the runtime
                            // throws "No push channel configured" at send time. Block publish instead.
                            const channels = action.config.inputs?.channels?.value
                            if (!Array.isArray(channels) || channels.length === 0) {
                                result.valid = false
                                result.errors = {
                                    ...result.errors,
                                    channels: 'Select at least one channel to send this notification',
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
                                    ...result.errors,
                                    // This is a special case for the template_id field which might need to go to a generic error message
                                    _template_id: 'Template not found',
                                }
                            } else {
                                const configValidation = CyclotronJobInputsValidation.validate(
                                    action.config.inputs,
                                    template.inputs_schema ?? []
                                )
                                // Merge so the type-specific block above (e.g. function_email's
                                // stricter `from` check) is not clobbered by the generic validator.
                                result.valid = result.valid && configValidation.valid
                                result.errors = { ...configValidation.errors, ...result.errors }
                                result.warnings = { ...result.warnings, ...configValidation.warnings }

                                if (action.type === 'function_email') {
                                    // The generic validator also joins the email sub-fields into one
                                    // blob under the `email` key; drop it so nothing renders under the
                                    // whole input. Per-field messages come from `emailErrors` instead.
                                    delete result.errors.email
                                }
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
                                // Accounts audiences may legitimately target every account — the
                                // blast-radius preview and confirm token guard the send instead.
                                if (
                                    action.config.filters.audience_type !== 'accounts' &&
                                    !action.config.filters.properties?.length
                                ) {
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

        // Only a missing name blocks auto-save; the payload itself is unsaveable without one.
        // Action validation errors don't block: on an active workflow content stages into the
        // draft, which is safe to hold incomplete steps (enable and publish revalidate before
        // anything deploys, and agents stage incomplete drafts through the same API). Pausing on
        // them would strand a user's edits unsaved exactly while they iterate.
        autoSaveBlockedByValidation: [(s) => [s.workflow], (workflow: HogFlow): boolean => !workflow.name],

        triggerAction: [
            (s) => [s.workflow],
            (workflow: HogFlow): TriggerAction | null => {
                return (workflow.actions.find((action) => action.type === 'trigger') as TriggerAction) ?? null
            },
        ],

        // Warehouse-triggered workflows are person-less ("row-scoped"): no person data is available,
        // so person-dependent steps and person-aware exit conditions are blocked (see the serializer
        // for the authoritative enforcement).
        isRowScopedTrigger: [
            (s) => [s.triggerAction],
            (triggerAction: TriggerAction | null): boolean =>
                ROW_SCOPED_TRIGGER_TYPES.has(triggerAction?.config?.type ?? ''),
        ],

        workflowSanitized: [
            (s) => [s.workflow, s.hogFunctionTemplatesById],
            (workflow: HogFlow, hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>): HogFlow => {
                return sanitizeWorkflow(workflow, hogFunctionTemplatesById)
            },
        ],

        hasStagedDraft: [
            (s) => [s.originalWorkflow],
            (originalWorkflow: HogFlow | null): boolean => !!originalWorkflow?.draft,
        ],
    }),
    listeners(({ actions, values, props, cache }) => ({
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
        resourceEdited: ({ event }) => {
            // Another channel (a second UI tab, MCP, or the API) saved this workflow. React only to
            // events for the workflow we currently have open.
            if (event.resource_type !== 'HogFlow' || event.resource_id !== props.id) {
                return
            }
            // Our own save/reload is mid-flight (originalWorkflowLoading covers both, they share a
            // loader), or a publish/discard is about to reload: the emit for our own write can beat
            // its HTTP response back to us, and reacting to that echo against the stale baseline
            // flashes the conflict banner at ourselves. Park the event instead of reacting; once the
            // flight settles it replays against the fresh baseline, where our own echo compares equal
            // (ignored) and a genuine concurrent edit is still strictly newer (reconciled).
            if (values.originalWorkflowLoading || values.draftActionPending) {
                actions.setDeferredResourceEdited(event)
                return
            }
            // Draft writes don't bump the live updated_at (the emit broadcasts the newer of the two
            // stamps), so compare against the newest stamp we loaded or a staged edit from another
            // channel would go unnoticed.
            let loadedUpdatedAt = values.originalWorkflow?.updated_at
            const loadedDraftUpdatedAt = values.originalWorkflow?.draft_updated_at
            if (
                loadedDraftUpdatedAt &&
                loadedUpdatedAt &&
                dayjs(loadedDraftUpdatedAt).isAfter(dayjs(loadedUpdatedAt))
            ) {
                loadedUpdatedAt = loadedDraftUpdatedAt
            }
            // Strictly-newer comparison rather than equality: equal means the event is the echo of our
            // own save (originalWorkflow already carries that updated_at), so we ignore it. Only a server
            // copy that is genuinely ahead of what we loaded is a real external edit.
            if (!loadedUpdatedAt || !dayjs(event.updated_at).isAfter(dayjs(loadedUpdatedAt))) {
                return
            }
            // Server wins while auto-save can flush the local buffer: unsaved edits are then at most
            // a few seconds old, so reconcile silently instead of interrupting with a conflict
            // banner. When auto-save can't flush (toggled off, no name to save under, or a pending
            // schedule change, which only a manual save persists), the buffer can hold real work,
            // so the banner lets the user choose.
            const autoSaveCanFlush =
                values.autoSaveEnabled && !values.autoSaveBlockedByValidation && values.pendingSchedule === false
            if (values.hasUnsavedChanges && !autoSaveCanFlush) {
                actions.setExternallyEdited(true)
            } else {
                // Flag the sync first so the editor shows a brief working/disabled overlay and
                // re-enables once the fresh copy loads (like auto-save).
                actions.setSyncingExternalEdit(true)
                actions.loadWorkflow()
            }
        },
        publishDraft: async () => {
            if (!props.id || props.id === 'new' || values.draftActionPending) {
                return
            }
            actions.setDraftActionPending('publish')
            let preview
            try {
                // Two-step publish: the unconfirmed call only previews the impact and mints the token
                // a confirmed publish must return, so a stale draft can never be promoted blind.
                preview = await api.hogFlows.publishHogFlow(props.id, { confirm: false })
            } catch {
                lemonToast.error('Could not load the publish preview. Please try again.')
                return
            } finally {
                actions.setDraftActionPending(null)
            }
            openPublishConfirmDialog({
                impact: preview.impact,
                inFlightRuns: preview.in_flight_runs,
                onConfirm: () => actions.confirmPublishDraft(preview.confirm_token ?? ''),
            })
        },
        confirmPublishDraft: async ({ confirmToken }) => {
            // draftActionPending also guards the dialog's close-animation window, where a fast
            // double-click on the confirm button dispatches twice.
            if (!props.id || props.id === 'new' || values.draftActionPending) {
                return
            }
            actions.setDraftActionPending('publish')
            try {
                await api.hogFlows.publishHogFlow(props.id, { confirm: true, confirm_token: confirmToken })
                lemonToast.success('Changes published')
                actions.loadWorkflow()
            } catch {
                // Covers a stale/expired token (the draft moved since the preview) and plain failures.
                lemonToast.error('Publishing failed. Review the staged changes and try again.')
                actions.loadWorkflow()
            } finally {
                actions.setDraftActionPending(null)
            }
        },
        discardDraft: () => {
            if (!props.id || props.id === 'new' || values.draftActionPending) {
                return
            }
            LemonDialog.open({
                title: 'Discard staged changes?',
                description: 'This throws away the staged changes. The live workflow is unaffected.',
                primaryButton: {
                    children: 'Discard',
                    status: 'danger',
                    onClick: () => actions.confirmDiscardDraft(),
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        },
        confirmDiscardDraft: async () => {
            if (!props.id || props.id === 'new' || values.draftActionPending) {
                return
            }
            actions.setDraftActionPending('discard')
            try {
                await api.hogFlows.discardHogFlowDraft(props.id)
                lemonToast.success('Staged changes discarded')
                actions.loadWorkflow()
            } catch {
                lemonToast.error('Could not discard the staged changes. Please try again.')
            } finally {
                actions.setDraftActionPending(null)
            }
        },
        keepMyWorkflowVersion: async () => {
            // The user wants their in-progress edits to win. Adopt the latest server updated_at as the
            // save baseline (without touching their canvas) so the next save passes the optimistic-lock
            // check and deliberately overwrites the other channel's version, instead of looping on 409.
            if (props.id && props.id !== 'new') {
                try {
                    const latest = await api.hogFlows.getHogFlow(props.id)
                    // On an active workflow the next save races the draft slot, so its stamp is the baseline.
                    actions.setSaveBaseUpdatedAt(latest.draft_updated_at ?? latest.updated_at)
                } catch {
                    // If we can't fetch the latest timestamp, just dismiss; the 409 backstop still protects them.
                }
            }
            actions.setExternallyEdited(false)
        },
        submitWorkflow: () => {
            actions.markSaveAttempted(values.workflow.actions.map((action) => action.id))
        },
        saveWorkflowPartial: async ({ workflow }) => {
            // Recorded before the error guard: an enable attempt on an invalid draft must still
            // reveal the per-field step messages even though the save itself is aborted.
            actions.markSaveAttempted(values.workflow.actions.map((action) => action.id))
            const merged = { ...values.workflow, ...workflow }
            if (merged.status === 'active' && values.workflowHasActionErrors) {
                lemonToast.error('Fix all errors before enabling')
                return
            }
            actions.saveWorkflow(merged)
        },
        loadWorkflowSuccess: async ({ originalWorkflow }) => {
            // The form edits the staged draft when one exists; the live config keeps running underneath.
            actions.resetWorkflow(withStagedDraft(originalWorkflow))
            actions.replayDeferredResourceEdited()
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
        loadWorkflowFailure: () => {
            actions.replayDeferredResourceEdited()
        },
        saveWorkflow: () => {
            cache.saveEditVersion = values.workflowEditVersion
        },
        saveWorkflowFailure: () => {
            actions.replayDeferredResourceEdited()
        },
        replayDeferredResourceEdited: () => {
            const deferred = values.deferredResourceEdited
            if (deferred) {
                actions.setDeferredResourceEdited(null)
                actions.resourceEdited(deferred)
            }
        },
        saveWorkflowSuccess: async ({ originalWorkflow }) => {
            const isAutoSave = values.isAutoSave

            if (!isAutoSave) {
                // Save pending schedule changes (only on manual save)
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

                if (originalWorkflow.draft) {
                    // Saving used to deploy immediately, so the changed contract needs a loud cue at
                    // the moment of saving, not only the status bar.
                    lemonToast.success('Draft saved. The live version keeps running until you publish.', {
                        button: {
                            label: 'Publish',
                            action: () => actions.publishDraft(),
                        },
                    })
                } else {
                    lemonToast.success('Workflow saved')
                }

                if (props.id === 'new') {
                    tryShowMCPHint('workflows.create')
                }

                if (props.id === 'new' && originalWorkflow.id) {
                    router.actions.replace(
                        urls.workflow(
                            originalWorkflow.id,
                            workflowSceneLogic.findMounted()?.values.currentTab || 'workflow'
                        )
                    )
                }
            }

            const tasksToMarkAsCompleted: SetupTaskId[] = []

            // Mark workflow creation task as completed everytime it's saved for completeness
            tasksToMarkAsCompleted.push(SetupTaskId.CreateFirstWorkflow)

            // Check trigger configuration
            const trigger = originalWorkflow.actions.find((a) => a.type === 'trigger')
            if (trigger) {
                const config = trigger.config as any
                const hasValidTrigger =
                    (config.type === 'event' &&
                        (config.filters?.events?.length > 0 || config.filters?.actions?.length > 0)) ||
                    config.type === 'schedule' ||
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

            // A staged save's response carries the live config plus the new draft blob: rebaseline the
            // form on the merged view, or the reset would wipe the just-saved edits off the canvas.
            const editedDuringSave =
                cache.saveEditVersion !== undefined && values.workflowEditVersion !== cache.saveEditVersion
            const editsDuringSave = editedDuringSave ? pickWorkflowEdits(values.workflow) : null
            actions.resetWorkflow(withStagedDraft(originalWorkflow))
            actions.markAutoSave(false)
            if (editsDuringSave) {
                // The response only reflects the payload that was sent. Anything typed while it was
                // in flight (the live email editor writes on every pause) must survive the reset and
                // stay dirty, or it vanishes from the form and the canvas reloads the stale version.
                actions.setWorkflowValues(editsDuringSave)
                actions.autoSaveWorkflow()
            }
            actions.replayDeferredResourceEdited()
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
                    onClick: () =>
                        actions.resetWorkflow(
                            values.originalWorkflow ? withStagedDraft(values.originalWorkflow) : NEW_WORKFLOW
                        ),
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        },
        setWorkflowInfo: async ({ workflow }) => {
            actions.setWorkflowValues(workflow)
            actions.autoSaveWorkflow()
        },
        setWorkflowActionConfig: async ({ actionId, config }) => {
            const action = values.workflow.actions.find((action) => action.id === actionId)
            if (!action) {
                return
            }

            // Replace the action rather than mutating it: subscribers diff the workflow against
            // their previous snapshot, and an in-place write updates that snapshot too, making
            // every config edit look like a no-op.
            const updatedAction = { ...action, config: { ...config } as HogFlowAction['config'] }

            const changes = {
                actions: values.workflow.actions.map((a) => (a.id === actionId ? updatedAction : a)),
            } as Partial<HogFlow>
            if (updatedAction.type === 'trigger') {
                changes.trigger = updatedAction.config as TriggerAction['config']
            }

            actions.setWorkflowValues(changes)
            actions.autoSaveWorkflow()
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
            actions.autoSaveWorkflow()
        },
        setWorkflowActionEdges: async ({ actionId, edges }) => {
            // Helper method - Replaces all edges related to the action with the new edges
            const actionEdges = values.edgesByActionId[actionId] ?? []
            const newEdges = values.workflow.edges.filter((e) => !actionEdges.includes(e))

            actions.setWorkflowValues({ edges: [...newEdges, ...edges] })
            actions.autoSaveWorkflow()
        },
        setWorkflowValue: () => {
            actions.autoSaveWorkflow()
        },
        setAutoSaveEnabled: ({ enabled }) => {
            if (enabled && values.workflowChanged) {
                actions.autoSaveWorkflow()
            }
        },
        autoSaveWorkflow: async (_, breakpoint) => {
            await breakpoint(3000)

            // Active workflows auto-save too: their content edits route into the staged draft
            // (stage_draft in the saveWorkflow loader), so nothing deploys without an explicit publish.
            const shouldSkip =
                !values.autoSaveEnabled ||
                !props.id ||
                props.id === 'new' ||
                !!props.editTemplateId ||
                !values.workflowChanged ||
                values.autoSaveBlockedByValidation

            if (shouldSkip) {
                actions.clearAutoSavePending()
                return
            }

            actions.markAutoSave(true)
            actions.saveWorkflow(values.workflow)
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
        triggerBatchWorkflow: async ({ variables, filters }) => {
            if (!values.workflow.id || values.workflow.id === 'new') {
                lemonToast.error('You need to save the workflow before triggering it manually.')
                return
            }

            lemonToast.info('Triggering batch workflow...')

            try {
                await api.hogFlows.createHogFlowBatchJob(values.workflow.id, {
                    variables,
                    filters,
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
    beforeUnload((logic) => ({
        enabled: (newLocation) => {
            if (!logic.props.id || logic.props.id === 'new') {
                return false
            }
            if (logic.props.editTemplateId) {
                return false
            }
            if (!logic.values.hasUnsavedChanges) {
                return false
            }
            if (newLocation && newLocation.pathname === router.values.location.pathname) {
                return false
            }
            return true
        },
        message: 'Leave workflow?\nChanges you made will be discarded.',
        onConfirm: () => {
            if (logic.values.originalWorkflow) {
                logic.actions.resetWorkflow(logic.values.originalWorkflow)
            }
        },
    })),
])
