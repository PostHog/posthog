import type { HeatmapAnalysisVariantApi } from 'products/web_analytics/frontend/generated/api.schemas'

export const HISTORICAL_HEATMAP_RADIUS = 24

export function countHistoricalHeatmapClicks(
    clicks: HeatmapAnalysisVariantApi['clicks'],
    position: { x: number; y: number },
    scale: number
): number {
    if (scale <= 0) {
        return 0
    }
    const x = Math.round(position.x / scale)
    const y = Math.round(position.y / scale)
    return clicks.reduce(
        (count, click) =>
            (click.x - x) ** 2 + (click.y - y) ** 2 <= HISTORICAL_HEATMAP_RADIUS ** 2 ? count + click.count : count,
        0
    )
}
