import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { EventsNode, FunnelsQuery, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { HogQLQueryString, hogql } from '~/queries/utils'
import {
    AnyPropertyFilter,
    BaseMathType,
    FunnelConversionWindowTimeUnit,
    FunnelVizType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import type { HogFlow } from './hogflows/types'

// Emitted once per run when the run starts, but only for workflows with a conversion goal — so the
// absence of these events means "no goal configured", not "nobody enrolled".
const ENROLLED_EVENT = '$workflows_enrolled'
const CONVERSION_EVENT = '$workflows_conversion'

// A conversion goal with no window means "however long after"; a funnel always needs a finite one, so
// this stands in for unbounded. Long enough that no real goal reaches it, short enough to stay cheap.
const UNBOUNDED_WINDOW_DAYS = 365

export type WorkflowConversionRequest = {
    workflowId: string
    dateFrom: string
    dateTo: string
    interval: 'day' | 'hour' | 'minute'
    // null means no window: a run counts as converted whenever the conversion lands, however long after.
    windowMinutes: number | null
    conversion: HogFlow['conversion']
}

export type WorkflowConversionSeries = {
    labels: string[]
    // People who entered the workflow in each bucket, and how many of those went on to convert. Both
    // are keyed on the bucket the person ENTERED in, not the one they converted in — that's what makes
    // a bucket's rate answerable ("of the people who entered that day, how many converted?").
    enrolled: number[]
    converted: number[]
}

// Whether any part of the goal is met by something the person does, rather than by their properties
// changing. That decides which of the two counting paths below can see the conversion.
export function hasEventGoal(conversion: HogFlow['conversion']): boolean {
    const goalEvents: any[] = conversion?.events?.[0]?.filters?.events ?? []
    const goalActions: any[] = conversion?.events?.[0]?.filters?.actions ?? []
    return goalEvents.some((event) => event.id) || goalActions.some((action) => action.id)
}

/**
 * The goal as a funnel step: the events that mean the person converted.
 *
 * Event- and action-based goals are matched against the raw event stream, so they are counted from
 * what the person actually did rather than from a `$workflows_conversion` event. That event is only
 * emitted while a run is parked in cyclotron, so a workflow with no delay step never emits one and
 * reads as 0% conversion however many people converted.
 *
 * A goal that also has property conditions keeps them here as one more way to qualify, which catches
 * a property conversion recorded on a later pass. Property-only goals never reach this path.
 *
 * A funnel step takes a flat, AND-ed property list — there is no per-step OR group in the schema — so
 * a goal naming several events is expressed as one unnamed step whose event identity is an OR'd HogQL
 * condition. Filters attached to an individual event can then only be AND-ed across the whole step,
 * which is stricter than the goal; a goal that names a single event (the shape the editor produces by
 * default) keeps exact fidelity because there is nothing to combine it with.
 */
export function buildConversionGoalStep(conversion: HogFlow['conversion'], workflowId: string): EventsNode | null {
    const goalEvents: any[] = conversion?.events?.[0]?.filters?.events ?? []
    const goalActions: any[] = conversion?.events?.[0]?.filters?.actions ?? []
    const goalProperties: AnyPropertyFilter[] = conversion?.events?.[0]?.filters?.properties ?? []
    const hasPropertyGoal = Array.isArray(conversion?.filters) && conversion.filters.length > 0

    // Each entry is one way to meet the goal, so their event identities are OR'd.
    const identities: string[] = []
    const properties: AnyPropertyFilter[] = [...goalProperties]

    for (const event of goalEvents) {
        if (!event.id) {
            continue
        }
        identities.push(hogql`event = ${event.id}`)
        properties.push(...((event.properties ?? []) as AnyPropertyFilter[]))
    }

    for (const action of goalActions) {
        if (!action.id) {
            continue
        }
        identities.push(hogql`matchesAction(${parseInt(action.id)})`)
        properties.push(...((action.properties ?? []) as AnyPropertyFilter[]))
    }

    if (hasPropertyGoal) {
        identities.push(
            hogql`(event = ${CONVERSION_EVENT} AND properties.$workflow_id = ${workflowId} AND properties.$workflow_conversion_type = 'property')`
        )
    }

    if (identities.length === 0) {
        return null
    }

    return {
        kind: NodeKind.EventsNode,
        // Named only when the goal is a single event, so the step reads as that event everywhere the
        // query is inspected; an OR needs the unnamed form with the identity as a condition.
        event: goalEvents.length === 1 && !goalActions.length && !hasPropertyGoal ? goalEvents[0].id : null,
        properties:
            identities.length === 1 && goalEvents.length === 1 && !goalActions.length && !hasPropertyGoal
                ? properties
                : [...properties, { type: PropertyFilterType.HogQL, key: identities.join(' OR ') }],
    }
}

/**
 * Property-only goals, counted by pairing each run's enrollment with its conversion on the run id.
 *
 * Both events are emitted by the executor itself, so the pairing is exact and needs no ordering
 * between them. Runs are bucketed by when they enrolled, matching the funnel path.
 */
async function loadPropertyGoalSeries(
    request: WorkflowConversionRequest,
    timezone: string
): Promise<WorkflowConversionSeries> {
    const windowClause = hogql.raw(
        request.windowMinutes && request.windowMinutes > 0
            ? `AND converted_at <= enrolled_at + toIntervalMinute(${Math.floor(request.windowMinutes)})`
            : ''
    )

    const query = hogql`
        SELECT
            dateTrunc(${request.interval}, toTimeZone(enrolled_at, ${timezone}), ${timezone}) AS bucket,
            count() AS enrolled,
            countIf(converted_at >= enrolled_at ${windowClause}) AS converted
        FROM (
            SELECT
                properties.$workflow_run_id AS run_id,
                minIf(timestamp, event = ${ENROLLED_EVENT}) AS enrolled_at,
                minIf(timestamp, event = ${CONVERSION_EVENT}) AS converted_at
            FROM events
            WHERE event IN (${ENROLLED_EVENT}, ${CONVERSION_EVENT})
                AND properties.$workflow_id = ${request.workflowId}
                AND properties.$workflow_run_id != ''
                AND timestamp >= toDateTime(${request.dateFrom})
            GROUP BY run_id
            -- A conversion whose run started before the range must not invent a denominator row.
            HAVING enrolled_at > toDateTime(0)
                AND enrolled_at < toDateTime(${request.dateTo})
        )
        GROUP BY bucket
        ORDER BY bucket
    ` as HogQLQueryString

    const response = await api.queryHogQL(
        query,
        { scene: 'Workflow', productKey: 'messaging' },
        {
            refresh: 'force_blocking',
        }
    )

    const labels: string[] = []
    const enrolled: number[] = []
    const converted: number[] = []
    for (const [bucket, enrolledCount, convertedCount] of response.results ?? []) {
        labels.push(
            dayjs(bucket)
                .tz(timezone)
                .format(request.interval === 'day' ? 'YYYY-MM-DD' : 'YYYY-MM-DD HH:mm')
        )
        enrolled.push(enrolledCount ?? 0)
        converted.push(convertedCount ?? 0)
    }
    return { labels, enrolled, converted }
}

/**
 * Conversion rate as a two-step funnel: entering the workflow, then meeting the goal.
 *
 * The funnel counts people, not runs — a person enrolled twice in a bucket is one entrant. That is
 * what makes a goal measurable at all here: the goal event carries no run id, so there is nothing to
 * pair it to a specific run with, and the person is the only join key both sides share.
 *
 * Buckets are keyed on the entrance period, so a bucket answers "of the people who entered then, how
 * many converted?" — which is what the tile above the chart claims.
 */
export async function loadWorkflowConversionSeries(
    request: WorkflowConversionRequest,
    timezone: string
): Promise<WorkflowConversionSeries> {
    const goalStep = buildConversionGoalStep(request.conversion, request.workflowId)
    if (!goalStep) {
        return { labels: [], enrolled: [], converted: [] }
    }

    // A goal made only of person-property conditions is evaluated inline as the run executes, so its
    // conversion event is stamped in the same instant as the enrollment event. A funnel needs its
    // second step to come after the first, so it would score every one of those runs as unconverted.
    // They carry a run id, which pairs exactly, so count them that way instead.
    if (!hasEventGoal(request.conversion)) {
        return await loadPropertyGoalSeries(request, timezone)
    }

    const windowMinutes =
        request.windowMinutes && request.windowMinutes > 0
            ? Math.floor(request.windowMinutes)
            : UNBOUNDED_WINDOW_DAYS * 24 * 60

    // Someone entering at the end of the range still has the whole window to convert, and that
    // conversion belongs to their entrance bucket. Asking for the window past `dateTo` lets the funnel
    // see it; the trailing buckets it also generates are dropped below.
    const dateToWithWindow = dayjs(request.dateTo).add(windowMinutes, 'minute')

    const query: FunnelsQuery = {
        kind: NodeKind.FunnelsQuery,
        tags: { scene: 'Workflow', productKey: 'messaging' },
        interval: request.interval,
        dateRange: { date_from: request.dateFrom, date_to: dateToWithWindow.toISOString() },
        series: [
            {
                kind: NodeKind.EventsNode,
                event: ENROLLED_EVENT,
                properties: [
                    {
                        type: PropertyFilterType.Event,
                        key: '$workflow_id',
                        operator: PropertyOperator.Exact,
                        value: request.workflowId,
                    },
                ],
            },
            goalStep,
        ],
        funnelsFilter: {
            funnelVizType: FunnelVizType.Trends,
            funnelWindowInterval: windowMinutes,
            funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Minute,
        },
    }

    // The funnel reports each bucket's conversion rate but not the two counts behind it, so the
    // entrants are counted alongside it and the conversions are read back off the rate. Both sides
    // count unique people over the same buckets, so they describe the same set.
    const entrantsQuery: TrendsQuery = {
        kind: NodeKind.TrendsQuery,
        tags: { scene: 'Workflow', productKey: 'messaging' },
        interval: request.interval,
        dateRange: { date_from: request.dateFrom, date_to: request.dateTo },
        series: [
            {
                kind: NodeKind.EventsNode,
                event: ENROLLED_EVENT,
                math: BaseMathType.UniqueUsers,
                properties: [
                    {
                        type: PropertyFilterType.Event,
                        key: '$workflow_id',
                        operator: PropertyOperator.Exact,
                        value: request.workflowId,
                    },
                ],
            },
        ],
    }

    const [funnelResponse, entrantsResponse] = await Promise.all([
        api.query(query, { refresh: 'force_blocking' }),
        api.query(entrantsQuery, { refresh: 'force_blocking' }),
    ])

    // `days` are the bucket keys the funnel cut, `data` the rate in each. Both come back on the
    // widened range, so the buckets past the request are dropped against the entrant series.
    const funnelSeries = funnelResponse.results?.[0] ?? { days: [], data: [] }
    const rateByDay = new Map<string, number>(
        (funnelSeries.days ?? []).map((day: string, index: number) => [day, funnelSeries.data?.[index] ?? 0])
    )

    const entrantSeries = entrantsResponse.results?.[0] ?? { days: [], data: [] }
    const labels: string[] = []
    const enrolled: number[] = []
    const converted: number[] = []

    ;(entrantSeries.days ?? []).forEach((day: string, index: number) => {
        const entrants = entrantSeries.data?.[index] ?? 0
        labels.push(
            dayjs(day)
                .tz(timezone)
                .format(request.interval === 'day' ? 'YYYY-MM-DD' : 'YYYY-MM-DD HH:mm')
        )
        enrolled.push(entrants)
        converted.push(Math.round(((rateByDay.get(day) ?? 0) / 100) * entrants))
    })

    return { labels, enrolled, converted }
}
