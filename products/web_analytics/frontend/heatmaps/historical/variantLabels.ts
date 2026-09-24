import { dayjs } from 'lib/dayjs'
import { formatDateRange } from 'lib/utils/datetime'
import { pluralize } from 'lib/utils/strings'

import type { HeatmapAnalysisVariantApi } from 'products/web_analytics/frontend/generated/api.schemas'

export function variantClickCount(variant: HeatmapAnalysisVariantApi): number {
    return variant.clicks.reduce((sum, click) => sum + click.count, 0)
}

export function variantStatsLabel(variant: HeatmapAnalysisVariantApi): string {
    return `${variant.visits.toLocaleString()} recorded ${pluralize(variant.visits, 'visit', undefined, false)} · ${variantClickCount(variant).toLocaleString()} clicks`
}

export function variantDateRange(variant: HeatmapAnalysisVariantApi, timezone: string): string {
    return formatDateRange(dayjs(variant.first_seen).tz(timezone), dayjs(variant.last_seen).tz(timezone))
}
