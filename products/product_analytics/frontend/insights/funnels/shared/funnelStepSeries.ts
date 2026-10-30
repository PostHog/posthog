import type { DisplayableEntity } from 'lib/components/EntityFilterInfo'
import { ensureStringIsNotBlank } from 'lib/utils/strings'
import {
    SeriesNode,
    isActionsSeriesNode,
    isEventsSeriesNode,
    isGroupSeriesNode,
    isWarehouseSeriesNode,
    seriesNodeKey,
} from 'scenes/insights/filters/ActionFilter/seriesNode'

import type { FunnelsQuery } from '~/queries/schema/schema-general'
import { type FunnelStep, StepOrderValue } from '~/types'

// Takes the step index because a nested breakdown row's `order` holds a breakdown rank. An unordered funnel's step N
// counts people who completed any N series, so it has no series.
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

// The query holds the action name saved with the funnel, and the runner names the step from the database. So an action,
// and a group without a name, take the step's name.
function withDisplayName(node: SeriesNode, step: Pick<FunnelStep, 'name'>): SeriesNode {
    const stepName = ensureStringIsNotBlank(step.name)
    if (isActionsSeriesNode(node) && stepName) {
        return { ...node, name: stepName }
    }
    if (ensureStringIsNotBlank(node.name)) {
        return node
    }
    const name = isEventsSeriesNode(node) ? node.event : isWarehouseSeriesNode(node) ? node.table_name : step.name
    return name ? { ...node, name } : node
}
