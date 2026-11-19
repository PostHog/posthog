import { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

/** A previous-period row shows its series color at half opacity, so it reads as the faded twin of the current row. */
export function seriesRowColor(item: IndexedTrendResult, seriesColor: string): string {
    return item.compare && item.compare_label === 'previous' ? `${seriesColor}80` : seriesColor
}
