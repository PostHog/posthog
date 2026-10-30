import type { DisplayableEntity } from 'lib/components/EntityFilterInfo'
import { ensureStringIsNotBlank } from 'lib/utils/strings'
import {
    SeriesNode,
    isEventsSeriesNode,
    isGroupSeriesNode,
    isWarehouseSeriesNode,
    seriesNodeKey,
} from 'scenes/insights/filters/ActionFilter/seriesNode'

import type { FunnelsQuery } from '~/queries/schema/schema-general'
import { type FunnelStep, StepOrderValue } from '~/types'

/**
 * The query series of the funnel step at `stepIndex`, carrying the name the step displays under. A step's index is
 * its series index on ordered and strict funnels. Pass the index of the step, not the `order` of a nested breakdown
 * row, because a nested row's `order` holds a breakdown rank.
 *
 * Null on an unordered funnel, whose step N counts the people who completed any N of the series, and on a step whose
 * series the query no longer holds, which happens while results for an edited query load.
 */
export function getFunnelStepSeries(
    querySource: FunnelsQuery | null | undefined,
    stepIndex: number,
    step: Pick<FunnelStep, 'name'>
): SeriesNode | null {
    if (!querySource || querySource.funnelsFilter?.funnelOrderType === StepOrderValue.UNORDERED) {
        return null
    }
    const node = querySource.series[stepIndex] as SeriesNode | undefined
    return node ? withDisplayName(node, step) : null
}

export function getFunnelStepEntity(
    querySource: FunnelsQuery | null | undefined,
    stepIndex: number,
    step: Pick<FunnelStep, 'name' | 'custom_name'>
): DisplayableEntity {
    return (
        getFunnelStepSeries(querySource, stepIndex, step) ?? {
            id: null,
            name: step.name,
            custom_name: step.custom_name,
        }
    )
}

export function isRepeatedFunnelStep(series: SeriesNode | null, previousSeries: SeriesNode | null): boolean {
    if (!series || !previousSeries || series.kind !== previousSeries.kind) {
        return false
    }
    if (isGroupSeriesNode(series) && isGroupSeriesNode(previousSeries)) {
        return (
            series.nodes.length === previousSeries.nodes.length &&
            series.nodes.every((member, index) => isRepeatedFunnelStep(member, previousSeries.nodes[index]))
        )
    }
    return seriesNodeKey(series) === seriesNodeKey(previousSeries)
}

/**
 * A series saved without a `name` displays the key it queries, as the runner names the step. The query does not hold
 * the name of an action, so an action or a group takes the step's name, which the runner builds with action names
 * from the database.
 */
function withDisplayName(node: SeriesNode, step: Pick<FunnelStep, 'name'>): SeriesNode {
    if (ensureStringIsNotBlank(node.name)) {
        return node
    }
    const name = isEventsSeriesNode(node) ? node.event : isWarehouseSeriesNode(node) ? node.table_name : step.name
    return name ? { ...node, name } : node
}
