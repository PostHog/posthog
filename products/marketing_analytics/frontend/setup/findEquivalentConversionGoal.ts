import { objectsEqual } from 'lib/utils/objects'
import { defaultConversionGoalFilter } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/constants'

import { ConversionGoalFilter, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType } from '~/types'

function measurement(goal: ConversionGoalFilter): Record<string, unknown> {
    return {
        kind: goal.kind,
        source: goal.kind === NodeKind.EventsNode ? goal.event : goal.id,
        math: goal.math ?? BaseMathType.TotalCount,
        math_property: goal.math_property,
        math_property_type: goal.math_property_type,
        math_property_revenue_currency: goal.math_property_revenue_currency,
        math_multiplier: goal.math_multiplier ?? 1,
        math_hogql: goal.math_hogql,
        math_group_type_index: goal.math_group_type_index,
        properties: goal.properties ?? [],
        fixedProperties: goal.fixedProperties ?? [],
        counts_as_revenue: !!goal.counts_as_revenue,
        counts_as_customer: !!goal.counts_as_customer,
        schema_map: { ...defaultConversionGoalFilter.schema_map, ...goal.schema_map },
    }
}

export function findConversionGoalForSource(
    goals: ConversionGoalFilter[],
    candidate: ConversionGoalFilter
): ConversionGoalFilter | undefined {
    return goals.find((goal) =>
        candidate.kind === NodeKind.EventsNode
            ? goal.kind === NodeKind.EventsNode && !!candidate.event && goal.event === candidate.event
            : candidate.kind === NodeKind.ActionsNode &&
              goal.kind === NodeKind.ActionsNode &&
              !!candidate.id &&
              goal.id === candidate.id
    )
}

export function findEquivalentConversionGoal(
    goals: ConversionGoalFilter[],
    candidate: ConversionGoalFilter
): ConversionGoalFilter | undefined {
    if (candidate.kind === NodeKind.DataWarehouseNode) {
        return undefined
    }
    const candidateMeasurement = measurement(candidate)
    return goals.find((goal) => objectsEqual(measurement(goal), candidateMeasurement))
}
