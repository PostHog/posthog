import { uuid } from 'lib/utils/dom'

import type { HogFlow, HogFlowAction, HogFlowEdge } from '../types'

export const SHOW_SURVEY_TEMPLATE_ID = 'template-posthog-show-survey'
export const HIDE_SURVEY_TEMPLATE_ID = 'template-posthog-hide-survey'
export const SURVEY_SENT_EVENT = 'survey sent'
export const SURVEY_RESPONSE_MAX_WAIT = '3d'

type WorkflowGraph = Pick<HogFlow, 'actions' | 'edges'>
type FunctionConfig = Extract<HogFlowAction, { type: 'function' }>['config']

function surveySentEntry(
    surveyId: string
): NonNullable<Extract<HogFlowAction, { type: 'wait_until_condition' }>['config']['events']>[number] {
    return {
        name: 'Survey answered',
        filters: {
            events: [
                {
                    id: SURVEY_SENT_EVENT,
                    name: SURVEY_SENT_EVENT,
                    type: 'events',
                    properties: [{ key: '$survey_id', type: 'event', operator: 'exact', value: [surveyId] }],
                },
            ],
        },
    }
}

function surveyIdFromFilter(properties: { key?: string; value?: unknown }[] | undefined): string | null {
    const value = properties?.find((property) => property.key === '$survey_id')?.value
    const surveyId = Array.isArray(value) ? value[0] : value
    return typeof surveyId === 'string' && surveyId ? surveyId : null
}

export function getAwaitedSurveyId(action: HogFlowAction | undefined): string | null {
    if (action?.type !== 'wait_until_condition') {
        return null
    }
    const surveySentEvents = (action.config.events ?? [])
        .flatMap((entry) => entry.filters?.events ?? [])
        .filter((event) => event.id === SURVEY_SENT_EVENT)
    return surveySentEvents.map((event) => surveyIdFromFilter(event.properties)).find(Boolean) ?? null
}

export function getNextAction(workflow: WorkflowGraph, actionId: string): HogFlowAction | undefined {
    const outgoing = workflow.edges.filter((edge) => edge.from === actionId)
    if (outgoing.length !== 1) {
        return undefined
    }
    return workflow.actions.find((action) => action.id === outgoing[0].to)
}

export function retargetSurveyResponseWait(
    workflow: WorkflowGraph,
    showSurveyActionId: string,
    surveyId: string,
    now: number = Date.now()
): WorkflowGraph | null {
    const waitAction = getNextAction(workflow, showSurveyActionId)
    const previousSurveyId = getAwaitedSurveyId(waitAction)
    if (!waitAction || !previousSurveyId) {
        return null
    }
    const hideActionIds = new Set(workflow.edges.filter((edge) => edge.from === waitAction.id).map((edge) => edge.to))

    const actions = workflow.actions.map((action): HogFlowAction => {
        if (action.id === waitAction.id && action.type === 'wait_until_condition') {
            const events = (action.config.events ?? []).map((entry) =>
                entry.filters?.events?.some((event) => event.id === SURVEY_SENT_EVENT)
                    ? surveySentEntry(surveyId)
                    : entry
            )
            return { ...action, config: { ...action.config, events }, updated_at: now }
        }
        if (
            hideActionIds.has(action.id) &&
            action.type === 'function' &&
            action.config.template_id === HIDE_SURVEY_TEMPLATE_ID &&
            action.config.inputs?.survey_id?.value === previousSurveyId
        ) {
            const inputs = {
                ...action.config.inputs,
                survey_id: { ...action.config.inputs.survey_id, value: surveyId },
            }
            return { ...action, config: { ...action.config, inputs }, updated_at: now }
        }
        return action
    })
    return { actions, edges: workflow.edges }
}

export function insertSurveyResponseWait(
    workflow: WorkflowGraph,
    showSurveyActionId: string,
    surveyId: string,
    hideSurveyConfig: FunctionConfig,
    now: number = Date.now()
): (WorkflowGraph & { waitActionId: string }) | null {
    const outgoing = workflow.edges.filter((edge) => edge.from === showSurveyActionId)
    if (outgoing.length !== 1 || outgoing[0].type !== 'continue') {
        return null
    }
    const nextActionId = outgoing[0].to

    const waitAction = {
        id: `action_wait_until_condition_${uuid()}`,
        type: 'wait_until_condition',
        name: 'Wait for survey answer',
        description: 'Continues when the person answers the survey, or when the wait runs out.',
        config: {
            condition: { name: 'Survey answered', filters: null },
            events: [surveySentEntry(surveyId)],
            max_wait_duration: SURVEY_RESPONSE_MAX_WAIT,
        },
        created_at: now,
        updated_at: now,
    } as HogFlowAction

    const hideAction = {
        id: `action_function_${uuid()}`,
        type: 'function',
        name: 'Hide survey',
        description: 'Stops showing the survey to this person.',
        config: {
            ...hideSurveyConfig,
            template_id: HIDE_SURVEY_TEMPLATE_ID,
            inputs: { ...hideSurveyConfig.inputs, survey_id: { value: surveyId } },
        },
        created_at: now,
        updated_at: now,
    } as HogFlowAction

    const edges: HogFlowEdge[] = [
        ...workflow.edges.filter((edge) => edge !== outgoing[0]),
        { from: showSurveyActionId, to: waitAction.id, type: 'continue' },
        { from: waitAction.id, to: hideAction.id, type: 'branch', index: 0 },
        { from: waitAction.id, to: hideAction.id, type: 'continue' },
        { from: hideAction.id, to: nextActionId, type: 'continue' },
    ]

    const actions = [...workflow.actions.slice(0, -1), waitAction, hideAction, ...workflow.actions.slice(-1)]
    return { actions, edges, waitActionId: waitAction.id }
}
