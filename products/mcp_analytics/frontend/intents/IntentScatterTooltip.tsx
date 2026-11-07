import { TooltipFooter, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
import type { ScatterPointDatum } from '@posthog/quill-charts'

import { formatNumber } from '../dashboard/formatters'
import type { IntentScatterMeta } from './intentScatter'

export function IntentScatterTooltip({ point }: { point: ScatterPointDatum<IntentScatterMeta> }): JSX.Element {
    const meta = point.meta
    if (!meta) {
        return <TooltipSurface>{point.seriesLabel}</TooltipSurface>
    }
    if (meta.kind === 'topic') {
        return (
            <TooltipSurface>
                <div className="flex items-center gap-2 min-w-0 font-semibold">
                    <TooltipSwatch color={point.color} />
                    <span className="truncate">{meta.label}</span>
                </div>
                <div className="opacity-60">
                    {formatNumber(meta.calls)} calls · {meta.sharePct?.toFixed(1)}% of calls with an intent
                </div>
                <TooltipFooter>click to see the intents inside</TooltipFooter>
            </TooltipSurface>
        )
    }
    return (
        <TooltipSurface>
            <div className="flex items-center gap-2 min-w-0 font-semibold">
                <TooltipSwatch color={point.color} />
                <span className="truncate">{meta.isOutlier ? 'Outlier' : point.seriesLabel}</span>
            </div>
            <div className="max-w-xs whitespace-normal break-words">{meta.label}</div>
            <div className="opacity-60">
                {formatNumber(meta.calls)} calls{meta.tool ? ` · ${meta.tool}` : ''}
            </div>
        </TooltipSurface>
    )
}
