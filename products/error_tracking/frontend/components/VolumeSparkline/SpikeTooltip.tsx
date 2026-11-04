import { TooltipFooter, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'

import { resolveVariableColor } from 'lib/charts/utils/color'

import { formatCompactVolumeHoverDate, formatCompactVolumeHoverOccurrences } from './formatCompactVolumeHover'
import type { SparklineDatum } from './types'

export type SpikeTooltipProps = {
    datum: SparklineDatum
    clickable: boolean
}

export function SpikeTooltip({ datum, clickable }: SpikeTooltipProps): JSX.Element {
    const swatchColor = resolveVariableColor(datum.color)
    return (
        <TooltipSurface data-attr="error-tracking-volume-spike-tooltip">
            <div className="flex items-center justify-between gap-4">
                <span className="flex items-center gap-1.5 font-semibold">
                    {swatchColor && <TooltipSwatch color={swatchColor} />}
                    <span>Spike detected</span>
                </span>
                <span className="opacity-60">
                    <span>{formatCompactVolumeHoverDate(datum)}</span> (UTC)
                </span>
            </div>
            <div className="tabular-nums">{formatCompactVolumeHoverOccurrences(datum)}</div>
            {datum.spikeMultiplier !== undefined && (
                <div className="tabular-nums">
                    <span>{datum.spikeMultiplier.toFixed(1)}x</span> this issue's baseline
                </div>
            )}
            {clickable && <TooltipFooter>Click to see spike details</TooltipFooter>}
        </TooltipSurface>
    )
}
