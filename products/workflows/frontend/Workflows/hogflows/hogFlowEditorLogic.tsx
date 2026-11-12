import { getOutgoers } from '@xyflow/react'
import { MakeLogicType, actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'
import type { DragEvent } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import { AppMetricsTotalsResponse } from 'lib/components/AppMetrics/appMetricsLogic'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { uuid } from 'lib/utils/dom'
import { objectsEqual, reconcileById } from 'lib/utils/objects'
import { templateToConfiguration } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type {
    HogFunctionTemplateType,
    IntegrationType,
    TeamPublicType,
    TeamType,
    UserBasicType,
} from '../../../../../frontend/src/types'
import { resolveDefaultEmailSender } from '../../Channels/defaultEmailSender'
import { sandboxSenderLogic } from '../../Channels/sandboxSenderLogic'
import type { WorkflowEmailSandboxStatusApi } from '../../generated/api.schemas'
import { optOutCategoriesLogic } from '../../OptOuts/optOutCategoriesLogic'
import type { MessageCategory } from '../../OptOuts/optOutCategoriesLogic'
import { EXIT_NODE_ID, TRIGGER_NODE_ID, WorkflowLogicProps, workflowLogic } from '../workflowLogic'
import { getEdgeId } from './edgeId'
import { getTeamUtmDefaults, newEmailUtmConfig, utmKeysFollowingSavedDefault } from './steps/components/utmDefaults'
import type { UtmTagValues } from './steps/components/UtmTagFields'
import type { UtmTagKey } from './steps/components/UtmTagFields'
import {
    hasOwnSender,
    needsSandboxSender,
    sandboxSenderAllowed,
    toSandboxAction,
} from './steps/email/emailStepVariants'
import { getHogFlowStep } from './steps/HogFlowSteps'
import { CyclotronInputType } from './steps/types'
import type { DropzoneNode, HogFlow, HogFlowAction, HogFlowActionEdge, HogFlowActionNode } from './types'
import type { HogFlowEdge } from './types'

export function computeInsertEdges(
    edges: HogFlow['edges'],
    newActionId: string,
    branchEdges: number,
    edgesToReplace: HogFlow['edges']
): HogFlow['edges'] | null {
    const edgeIdsToReplace = new Set(edgesToReplace.map(getEdgeId))
    const matchingEdges = edges.filter((edge) => edgeIdsToReplace.has(getEdgeId(edge)))

    if (matchingEdges.length === 0 || matchingEdges.length !== edgesToReplace.length) {
        return null
    }

    return [
        ...edges.filter((edge) => !edgeIdsToReplace.has(getEdgeId(edge))),
        ...matchingEdges.map((edge) => ({ ...edge, to: newActionId })),
        ...Array.from({ length: branchEdges }, (_, index) => ({
            ...matchingEdges[0],
            index,
            type: 'branch' as const,
            from: newActionId,
        })),
        {
            ...matchingEdges[0],
            index: undefined,
            type: 'continue' as const,
            from: newActionId,
        },
    ]
}

/**
 * Helper to get branch label with custom name fallback
 */
/**
 * Computes the new edges after moving a node to a new position in the graph.
 * Extracted into pure function to be easier to test.
 */
export function computeMoveEdges(
    edges: HogFlow['edges'],
    movingNodeId: string,
    targetEdge: HogFlow['edges'][0],
    isBranchJoinDropzone: boolean,
    joinEdges?: HogFlow['edges']
): HogFlow['edges'] | null {
    const incomingEdges = edges.filter((e) => e.to === movingNodeId)
    const outgoingEdge = edges.find((e) => e.from === movingNodeId)

    if (!outgoingEdge || incomingEdges.length === 0) {
        return null
    }

    // Step 1: Bypass the node — incoming edges point to the node's outgoer, outgoing edge removed
    let newEdges = edges
        .map((e) => (e.to === movingNodeId ? { ...e, to: outgoingEdge.to } : e))
        .filter((e) => e.from !== movingNodeId)

    // Step 2: Find the target edge(s) to insert into.
    // We match by from/type/index (not the full edge ID) because step 1 may have
    // changed the 'to' field of the target edge if the moving node was its target.
    let edgesToSplitIndexes: number[] = []

    if (isBranchJoinDropzone) {
        const newTarget = targetEdge.to === movingNodeId ? outgoingEdge.to : targetEdge.to
        const joinEdgeIds = joinEdges ? new Set(joinEdges.map(getEdgeId)) : null
        edgesToSplitIndexes = newEdges
            .map((edge, index) => ({ edge, index }))
            .filter(({ edge }) => (joinEdgeIds ? joinEdgeIds.has(getEdgeId(edge)) : edge.to === newTarget))
            .map(({ index }) => index)
    } else {
        edgesToSplitIndexes = [
            newEdges.findIndex(
                (edge) =>
                    edge.from === targetEdge.from && edge.type === targetEdge.type && edge.index === targetEdge.index
            ),
        ]
    }

    if (edgesToSplitIndexes.length === 0 || edgesToSplitIndexes.includes(-1)) {
        return null
    }

    // Step 3: Split the target edge(s) — sources → movingNode → original target
    const edgesToSplit = edgesToSplitIndexes.map((i) => newEdges[i])
    const insertionTarget = edgesToSplit[0].to

    edgesToSplitIndexes.sort((a, b) => b - a).forEach((i) => newEdges.splice(i, 1))

    for (const edge of edgesToSplit) {
        newEdges.push({ ...edge, to: movingNodeId })
    }

    newEdges.push({
        from: movingNodeId,
        to: insertionTarget,
        type: 'continue',
        index: undefined,
    } as HogFlow['edges'][0])

    return newEdges
}

const BRANCHING_STEP_TYPES: HogFlowAction['type'][] = [
    'conditional_branch',
    'random_cohort_branch',
    'wait_until_condition',
]

/** A step moves on its own when it has one next step and no paths of its own to carry along. */
export function canMoveStep(workflow: HogFlow, actionId: string): boolean {
    const action = workflow.actions.find((candidate) => candidate.id === actionId)
    if (!action || action.type === 'trigger' || action.type === 'exit' || BRANCHING_STEP_TYPES.includes(action.type)) {
        return false
    }
    return new Set(workflow.edges.filter((edge) => edge.from === actionId).map((edge) => edge.to)).size === 1
}

export const HOG_FLOW_EDITOR_MODES = ['build', 'variables', 'test', 'metrics', 'logs'] as const
export type HogFlowEditorMode = (typeof HOG_FLOW_EDITOR_MODES)[number]
export const HOG_FLOW_EDITOR_DEFAULT_PANEL_WIDTH = 592
export type HogFlowEditorActionMetrics = {
    actionId: string
    succeeded: number
    failed: number
    filtered: number
}

/** Turns metric totals broken down by step and metric into one entry per step. */
export function actionMetricsFromTotals(
    response: AppMetricsTotalsResponse
): Record<string, HogFlowEditorActionMetrics> {
    const res: Record<string, HogFlowEditorActionMetrics> = {}
    Object.values(response).forEach((value) => {
        let [instanceId, metricName] = value.breakdowns

        if (!metricName) {
            return
        }

        if (!instanceId) {
            // TRICKY: Trigger and exit dont get their own metrics so we pull from the overall metrics
            if (['succeeded', 'failed'].includes(metricName)) {
                instanceId = EXIT_NODE_ID
            } else if (['rate_limited', 'triggered'].includes(metricName)) {
                instanceId = TRIGGER_NODE_ID
                if (['rate_limited'].includes(metricName)) {
                    metricName = 'failed'
                }
                if (['triggered'].includes(metricName)) {
                    metricName = 'succeeded'
                }
            }
        }

        res[instanceId] = res[instanceId] || {
            actionId: instanceId,
            succeeded: 0,
            failed: 0,
            filtered: 0,
        }
        if (metricName in res[instanceId]) {
            ;(res[instanceId] as any)[metricName] = value.total
        }
    })

    return res
}

export type OutputMappingSuggestion = {
    key: string
    result_path: string
    label: string
}

export type CreateActionType = Pick<HogFlowAction, 'type' | 'config' | 'name' | 'description'> & {
    branchEdges?: number
    output_variable?: HogFlowAction['output_variable']
    on_error?: HogFlowAction['on_error']
    getDefaultInputs?: () => Record<string, CyclotronInputType> | undefined
    getOutputMappingSuggestions?: () => Promise<OutputMappingSuggestion[]>
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface hogFlowEditorLogicValues {
    integrations: IntegrationType[] | null // integrationsLogic
    categories: MessageCategory[] // optOutCategoriesLogic
    categoriesLoading: boolean // optOutCategoriesLogic
    canAdoptSandbox: boolean // sandboxSenderLogic
    sandboxStatus: WorkflowEmailSandboxStatusApi | null // sandboxSenderLogic
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    edgesByActionId: Record<string, HogFlowEdge[]> // workflowLogic
    hogFunctionTemplatesById: Record<string, HogFunctionTemplateType> // workflowLogic
    workflow: HogFlow // workflowLogic
    dropzoneNodes: DropzoneNode[]
    edges: HogFlowActionEdge[]
    highlightedDropzoneNodeId: string | null
    isCopyingNode: boolean
    isMovingNode: boolean
    mode: HogFlowEditorMode
    movingNodeId: string | null
    nodeToBeAdded: CreateActionType | HogFlowActionNode | null
    nodes: HogFlowActionNode[]
    nodesById: Record<string, HogFlowActionNode>
    panelWidth: number | null
    selectedNode: HogFlowActionNode | null
    selectedNodeCanBeCopiedOrMoved: boolean
    selectedNodeCanBeDeleted: boolean
    selectedNodeId: string | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface hogFlowEditorLogicActions {
    loadCategories: () => {
        value: true
    } // optOutCategoriesLogic
    provisionSandboxSender: (surface: import('../../Channels/sandboxSender').SandboxSenderSurface) => {
        surface: import('../../Channels/sandboxSender').SandboxSenderSurface
    } // sandboxSenderLogic
    loadWorkflowSuccess: (
        originalWorkflow:
            | HogFlow
            | {
                  abort_action?: string | undefined
                  actions: (
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
                            config: {
                                conditions: {
                                    filters: {
                                        actions?: any[] | undefined
                                        events?: any[] | undefined
                                        properties?: any[] | undefined
                                    }
                                    name?: string | undefined
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
                            type: 'conditional_branch'
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
                                inputs: {
                                    email: {
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: {
                                            design?: any
                                            html?: string | undefined
                                            preheader?: string | undefined
                                            subject?: string | undefined
                                            text?: string | undefined
                                            to?:
                                                | {
                                                      email: string
                                                      name?: string | undefined
                                                  }
                                                | undefined
                                        }
                                    }
                                }
                                message_category_id?: string | null | undefined
                                message_category_type?: 'marketing' | 'transactional' | null | undefined
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
                            type: 'email_sandbox'
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
                                                        | 'posthog_survey'
                                                        | 'posthog_ticket_tags'
                                                        | 'replay_vision_scan'
                                                        | 'signals_scout'
                                                        | 'string'
                                                        | 'task_mcp_installations'
                                                        | 'task_model'
                                                        | 'task_repository'
                                                        | 'task_skills'
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
                                sensitive?: boolean | undefined
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
                                message_category_id?: string | null | undefined
                                message_category_type?: 'marketing' | 'transactional' | undefined
                                skip_frequency_cap?: boolean | undefined
                                template_id: 'template-email'
                                template_uuid?: string | undefined
                                tracking_enabled?: boolean | undefined
                                utm_params?:
                                    | {
                                          utm_campaign?: string | undefined
                                          utm_content?: string | undefined
                                          utm_medium?: string | undefined
                                          utm_source?: string | undefined
                                      }
                                    | undefined
                                utm_params_from_default?:
                                    | ('utm_campaign' | 'utm_content' | 'utm_medium' | 'utm_source')[]
                                    | undefined
                                utm_tags_enabled?: boolean | undefined
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
                            config:
                                | {
                                      type: 'api'
                                  }
                                | {
                                      type: 'schedule'
                                  }
                                | {
                                      filters: {
                                          events: any[]
                                          properties?: any[] | undefined
                                          source: 'internal-events'
                                      }
                                      type: 'internal-event'
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
                                          all_roles_unassigned?: boolean | undefined
                                          assigned_to_user_ids?: number[] | undefined
                                          assignment_status?: 'all' | 'assigned' | 'unassigned' | undefined
                                          audience_type?: 'accounts' | 'persons' | undefined
                                          properties: any[]
                                          tag_names?: string[] | undefined
                                      }
                                      type: 'batch'
                                  }
                                | {
                                      cohort_id: number | null
                                      transition: 'entered' | 'left'
                                      type: 'cohort'
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
                            window?: string | undefined
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
                            type: 'api'
                        }
                      | {
                            type: 'schedule'
                        }
                      | {
                            filters: {
                                events: any[]
                                properties?: any[] | undefined
                                source: 'internal-events'
                            }
                            type: 'internal-event'
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
                                all_roles_unassigned?: boolean | undefined
                                assigned_to_user_ids?: number[] | undefined
                                assignment_status?: 'all' | 'assigned' | 'unassigned' | undefined
                                audience_type?: 'accounts' | 'persons' | undefined
                                properties: any[]
                                tag_names?: string[] | undefined
                            }
                            type: 'batch'
                        }
                      | {
                            cohort_id: number | null
                            transition: 'entered' | 'left'
                            type: 'cohort'
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
                                | 'posthog_survey'
                                | 'posthog_ticket_tags'
                                | 'replay_vision_scan'
                                | 'signals_scout'
                                | 'string'
                                | 'task_mcp_installations'
                                | 'task_model'
                                | 'task_repository'
                                | 'task_skills'
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
                            config: {
                                conditions: {
                                    filters: {
                                        actions?: any[] | undefined
                                        events?: any[] | undefined
                                        properties?: any[] | undefined
                                    }
                                    name?: string | undefined
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
                            type: 'conditional_branch'
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
                                inputs: {
                                    email: {
                                        templating?: 'hog' | 'liquid' | undefined
                                        value: {
                                            design?: any
                                            html?: string | undefined
                                            preheader?: string | undefined
                                            subject?: string | undefined
                                            text?: string | undefined
                                            to?:
                                                | {
                                                      email: string
                                                      name?: string | undefined
                                                  }
                                                | undefined
                                        }
                                    }
                                }
                                message_category_id?: string | null | undefined
                                message_category_type?: 'marketing' | 'transactional' | null | undefined
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
                            type: 'email_sandbox'
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
                                                        | 'posthog_survey'
                                                        | 'posthog_ticket_tags'
                                                        | 'replay_vision_scan'
                                                        | 'signals_scout'
                                                        | 'string'
                                                        | 'task_mcp_installations'
                                                        | 'task_model'
                                                        | 'task_repository'
                                                        | 'task_skills'
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
                                sensitive?: boolean | undefined
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
                                message_category_id?: string | null | undefined
                                message_category_type?: 'marketing' | 'transactional' | undefined
                                skip_frequency_cap?: boolean | undefined
                                template_id: 'template-email'
                                template_uuid?: string | undefined
                                tracking_enabled?: boolean | undefined
                                utm_params?:
                                    | {
                                          utm_campaign?: string | undefined
                                          utm_content?: string | undefined
                                          utm_medium?: string | undefined
                                          utm_source?: string | undefined
                                      }
                                    | undefined
                                utm_params_from_default?:
                                    | ('utm_campaign' | 'utm_content' | 'utm_medium' | 'utm_source')[]
                                    | undefined
                                utm_tags_enabled?: boolean | undefined
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
                            config:
                                | {
                                      type: 'api'
                                  }
                                | {
                                      type: 'schedule'
                                  }
                                | {
                                      filters: {
                                          events: any[]
                                          properties?: any[] | undefined
                                          source: 'internal-events'
                                      }
                                      type: 'internal-event'
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
                                          all_roles_unassigned?: boolean | undefined
                                          assigned_to_user_ids?: number[] | undefined
                                          assignment_status?: 'all' | 'assigned' | 'unassigned' | undefined
                                          audience_type?: 'accounts' | 'persons' | undefined
                                          properties: any[]
                                          tag_names?: string[] | undefined
                                      }
                                      type: 'batch'
                                  }
                                | {
                                      cohort_id: number | null
                                      transition: 'entered' | 'left'
                                      type: 'cohort'
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
                            window?: string | undefined
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
                            type: 'api'
                        }
                      | {
                            type: 'schedule'
                        }
                      | {
                            filters: {
                                events: any[]
                                properties?: any[] | undefined
                                source: 'internal-events'
                            }
                            type: 'internal-event'
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
                                all_roles_unassigned?: boolean | undefined
                                assigned_to_user_ids?: number[] | undefined
                                assignment_status?: 'all' | 'assigned' | 'unassigned' | undefined
                                audience_type?: 'accounts' | 'persons' | undefined
                                properties: any[]
                                tag_names?: string[] | undefined
                            }
                            type: 'batch'
                        }
                      | {
                            cohort_id: number | null
                            transition: 'entered' | 'left'
                            type: 'cohort'
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
                                | 'posthog_survey'
                                | 'posthog_ticket_tags'
                                | 'replay_vision_scan'
                                | 'signals_scout'
                                | 'string'
                                | 'task_mcp_installations'
                                | 'task_model'
                                | 'task_repository'
                                | 'task_skills'
                        }[]
                      | null
                      | undefined
                  version: number
              }
        payload?: any
    } // workflowLogic
    setWorkflowAction: (
        actionId: string,
        action: HogFlowAction
    ) => {
        action: HogFlowAction
        actionId: string
    } // workflowLogic
    setWorkflowActionEdges: (
        actionId: string,
        edges: {
            from: string
            index?: number | undefined
            to: string
            type: 'branch' | 'continue'
        }[]
    ) => {
        actionId: string
        edges: {
            from: string
            index?: number | undefined
            to: string
            type: 'branch' | 'continue'
        }[]
    } // workflowLogic
    setWorkflowInfo: (workflow: Partial<HogFlow>) => {
        workflow: Partial<HogFlow>
    } // workflowLogic
    clearPanelWidth: () => {
        value: true
    }
    copyNodeToHighlightedDropzone: () => {
        value: true
    }
    handlePaneClick: () => {
        value: true
    }
    hideDropzones: () => {
        value: true
    }
    markUtmSavedAsTeamDefault: (
        actionId: string,
        saved: UtmTagValues
    ) => {
        actionId: string
        saved: Partial<Record<UtmTagKey, string>>
    }
    moveNodeToEdge: (
        movingNodeId: string,
        targetEdge: HogFlowEdge,
        isBranchJoinDropzone: boolean,
        joinEdges?: HogFlowEdge[]
    ) => {
        isBranchJoinDropzone: boolean
        joinEdges: HogFlowEdge[] | undefined
        movingNodeId: string
        targetEdge: HogFlowEdge
    }
    moveNodeToHighlightedDropzone: () => {
        value: true
    }
    onDragOver: (event: DragEvent) => {
        event: DragEvent<Element>
    }
    onDrop: (
        event?: DragEvent,
        targetEdge?: HogFlowEdge,
        joinEdges?: HogFlowEdge[]
    ) => {
        event: DragEvent<Element> | undefined
        joinEdges: HogFlowEdge[] | undefined
        targetEdge: HogFlowEdge | undefined
    }
    onNodesDelete: (deleted: HogFlowActionNode[]) => {
        deleted: HogFlowActionNode[]
    }
    resetFlowFromHogFlow: (hogFlow: HogFlow) => {
        hogFlow: HogFlow
    }
    setDropzoneNodes: (dropzoneNodes: DropzoneNode[]) => {
        dropzoneNodes: DropzoneNode[]
    }
    setEdges: (edges: HogFlowActionEdge[]) => {
        edges: HogFlowActionEdge[]
    }
    setHighlightedDropzoneNodeId: (highlightedDropzoneNodeId: string | null) => {
        highlightedDropzoneNodeId: string | null
    }
    setMode: (mode: HogFlowEditorMode) => {
        mode: 'build' | 'logs' | 'metrics' | 'test' | 'variables'
    }
    setNodeToBeAdded: (nodeToBeAdded: CreateActionType | HogFlowActionNode | null) => {
        nodeToBeAdded: CreateActionType | HogFlowActionNode | null
    }
    setNodesRaw: (nodes: HogFlowActionNode[]) => {
        nodes: HogFlowActionNode[]
    }
    setPanelWidth: (panelWidth: number) => {
        panelWidth: number
    }
    setSelectedNodeId: (selectedNodeId: string | null) => {
        selectedNodeId: string | null
    }
    showDropzones: () => {
        value: true
    }
    startCopyingNode: (node: HogFlowActionNode) => {
        node: HogFlowActionNode
    }
    startMovingNode: (node: HogFlowActionNode) => {
        node: HogFlowActionNode
    }
    stopCopyingNode: () => {
        value: true
    }
    stopMovingNode: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface hogFlowEditorLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        nodesById: (nodes: HogFlowActionNode[]) => Record<string, HogFlowActionNode>
        selectedNode: (
            nodes: HogFlowActionNode[],
            selectedNodeId: string | null,
            workflow: HogFlow
        ) => HogFlowActionNode | null
        selectedNodeCanBeDeleted: (
            selectedNode: HogFlowActionNode | null,
            nodes: HogFlowActionNode[],
            edges: HogFlowActionEdge[]
        ) => boolean
        selectedNodeCanBeCopiedOrMoved: (
            selectedNode: HogFlowActionNode | null,
            selectedNodeCanBeDeleted: boolean
        ) => boolean
    }
}

export type hogFlowEditorLogicType = MakeLogicType<
    hogFlowEditorLogicValues,
    hogFlowEditorLogicActions,
    WorkflowLogicProps,
    hogFlowEditorLogicMeta
>

function withSandboxSenderOnInsert(
    action: HogFlowAction,
    values: Pick<
        hogFlowEditorLogicValues,
        'integrations' | 'workflow' | 'canAdoptSandbox' | 'sandboxStatus' | 'currentTeam'
    >,
    editingTemplate: boolean,
    provisionSandboxSender: () => void
): HogFlowAction {
    if (
        hasOwnSender(values.integrations) !== false ||
        !sandboxSenderAllowed(values.workflow, editingTemplate) ||
        !needsSandboxSender(action, values.canAdoptSandbox, getTeamUtmDefaults(values.currentTeam?.workflows_config))
    ) {
        return action
    }
    if (values.sandboxStatus?.integration_id === null) {
        provisionSandboxSender()
    }
    return toSandboxAction(action)
}

export const hogFlowEditorLogic = kea<hogFlowEditorLogicType>([
    props({} as WorkflowLogicProps),
    path((key) => ['scenes', 'hogflows', 'hogFlowEditorLogic', key]),
    key((props) => `hog-flow-editor-${props.id}-${props.templateId || 'default'}-${props.editTemplateId || 'default'}`),
    connect(() => ({
        values: [
            workflowLogic,
            ['workflow', 'edgesByActionId', 'hogFunctionTemplatesById'],
            optOutCategoriesLogic(),
            ['categories', 'categoriesLoading'],
            integrationsLogic,
            ['integrations'],
            teamLogic,
            ['currentTeam'],
            sandboxSenderLogic,
            ['canAdoptSandbox', 'sandboxStatus'],
        ],
        actions: [
            workflowLogic,
            ['setWorkflowInfo', 'setWorkflowAction', 'setWorkflowActionEdges', 'loadWorkflowSuccess'],
            optOutCategoriesLogic(),
            ['loadCategories'],
            sandboxSenderLogic,
            ['provisionSandboxSender'],
        ],
    })),
    actions({
        onNodesDelete: (deleted: HogFlowActionNode[]) => ({ deleted }),
        setDropzoneNodes: (dropzoneNodes: DropzoneNode[]) => ({
            dropzoneNodes,
        }),
        showDropzones: true,
        hideDropzones: true,
        setNodesRaw: (nodes: HogFlowActionNode[]) => ({ nodes }),
        setEdges: (edges: HogFlowActionEdge[]) => ({ edges }),
        setSelectedNodeId: (selectedNodeId: string | null) => ({ selectedNodeId }),
        resetFlowFromHogFlow: (hogFlow: HogFlow) => ({ hogFlow }),
        onDragOver: (event: DragEvent) => ({ event }),
        onDrop: (event?: DragEvent, targetEdge?: HogFlowEdge, joinEdges?: HogFlowEdge[]) => ({
            event,
            targetEdge,
            joinEdges,
        }),
        setNodeToBeAdded: (nodeToBeAdded: CreateActionType | HogFlowActionNode | null) => ({ nodeToBeAdded }),
        setHighlightedDropzoneNodeId: (highlightedDropzoneNodeId: string | null) => ({ highlightedDropzoneNodeId }),
        setMode: (mode: HogFlowEditorMode) => ({ mode }),
        setPanelWidth: (panelWidth: number) => ({ panelWidth }),
        clearPanelWidth: true,
        startCopyingNode: (node: HogFlowActionNode) => ({ node }),
        stopCopyingNode: true,
        copyNodeToHighlightedDropzone: true,
        startMovingNode: (node: HogFlowActionNode) => ({ node }),
        stopMovingNode: true,
        moveNodeToHighlightedDropzone: true,
        moveNodeToEdge: (
            movingNodeId: string,
            targetEdge: HogFlowEdge,
            isBranchJoinDropzone: boolean,
            joinEdges?: HogFlowEdge[]
        ) => ({
            movingNodeId,
            targetEdge,
            isBranchJoinDropzone,
            joinEdges,
        }),
        markUtmSavedAsTeamDefault: (actionId: string, saved: UtmTagValues) => ({ actionId, saved }),
        handlePaneClick: true,
    }),
    reducers(() => ({
        mode: [
            'build' as HogFlowEditorMode,
            {
                setMode: (_, { mode }) => mode,
            },
        ],
        panelWidth: [
            null as number | null,
            { persist: true, storageKey: 'hogFlowEditorPanelWidth' },
            {
                setPanelWidth: (_, { panelWidth }) => panelWidth,
                clearPanelWidth: () => null,
            },
        ],
        nodes: [
            [] as HogFlowActionNode[],
            {
                setNodesRaw: (_, { nodes }) => nodes,
            },
        ],
        dropzoneNodes: [
            [] as DropzoneNode[],
            {
                setDropzoneNodes: (_, { dropzoneNodes }) => dropzoneNodes,
            },
        ],
        highlightedDropzoneNodeId: [
            null as string | null,
            {
                setHighlightedDropzoneNodeId: (_, { highlightedDropzoneNodeId }) => highlightedDropzoneNodeId,
            },
        ],
        edges: [
            [] as HogFlowActionEdge[],
            {
                setEdges: (_, { edges }) => edges,
            },
        ],
        selectedNodeId: [
            null as string | null,
            {
                setSelectedNodeId: (_, { selectedNodeId }) => selectedNodeId,
            },
        ],
        isCopyingNode: [
            false,
            {
                startCopyingNode: () => true,
                stopCopyingNode: () => false,
            },
        ],
        isMovingNode: [
            false,
            {
                startMovingNode: () => true,
                stopMovingNode: () => false,
            },
        ],
        movingNodeId: [
            null as string | null,
            {
                startMovingNode: (_, { node }) => node.id,
                stopMovingNode: () => null,
            },
        ],
        nodeToBeAdded: [
            null as CreateActionType | HogFlowActionNode | null,
            {
                setNodeToBeAdded: (_, { nodeToBeAdded }) => nodeToBeAdded,
                startCopyingNode: (_, { node }) => node.data,
            },
        ],
    })),

    selectors({
        nodesById: [
            (s) => [s.nodes],
            (nodes: HogFlowActionNode[]): Record<string, HogFlowActionNode> => {
                return nodes.reduce(
                    (acc, node) => {
                        acc[node.id] = node
                        return acc
                    },
                    {} as Record<string, HogFlowActionNode>
                )
            },
        ],
        selectedNode: [
            (s) => [s.nodes, s.selectedNodeId, s.workflow],
            (
                nodes: HogFlowActionNode[],
                selectedNodeId: string | null,
                workflow: HogFlow
            ): HogFlowActionNode | null => {
                const node = nodes.find((node) => node.id === selectedNodeId)
                if (node || !selectedNodeId) {
                    return node ?? null
                }

                const action = workflow.actions.find((action) => action.id === selectedNodeId)
                return action
                    ? ({
                          id: action.id,
                          type: 'action',
                          data: action,
                          position: { x: 0, y: 0 },
                          deletable: !['trigger', 'exit'].includes(action.type),
                          selectable: true,
                          draggable: false,
                          connectable: false,
                      } satisfies HogFlowActionNode)
                    : null
            },
        ],
        selectedNodeCanBeDeleted: [
            (s) => [s.selectedNode, s.nodes, s.edges],
            (selectedNode: HogFlowActionNode | null, nodes: HogFlowActionNode[], edges: HogFlowActionEdge[]) => {
                if (!selectedNode) {
                    return false
                }

                const outgoingNodes = getOutgoers(selectedNode, nodes, edges)
                if (outgoingNodes.length === 1) {
                    return true
                }

                return new Set(outgoingNodes.map((node) => node.id)).size === 1
            },
        ],
        selectedNodeCanBeCopiedOrMoved: [
            (s) => [s.selectedNode, s.selectedNodeCanBeDeleted],
            (selectedNode: HogFlowActionNode | null, selectedNodeCanBeDeleted: boolean) => {
                if (!selectedNodeCanBeDeleted) {
                    return false
                }

                return !!selectedNode && !BRANCHING_STEP_TYPES.includes(selectedNode.data.type)
            },
        ],
    }),
    listeners(({ values, actions, props }) => {
        return {
            resetFlowFromHogFlow: ({ hogFlow }) => {
                try {
                    const edges: HogFlowActionEdge[] = hogFlow.edges.map((edge) => ({
                        id: getEdgeId(edge),
                        source: edge.from,
                        target: edge.to,
                        data: { edge },
                    }))

                    const nodes: HogFlowActionNode[] = hogFlow.actions.map((action: HogFlowAction) => {
                        const step = getHogFlowStep(action, values.hogFunctionTemplatesById)

                        // Migrate old function actions to the basic function action type without
                        // writing back onto workflowLogic's action: an in-place mutation corrupts
                        // the workflow subscription's previous-value snapshot, so legacy flows
                        // would never compare deep-equal and would rebuild on every poll.
                        const migratedAction: HogFlowAction =
                            !step && action.type.startsWith('function_')
                                ? ({ ...action, type: 'function' } as HogFlowAction)
                                : action

                        return {
                            id: migratedAction.id,
                            type: 'action',
                            data: migratedAction,
                            position: { x: 0, y: 0 },
                            deletable: !['trigger', 'exit'].includes(migratedAction.type),
                            selectable: true,
                            draggable: false,
                            connectable: false,
                        }
                    })

                    // Keep unchanged references so a save round trip doesn't re-render every step.
                    actions.setEdges(reconcileById(values.edges, edges, (edge) => edge.id))
                    actions.setNodesRaw(reconcileById(values.nodes, nodes, (node) => node.id))
                } catch (error) {
                    console.error('Error resetting flow from hog flow', error)
                    lemonToast.error('Error updating workflow')
                }
            },

            onNodesDelete: ({ deleted }) => {
                if (deleted.some((node) => node.id === values.selectedNodeId)) {
                    actions.setSelectedNodeId(null)
                }

                const deletedNodeIds = deleted.map((node) => node.id)

                // Find all edges connected to the deleted node then reconnect them to avoid orphaned nodes
                const updatedEdges = values.workflow.edges
                    .map((hogFlowEdge) => {
                        if (deletedNodeIds.includes(hogFlowEdge.to)) {
                            // Find the deleted node
                            const deletedNode = deleted.find((node) => node.id === hogFlowEdge.to)
                            if (deletedNode) {
                                const outgoer = values.workflow.edges.find((edge) => edge.from === deletedNode.id)
                                if (outgoer) {
                                    // Change target to the first outgoer
                                    return {
                                        ...hogFlowEdge,
                                        to: outgoer.to,
                                    }
                                }
                            }
                        }
                        return hogFlowEdge
                    })
                    .filter(
                        (hogFlowEdge) =>
                            !deletedNodeIds.includes(hogFlowEdge.from) && !deletedNodeIds.includes(hogFlowEdge.to)
                    )

                // Update workflow actions to match the new flow
                const updatedActions = values.workflow.actions.filter((action) => !deletedNodeIds.includes(action.id))

                actions.setWorkflowInfo({ actions: updatedActions, edges: updatedEdges })
            },

            showDropzones: () => {
                const { nodesById, edges, isMovingNode, movingNodeId } = values

                const dropzoneNodes: DropzoneNode[] = []

                const skipEdgeIds: Set<string> = new Set()
                if (isMovingNode && movingNodeId) {
                    const incomingEdges = edges.filter((e) => e.target === movingNodeId)
                    const outgoingEdges = edges.filter((e) => e.source === movingNodeId)
                    // A move drops the step's outgoing edge before it splits the target, so that edge can never take the step.
                    if (outgoingEdges.length === 1) {
                        skipEdgeIds.add(outgoingEdges[0].id)
                    }
                    // With one incoming edge, placing the step there leaves it where it is.
                    if (incomingEdges.length === 1 && outgoingEdges.length === 1) {
                        skipEdgeIds.add(incomingEdges[0].id)
                    }
                }

                edges.forEach((edge) => {
                    if (skipEdgeIds.has(edge.id)) {
                        return
                    }
                    const sourceNode = nodesById[edge.source]
                    const targetNode = nodesById[edge.target]

                    if (sourceNode && targetNode) {
                        dropzoneNodes.push({
                            id: `dropzone_edge_${edge.id}`,
                            type: 'dropzone',
                            position: { x: 0, y: 0 },
                            data: {
                                edge,
                            },
                            draggable: false,
                            selectable: false,
                        })

                        // If multiple edges share the same target, add a single dropzone near the target node
                        // to allow branch convergence (fan-in). This covers both branch edges directly
                        // from a conditional node and continue edges from downstream nodes in parallel paths.
                        const hasSiblingEdges = edges.filter((e) => e.data?.edge.to === edge.target).length > 1
                        if (hasSiblingEdges) {
                            // Use an ID that we can consistently look up for the branch join point to avoid duplicate dropzones
                            const branchJoinDropzoneTargetId = `dropzone_target_${edge.target}_branch_join`
                            // Avoid duplicating dropzones for multiple branch edges to the same target
                            if (dropzoneNodes.find((n) => n.id === branchJoinDropzoneTargetId)) {
                                return
                            }

                            // Add a dropzone near the target node to allow merging parallel branches
                            dropzoneNodes.push({
                                id: branchJoinDropzoneTargetId,
                                type: 'dropzone',
                                position: { x: 0, y: 0 },
                                data: {
                                    edge,
                                    isBranchJoinDropzone: true,
                                },
                                draggable: false,
                                selectable: false,
                            })
                        }
                    }
                })

                actions.setDropzoneNodes(dropzoneNodes)
            },

            hideDropzones: () => {
                actions.setDropzoneNodes([])
            },

            onDragOver: ({ event }) => {
                event.preventDefault()
                event.dataTransfer.dropEffect = 'move'
            },

            onDrop: ({ event, targetEdge, joinEdges }) => {
                event?.preventDefault()
                const dropzoneNode = values.dropzoneNodes.find((x) => x.id === values.highlightedDropzoneNodeId)

                if (values.nodeToBeAdded && (dropzoneNode || targetEdge)) {
                    const edgeToInsertNodeInto = targetEdge
                        ? ({
                              id: getEdgeId(targetEdge),
                              source: targetEdge.from,
                              target: targetEdge.to,
                          } as HogFlowActionEdge)
                        : dropzoneNode!.data.edge

                    // Check if nodeToBeAdded is a HogFlowActionNode (has 'data' property) or CreateActionType
                    const isHogFlowActionNode = 'data' in values.nodeToBeAdded
                    const partialNewAction = isHogFlowActionNode
                        ? (values.nodeToBeAdded as HogFlowActionNode).data
                        : (values.nodeToBeAdded as CreateActionType)

                    let config = partialNewAction.config
                    if (!isHogFlowActionNode) {
                        // pinned: analytics event name
                        posthog.capture('workflow step added', {
                            step_type: partialNewAction.type,
                            template_id: 'template_id' in config ? config.template_id : undefined,
                        })
                        const dynamicInputs = (partialNewAction as CreateActionType).getDefaultInputs?.()
                        if (dynamicInputs && 'inputs' in config) {
                            config = { ...config, inputs: { ...config.inputs, ...dynamicInputs } } as typeof config
                        }
                    }
                    // Seed the step's inputs with the template defaults at creation time. The input renderer
                    // snapshots its values on mount, so applying defaults after mount leaves the fields blank.
                    if ('template_id' in config && config.template_id) {
                        const template = values.hogFunctionTemplatesById[config.template_id]
                        if (template) {
                            const defaults = templateToConfiguration(template).inputs ?? {}
                            config = {
                                ...config,
                                inputs: { ...defaults, ...('inputs' in config ? config.inputs : {}) },
                            }
                        }
                    }

                    // A copied email keeps its own UTM choice. Without the team loaded the UTM keys stay out, so
                    // the API copies the team defaults on save.
                    if (
                        !isHogFlowActionNode &&
                        partialNewAction.type === 'function_email' &&
                        !('utm_tags_enabled' in config) &&
                        values.currentTeam
                    ) {
                        config = {
                            ...config,
                            ...newEmailUtmConfig(getTeamUtmDefaults(values.currentTeam.workflows_config)),
                        }
                    }

                    if (!isHogFlowActionNode && 'template_id' in config && config.template_id === 'template-email') {
                        const emailInput = config.inputs?.email
                        const team = values.currentTeam
                        const sender = resolveDefaultEmailSender(
                            values.integrations,
                            team && 'workflows_config' in team
                                ? team.workflows_config?.default_email_integration_id
                                : null
                        )
                        if (sender && emailInput?.value && !emailInput.value.from?.integrationId) {
                            config = {
                                ...config,
                                inputs: {
                                    ...config.inputs,
                                    email: {
                                        ...emailInput,
                                        value: {
                                            ...emailInput.value,
                                            from: { ...emailInput.value.from, integrationId: sender.integrationId },
                                        },
                                    },
                                },
                            }
                            // pinned: analytics event name
                            posthog.capture('email sender preselected', { surface: 'workflow', reason: sender.reason })
                        }
                    }

                    let newAction = {
                        id: isHogFlowActionNode
                            ? (values.nodeToBeAdded as HogFlowActionNode).id
                            : `action_${partialNewAction.type}_${uuid()}`,
                        type: partialNewAction.type,
                        name: partialNewAction.name,
                        description: partialNewAction.description,
                        config,
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        ...(!isHogFlowActionNode && (partialNewAction as CreateActionType).output_variable
                            ? { output_variable: (partialNewAction as CreateActionType).output_variable }
                            : {}),
                        ...(!isHogFlowActionNode && (partialNewAction as CreateActionType).on_error
                            ? { on_error: (partialNewAction as CreateActionType).on_error }
                            : {}),
                    } as HogFlowAction

                    if (!isHogFlowActionNode) {
                        newAction = withSandboxSenderOnInsert(newAction, values, !!props.editTemplateId, () =>
                            actions.provisionSandboxSender('inserted_step')
                        )
                    }

                    const step = getHogFlowStep(newAction, values.hogFunctionTemplatesById)

                    const branchEdges = isHogFlowActionNode
                        ? 0
                        : ((partialNewAction as CreateActionType).branchEdges ?? 0)
                    const isBranchJoinDropzone =
                        !!joinEdges || (!targetEdge && (dropzoneNode?.data.isBranchJoinDropzone ?? false))

                    if (!step) {
                        throw new Error(`Step not found for action type: ${newAction}`)
                    }

                    const edgesToBeReplaced = joinEdges
                        ? values.workflow.edges.filter((edge) =>
                              joinEdges.some((joinEdge) => getEdgeId(edge) === getEdgeId(joinEdge))
                          )
                        : isBranchJoinDropzone
                          ? values.workflow.edges.filter((edge) => edge.to === edgeToInsertNodeInto.target)
                          : values.workflow.edges.filter((edge) => getEdgeId(edge) === edgeToInsertNodeInto.id)
                    const newEdges = computeInsertEdges(
                        values.workflow.edges,
                        newAction.id,
                        branchEdges,
                        edgesToBeReplaced
                    )

                    if (!newEdges) {
                        throw new Error('Edge to be replaced not found')
                    }

                    // Auto-create workflow variables if the action has a default output_variable
                    let updatedVariables = values.workflow.variables
                    const outputVars = Array.isArray(newAction.output_variable)
                        ? newAction.output_variable
                        : newAction.output_variable
                          ? [newAction.output_variable]
                          : []

                    for (const outputVar of outputVars) {
                        if (!outputVar.key) {
                            continue
                        }
                        const prefix = outputVar.key
                        if (outputVar.spread) {
                            // Create individual variables for each expected property
                            const spreadFields: [string, string][] = [
                                ['status', 'Status'],
                                ['priority', 'Priority'],
                                ['number', 'Number'],
                                ['channel_source', 'Channel source'],
                                ['last_message_at', 'Last message at'],
                                ['last_message_text', 'Last message text'],
                                ['first_customer_message_text', 'First customer message text'],
                                ['unread_team_count', 'Unread team'],
                                ['unread_customer_count', 'Unread customer'],
                                ['sla', 'SLA'],
                                ['assignee', 'Assignee'],
                                ['url', 'URL'],
                                ['tags', 'Tags'],
                                ['slack_channel_id', 'Slack channel ID'],
                                ['slack_thread_ts', 'Slack thread timestamp'],
                                ['slack_team_id', 'Slack team ID'],
                                ['email_subject', 'Email subject'],
                                ['email_from', 'Email from'],
                                ['email_to', 'Email to'],
                                ['cc_participants', 'CC participants'],
                            ]

                            const newVars = spreadFields
                                .map(([prop, label]) => ({
                                    key: `${prefix}_${prop}`,
                                    label,
                                    type: 'string' as const,
                                    default: '',
                                }))
                                .filter(({ key }) => !updatedVariables?.some((v) => v.key === key))

                            if (newVars.length > 0) {
                                updatedVariables = [...(updatedVariables || []), ...newVars]
                            }
                        } else if (!updatedVariables?.some((v) => v.key === prefix)) {
                            updatedVariables = [
                                ...(updatedVariables || []),
                                {
                                    key: prefix,
                                    label: outputVar.label ?? prefix,
                                    type: 'string' as const,
                                    default: '',
                                },
                            ]
                        }
                    }

                    const oldActions = values.workflow.actions
                    const newActions = [...oldActions.slice(0, -1), newAction, oldActions[oldActions.length - 1]]

                    actions.setWorkflowInfo({ actions: newActions, edges: newEdges, variables: updatedVariables })
                    actions.setNodeToBeAdded(null)
                    actions.setSelectedNodeId(newAction.id)
                }
                // We can clear the dropzones now
                actions.hideDropzones()
            },
            startCopyingNode: () => {
                actions.showDropzones()
            },
            stopCopyingNode: () => {
                actions.hideDropzones()
            },
            copyNodeToHighlightedDropzone: () => {
                const dropzoneNode = values.dropzoneNodes.find((x) => x.id === values.highlightedDropzoneNodeId)
                // Mirror onDrop's guard (both dropzone and node required) so the toast is reliable
                if (!dropzoneNode || !values.nodeToBeAdded) {
                    lemonToast.error("Couldn't copy this step there. Try dropping it on a highlighted spot.")
                    actions.stopCopyingNode()
                    return
                }
                actions.onDrop()
                actions.stopCopyingNode()
            },
            startMovingNode: () => {
                actions.showDropzones()
            },
            stopMovingNode: () => {
                actions.hideDropzones()
            },
            moveNodeToHighlightedDropzone: () => {
                // Changes the edges in one setWorkflowInfo call, unlike copy, so the step keeps its identity.
                const movingNodeId = values.movingNodeId!
                const dropzoneNode = values.dropzoneNodes.find((x) => x.id === values.highlightedDropzoneNodeId)
                if (!dropzoneNode) {
                    lemonToast.error("Couldn't move this step there. Try dropping it on a highlighted spot.")
                    actions.stopMovingNode()
                    return
                }

                const targetHogFlowEdge = dropzoneNode.data.edge.data?.edge
                if (!targetHogFlowEdge) {
                    lemonToast.error("Couldn't move this step there. Try a different spot.")
                    actions.stopMovingNode()
                    return
                }

                const isBranchJoinDropzone = dropzoneNode.data.isBranchJoinDropzone ?? false
                actions.moveNodeToEdge(movingNodeId, targetHogFlowEdge, isBranchJoinDropzone)
                actions.hideDropzones()
                actions.stopMovingNode()
            },
            moveNodeToEdge: ({ movingNodeId, targetEdge, isBranchJoinDropzone, joinEdges }) => {
                // Uses computeMoveEdges (pure function) to manipulate edges in a single
                // setWorkflowInfo call. This preserves node identity while moving a step.
                const newEdges = computeMoveEdges(
                    values.workflow.edges,
                    movingNodeId,
                    targetEdge,
                    isBranchJoinDropzone,
                    joinEdges
                )

                if (!newEdges) {
                    lemonToast.error("Couldn't move this step there. Try a different spot.")
                    return
                }

                actions.setWorkflowInfo({ actions: values.workflow.actions, edges: newEdges })
                actions.setSelectedNodeId(movingNodeId)
            },
            markUtmSavedAsTeamDefault: ({ actionId, saved }) => {
                // The save takes a round trip, so start from the step as it is now to keep edits made meanwhile.
                const latest = values.workflow.actions.find((action) => action.id === actionId)
                if (!latest || latest.type !== 'function_email') {
                    return
                }
                actions.setWorkflowAction(actionId, {
                    ...latest,
                    config: {
                        ...latest.config,
                        utm_params_from_default: utmKeysFollowingSavedDefault(latest.config.utm_params ?? {}, saved),
                    },
                })
            },
            handlePaneClick: () => {
                actions.setSelectedNodeId(null)
                if (values.isCopyingNode) {
                    actions.stopCopyingNode()
                }
                if (values.isMovingNode) {
                    actions.stopMovingNode()
                }
            },
        }
    }),

    subscriptions(({ actions }) => ({
        workflow: (hogFlow?: HogFlow, oldHogFlow?: HogFlow) => {
            // Auto-save round-trips can emit a deep-equal workflow; skipping the rebuild avoids
            // re-deriving every node and edge for no change.
            if (hogFlow && !objectsEqual(hogFlow, oldHogFlow)) {
                actions.resetFlowFromHogFlow(hogFlow)
            }
        },
    })),

    trackedActionToUrl(({ values }) => {
        const syncProperty = (
            key: string,
            value: string | null
        ): [string, Record<string, any>, Record<string, any>] => {
            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    [key]: value,
                },
                router.values.hashParams,
            ]
        }

        return {
            setSelectedNodeId: () => syncProperty('node', values.selectedNodeId ?? null),
            setMode: () => syncProperty('mode', values.mode),
        }
    }),
    urlToAction(({ actions, values }) => {
        const reactToTabChange = (_: any, search: Record<string, string>): void => {
            const { node = null, mode } = search
            if (node !== values.selectedNodeId) {
                actions.setSelectedNodeId(node ?? null)
            }
            if (mode && HOG_FLOW_EDITOR_MODES.includes(mode as HogFlowEditorMode) && mode !== values.mode) {
                actions.setMode(mode as HogFlowEditorMode)
            }
        }

        return {
            [urls.workflow(':id', ':tab')]: reactToTabChange,
        }
    }),
    events(({ actions, values }) => ({
        afterMount: () => {
            actions.resetFlowFromHogFlow(values.workflow)

            const handleKeyDown = (e: KeyboardEvent): void => {
                if (e.key === 'Escape') {
                    if (values.isCopyingNode) {
                        actions.stopCopyingNode()
                    }
                    if (values.isMovingNode) {
                        actions.stopMovingNode()
                    }
                }
            }

            document.addEventListener('keydown', handleKeyDown)

            // Store the handler so we can clean it up
            ;(actions as any)._keydownHandler = handleKeyDown
        },
        beforeUnmount: () => {
            const handler = (actions as any)._keydownHandler
            if (handler) {
                document.removeEventListener('keydown', handler)
            }
        },
    })),
])
