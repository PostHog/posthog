import {
    MARKETING_ANALYTICS_DRILL_DOWN_CONFIG,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsItem,
    MarketingAnalyticsTableQuery,
} from '~/queries/schema/schema-general'

import { ConversionPeopleRequestApi } from './generated/api.schemas'

function rowValue(record: unknown, column: string): string | undefined {
    if (!Array.isArray(record)) {
        return undefined
    }
    const cell = record.find((item): item is MarketingAnalyticsItem => item?.key === column)
    return cell?.value == null ? undefined : String(cell.value)
}

export function conversionPeopleRequest(
    source: MarketingAnalyticsTableQuery,
    record: unknown,
    goalId: string
): ConversionPeopleRequestApi | null {
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
        source: source as ConversionPeopleRequestApi['source'],
        goal_id: goalId,
        group,
        source_name: needsSource ? sourceName : '',
        campaign_id:
            level === MarketingAnalyticsDrillDownLevel.Campaign && !source.compareFilter?.compare
                ? rowValue(record, 'ID')
                : undefined,
    }
}
