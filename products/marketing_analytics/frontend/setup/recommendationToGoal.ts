import { defaultConversionGoalFilter } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/constants'

import { ConversionGoalFilter, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, PropertyMathType } from '~/types'

import type { ConversionRecommendationApi } from '../generated/api.schemas'

export function recommendationToGoal(recommendation: ConversionRecommendationApi): ConversionGoalFilter {
    const { candidate, intent, amount_property } = recommendation
    const isRevenue = intent === 'revenue' && !!amount_property
    const source =
        candidate.kind === 'ActionsNode'
            ? { kind: NodeKind.ActionsNode as const, id: candidate.action_id ?? 0 }
            : { kind: NodeKind.EventsNode as const, event: candidate.event ?? '' }

    return {
        ...source,
        name: candidate.name,
        conversion_goal_id: '',
        conversion_goal_name: recommendation.name,
        schema_map: { ...defaultConversionGoalFilter.schema_map },
        properties: [],
        math: isRevenue ? PropertyMathType.Sum : BaseMathType.TotalCount,
        ...(isRevenue ? { math_property: amount_property } : {}),
        counts_as_revenue: isRevenue,
        counts_as_customer: intent === 'customer',
    }
}
