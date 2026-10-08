import { matchingFiltersToPropertyGroup } from 'scenes/hog-functions/filters/matchingFilters'

import { EventsNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { BaseMathType, ChartDisplayType } from '~/types'

import { HogFlowAction } from '../types'

type TriggerAction = Extract<HogFlowAction, { type: 'trigger' }>

export type EventTriggerFilters = Extract<TriggerAction['config'], { type: 'event' }>['filters']

/** Days of history the estimate looks back over. */
export const TRIGGER_VOLUME_DAYS = 7

/**
 * Tasks one workflow can create per day by default, mirroring WORKFLOW_TASK_RATE_CAP_PER_DAY in
 * products/tasks/backend/logic/services/workflow_tasks.py.
 *
 * The default, not the effective cap: staff can set another value per project on
 * `TeamWorkflowsConfig.workflow_task_rate_limit_per_day`, and no read API carries it, so the panel
 * cannot know a project's real number. Copy that names it says so.
 */
export const DEFAULT_AI_TASKS_PER_WORKFLOW_PER_DAY = 100

const AI_TASK_TEMPLATE_ID = 'template-posthog-create-task'
const SCOUT_TEMPLATE_ID = 'template-posthog-run-scout'

function countStepsOfTemplate(workflow: { actions?: HogFlowAction[] } | null | undefined, templateId: string): number {
    return (workflow?.actions ?? []).filter(
        (action) => action.type === 'function' && action.config.template_id === templateId
    ).length
}

/**
 * Steps of this workflow that create an AI task, which is what the daily task cap counts.
 *
 * A count rather than a flag, because every step a run reaches creates its own task: two steps
 * reach the cap at half the runs. Branches mean a run does not always reach all of them, so the
 * count is a ceiling, which is the safe side for a cost warning.
 */
export function countAiTaskSteps(workflow?: { actions?: HogFlowAction[] } | null): number {
    return countStepsOfTemplate(workflow, AI_TASK_TEMPLATE_ID)
}

/**
 * Steps of this workflow that start a Signals scout run.
 *
 * Counted apart from AI tasks: a scout run goes to its own endpoint, with its own pause, cooldown
 * and throttle, so it costs AI usage but never counts against the task cap.
 */
export function countScoutSteps(workflow?: { actions?: HogFlowAction[] } | null): number {
    return countStepsOfTemplate(workflow, SCOUT_TEMPLATE_ID)
}

/**
 * Whether the busiest day in the window would pass the default daily task cap.
 *
 * The busiest day, not the weekly average: the backend counts tasks over a trailing 24 hours, so
 * one busy day can break the cap while the average stays under it.
 */
export function exceedsAiTaskLimit(peakPerDay: number, taskSteps: number): boolean {
    return taskSteps > 0 && peakPerDay * taskSteps > DEFAULT_AI_TASKS_PER_WORKFLOW_PER_DAY
}

/**
 * The filters to estimate a trigger's volume from, or null when no estimate is possible.
 *
 * Only triggers that match real PostHog events can be counted. Internal events are not stored, and
 * a trigger with nothing configured yet would count every event in the project.
 */
export function eventTriggerVolumeFilters(action: HogFlowAction): EventTriggerFilters | null {
    if (action.type !== 'trigger' || action.config.type !== 'event') {
        return null
    }
    const filters = action.config.filters ?? {}
    const configured =
        (filters.events?.length ?? 0) > 0 || (filters.actions?.length ?? 0) > 0 || (filters.properties?.length ?? 0) > 0
    return configured ? filters : null
}

/** Daily counts of the events this trigger would have matched over the estimate window. */
export function eventTriggerVolumeQuery(filters: EventTriggerFilters): TrendsQuery {
    return setLatestVersionsOnQuery({
        kind: NodeKind.TrendsQuery,
        filterTestAccounts: filters.filter_test_accounts,
        series: [
            {
                kind: NodeKind.EventsNode,
                event: null,
                name: 'All events',
                math: BaseMathType.TotalCount,
            } satisfies EventsNode,
        ],
        properties: matchingFiltersToPropertyGroup(filters),
        interval: 'day',
        dateRange: {
            date_from: `-${TRIGGER_VOLUME_DAYS}d`,
            // End at yesterday, so the window holds exactly TRIGGER_VOLUME_DAYS whole days. An open
            // end adds today's partial day as an eighth bucket, which the daily average would then
            // divide as though it were complete.
            date_to: '-1d',
        },
        trendsFilter: {
            display: ChartDisplayType.ActionsBar,
        },
        modifiers: {
            // The matcher sees the person properties as they were when the event came in, so count
            // the same way rather than against today's person.
            personsOnEventsMode: 'person_id_no_override_properties_on_events',
        },
    })
}
