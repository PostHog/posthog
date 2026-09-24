import { LemonCard } from '@posthog/lemon-ui'

import type { HeatmapAnalysisVariantApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { HistoricalHeatmapImage } from './HistoricalHeatmapImage'
import { variantClickCount, variantDateRange, variantStatsLabel } from './variantLabels'

export function HistoricalHeatmapVariant({
    variant,
    timezone,
    index,
    backgroundUrl,
    onSelect,
}: {
    variant: HeatmapAnalysisVariantApi
    timezone: string
    index: number
    backgroundUrl: string
    onSelect: () => void
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="p-0 overflow-hidden">
            <button
                type="button"
                className="group/variant block w-full text-left cursor-pointer hover:bg-surface-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:-outline-offset-2"
                onClick={onSelect}
                aria-label={`Open variant ${index + 1} heatmap, ${variantClickCount(variant).toLocaleString()} clicks`}
                data-attr="historical-heatmap-variant"
            >
                <div className="aspect-[4/3] overflow-hidden border-b bg-surface-secondary" aria-hidden>
                    <HistoricalHeatmapImage
                        key={backgroundUrl}
                        variant={variant}
                        backgroundUrl={backgroundUrl}
                        overlayClassName="opacity-0 group-hover/variant:opacity-100 group-focus-visible/variant:opacity-100 motion-safe:transition-opacity motion-safe:duration-150"
                    />
                </div>
                <div className="p-3 flex flex-col gap-1">
                    <div className="flex flex-wrap justify-between items-center gap-1">
                        <span className="font-semibold">{`Variant ${index + 1}`}</span>
                        <span className="text-xs text-muted">{variantDateRange(variant, timezone)}</span>
                    </div>
                    <span className="text-sm text-muted">{variantStatsLabel(variant)}</span>
                </div>
            </button>
        </LemonCard>
    )
}
