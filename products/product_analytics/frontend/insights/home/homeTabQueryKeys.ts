import { pageCollectionId } from '~/queries/nodes/DataNode/pageCollections'

import type { HomeTabStatQuery } from './homeTabDefaultTiles'

export function homeTabDataCollectionId(teamId: number | null): string {
    return pageCollectionId(`product-analytics-home.${teamId}`)
}

export function homeTabStatKey(teamId: number | null, metric: string): string {
    return `HomeTabStatTile.${teamId}.${metric}`
}

export function homeTabStatTrendKey(teamId: number | null, stat: HomeTabStatQuery): string {
    return homeTabStatKey(teamId, stat.trendKey ?? (stat.trendQuery ? `${stat.key}.trend` : stat.key))
}

export function homeTabChartInsightId(teamId: number | null, chart: string): `new-${string}` {
    return `new-AdHoc.InsightViz.HomeTab.${teamId}.${chart}`
}
