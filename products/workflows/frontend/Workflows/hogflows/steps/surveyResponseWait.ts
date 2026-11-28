import { uuid } from 'lib/utils/dom'

import { SurveyEventName, SurveyEventProperties } from '~/types'

import type { HogFlow, HogFlowAction, HogFlowEdge } from '../types'

export const SHOW_SURVEY_TEMPLATE_ID = 'template-posthog-show-survey'
export const HIDE_SURVEY_TEMPLATE_ID = 'template-posthog-hide-survey'
export const SURVEY_RESPONSE_MAX_WAIT = '3d'

type WorkflowGraph = Pick<HogFlow, 'actions' | 'edges'>
type FunctionInputs = Extract<HogFlowAction, { type: 'function' }>['config']['inputs']
type SurveyWaitEntry = NonNullable<Extract<HogFlowAction, { type: 'wait_until_condition' }>['config']['events']>[number]

function surveySentEvent(surveyId: string, completed: 'true' | 'unset'): Record<string, unknown> {
    return {
        id: SurveyEventName.SENT,
        name: SurveyEventName.SENT,
        type: 'events',
        properties: [
            { key: SurveyEventProperties.SURVEY_ID, type: 'event', operator: 'exact', value: [surveyId] },
            completed === 'true'
                ? { key: SurveyEventProperties.SURVEY_COMPLETED, type: 'event', operator: 'exact', value: true }
                : {
                      key: SurveyEventProperties.SURVEY_COMPLETED,
                      type: 'event',
                      operator: 'is_not_set',
                      value: 'is_not_set',
                  },
        ],
    }
}

// With partial responses on, posthog-js sends "survey sent" after every question with
// `$survey_completed: false`, so only a true or missing value counts as an answer.
function surveySentEntry(surveyId: string): SurveyWaitEntry {
    return {
        name: 'Survey answered',
        filters: {
            events: [surveySentEvent(surveyId, 'true'), surveySentEvent(surveyId, 'unset')],
        },
    } as SurveyWaitEntry
}

function surveyIdFromFilter(properties: { key?: string; value?: unknown }[] | undefined): string | null {
    const value = properties?.find((property) => property.key === SurveyEventProperties.SURVEY_ID)?.value
    const surveyId = Array.isArray(value) ? value[0] : value
    return typeof surveyId === 'string' && surveyId ? surveyId : null
}

export function getAwaitedSurveyId(action: HogFlowAction | undefined): string | null {
    if (action?.type !== 'wait_until_condition') {
        return null
    }
    const surveySentEvents = (action.config.events ?? [])
        .flatMap((entry) => entry.filters?.events ?? [])
        .filter((event) => event.id === SurveyEventName.SENT)
    return surveySentEvents.map((event) => surveyIdFromFilter(event.properties)).find(Boolean) ?? null
}

export function canInsertSurveyResponseWait(workflow: WorkflowGraph, showSurveyActionId: string): boolean {
    const outgoing = workflow.edges.filter((edge) => edge.from === showSurveyActionId)
    return outgoing.length === 1 && outgoing[0].type === 'continue'
}

export function getNextAction(workflow: WorkflowGraph, actionId: string): HogFlowAction | undefined {
    const outgoing = workflow.edges.filter((edge) => edge.from === actionId)
    if (outgoing.length !== 1) {
        return undefined
    }
    return workflow.actions.find((action) => action.id === outgoing[0].to)
}

function actionIdsAfter(workflow: WorkflowGraph, actionId: string): Set<string> {
    const seen = new Set<string>()
    const queue = [actionId]
    while (queue.length) {
        const current = queue.shift()!
        for (const edge of workflow.edges) {
            if (edge.from === current && !seen.has(edge.to)) {
                seen.add(edge.to)
                queue.push(edge.to)
            }
        }
    }
    return seen
}

function retargetEntry(entry: SurveyWaitEntry, previousSurveyId: string, surveyId: string): SurveyWaitEntry {
    const events = entry.filters?.events?.map(
        (event: { id?: string; properties?: { key?: string; value?: unknown }[] }) =>
            event.id === SurveyEventName.SENT && surveyIdFromFilter(event.properties) === previousSurveyId
                ? {
                      ...event,
                      properties: event.properties?.map((property) =>
                          property.key === SurveyEventProperties.SURVEY_ID
                              ? { ...property, value: [surveyId] }
                              : property
                      ),
                  }
                : event
    )
    return events ? { ...entry, filters: { ...entry.filters, events } } : entry
}

export function retargetSurveyResponseWait(
    workflow: WorkflowGraph,
    showSurveyActionId: string,
    surveyId: string
): WorkflowGraph | null {
    const now = Date.now()
    const waitAction = getNextAction(workflow, showSurveyActionId)
    const previousSurveyId = getAwaitedSurveyId(waitAction)
    if (!waitAction || !previousSurveyId) {
        return null
    }
    const downstreamIds = actionIdsAfter(workflow, waitAction.id)

    const actions = workflow.actions.map((action): HogFlowAction => {
        if (action.id === waitAction.id && action.type === 'wait_until_condition') {
            const events = (action.config.events ?? []).map((entry) => retargetEntry(entry, previousSurveyId, surveyId))
            return { ...action, config: { ...action.config, events }, updated_at: now }
        }
        if (
            downstreamIds.has(action.id) &&
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
    hideSurveyInputs: FunctionInputs
): (WorkflowGraph & { waitActionId: string }) | null {
    if (!canInsertSurveyResponseWait(workflow, showSurveyActionId)) {
        return null
    }
    const now = Date.now()
    const outgoing = workflow.edges.filter((edge) => edge.from === showSurveyActionId)
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
            template_id: HIDE_SURVEY_TEMPLATE_ID,
            inputs: { ...hideSurveyInputs, survey_id: { value: surveyId } },
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
