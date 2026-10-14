import {
    DataTableNode,
    MARKETING_ANALYTICS_DRILL_DOWN_CONFIG,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsItem,
    MarketingAnalyticsTableQuery,
} from '~/queries/schema/schema-general'

import { ConversionRecordingsRequestApi } from './generated/api.schemas'

export interface ConversionRecordingsSelection {
    tableKey: string
    request: ConversionRecordingsRequestApi
    goalName: string
}

function rowColumns(source: MarketingAnalyticsTableQuery): string[] {
    const level = source.drillDownLevel ?? MarketingAnalyticsDrillDownLevel.Campaign
    if (level === MarketingAnalyticsDrillDownLevel.Ad || level === MarketingAnalyticsDrillDownLevel.AdGroup) {
        return []
    }
    const columns = [MARKETING_ANALYTICS_DRILL_DOWN_CONFIG[level].columnAlias]
    if (
        level === MarketingAnalyticsDrillDownLevel.Campaign ||
        level === MarketingAnalyticsDrillDownLevel.ChannelSource
    ) {
        columns.push('Source')
    }
    if (level === MarketingAnalyticsDrillDownLevel.Campaign && !source.compareFilter?.compare) {
        columns.push('ID')
    }
    return columns
}

export function conversionRecordingsTableQuery(query: DataTableNode, enabled: boolean): DataTableNode {
    const source = query.source as MarketingAnalyticsTableQuery
    if (!enabled || !source.select?.length) {
        return query
    }
    const hidden = rowColumns(source).filter((column) => !source.select?.includes(column))
    if (!hidden.length) {
        return query
    }
    return {
        ...query,
        source: { ...source, select: [...source.select, ...hidden] },
        hiddenColumns: [...(query.hiddenColumns ?? []), ...hidden],
    }
}

export function restoreConversionRecordingsColumns(updated: DataTableNode, original: DataTableNode): DataTableNode {
    const source = original.source as MarketingAnalyticsTableQuery
    if (!source.select?.length) {
        return updated
    }
    const hidden = rowColumns(source).filter((column) => !source.select?.includes(column))
    const updatedSource = updated.source as MarketingAnalyticsTableQuery
    return {
        ...updated,
        source: { ...updatedSource, select: updatedSource.select?.filter((column) => !hidden.includes(column)) },
        hiddenColumns: original.hiddenColumns,
    }
}

function rowValue(record: unknown, column: string): string | undefined {
    if (!Array.isArray(record)) {
        return undefined
    }
    const cell = record.find((item): item is MarketingAnalyticsItem => item?.key === column)
    return cell?.value == null ? undefined : String(cell.value)
}

export function conversionRecordingsRequest(
    source: MarketingAnalyticsTableQuery,
    record: unknown,
    goalId: string
): ConversionRecordingsRequestApi | null {
    const level = source.drillDownLevel ?? MarketingAnalyticsDrillDownLevel.Campaign
    if (level === MarketingAnalyticsDrillDownLevel.Ad || level === MarketingAnalyticsDrillDownLevel.AdGroup) {
        return null
    }
    const group = rowValue(record, MARKETING_ANALYTICS_DRILL_DOWN_CONFIG[level].columnAlias)
    const sourceName = rowValue(record, 'Source')
    const needsSource =
        level === MarketingAnalyticsDrillDownLevel.Campaign || level === MarketingAnalyticsDrillDownLevel.ChannelSource
    if (group === undefined || (needsSource && sourceName === undefined)) {
        return null
    }
    return {
        source: source as ConversionRecordingsRequestApi['source'],
        goal_id: goalId,
        group,
        source_name: needsSource ? sourceName : '',
        campaign_id:
            level === MarketingAnalyticsDrillDownLevel.Campaign && !source.compareFilter?.compare
                ? rowValue(record, 'ID') || '-'
                : undefined,
    }
}
