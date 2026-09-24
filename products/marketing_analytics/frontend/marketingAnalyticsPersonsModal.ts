import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import {
    ActorsQuery,
    DataTableNode,
    MARKETING_ANALYTICS_DRILL_DOWN_CONFIG,
    MarketingAnalyticsActorsQuery,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsItem,
    MarketingAnalyticsTableQuery,
    NodeKind,
} from '~/queries/schema/schema-general'

type MarketingAnalyticsActorsRequest = ActorsQuery & { source: MarketingAnalyticsActorsQuery }

function rowValue(record: unknown, column: string): string | null {
    if (!Array.isArray(record)) {
        return null
    }
    const item = record.find(
        (candidate): candidate is MarketingAnalyticsItem =>
            typeof candidate === 'object' && candidate !== null && candidate.key === column
    )
    return item?.value == null ? null : String(item.value)
}

export function marketingAnalyticsActorsQuery({
    conversionGoalId,
    query,
    record,
}: {
    conversionGoalId: string
    query: DataTableNode
    record: unknown
}): MarketingAnalyticsActorsRequest | null {
    const source = query.source as MarketingAnalyticsTableQuery
    const level = source.drillDownLevel ?? MarketingAnalyticsDrillDownLevel.Campaign
    const breakdownValue = rowValue(record, MARKETING_ANALYTICS_DRILL_DOWN_CONFIG[level].columnAlias)
    if (breakdownValue === null) {
        return null
    }

    const sourceQuery: MarketingAnalyticsActorsQuery = {
        kind: NodeKind.MarketingAnalyticsActorsQuery,
        source,
        conversionGoalId,
        breakdown: {
            value: breakdownValue,
            source:
                level === MarketingAnalyticsDrillDownLevel.Campaign ||
                level === MarketingAnalyticsDrillDownLevel.ChannelSource
                    ? (rowValue(record, MarketingAnalyticsBaseColumns.Source) ?? undefined)
                    : undefined,
        },
    }

    return {
        kind: NodeKind.ActorsQuery,
        source: sourceQuery,
    }
}

export function openMarketingAnalyticsPersonsModal({
    conversionGoalId,
    conversionGoalName,
    query,
    record,
}: {
    conversionGoalId: string
    conversionGoalName: string
    query: DataTableNode
    record: unknown
}): void {
    const actorsQuery = marketingAnalyticsActorsQuery({ conversionGoalId, query, record })
    if (!actorsQuery) {
        return
    }

    openPersonsModal({
        title: `${conversionGoalName}: people attributed to ${actorsQuery.source.breakdown.value}`,
        actorsQuery,
    })
}
