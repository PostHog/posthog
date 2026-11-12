import { useValues } from 'kea'

import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { getExperimentVariants, getVariantColor } from 'scenes/experiments/utils'

import type { HealthDetectableEffect } from './healthCheckRows'
import { formatHealthPercentage } from './healthCheckValues'

/**
 * A line from 0 to the scale's end. The shaded part is smaller than the sample can reliably detect, and the marker is
 * the size of the variant's difference, so a marker outside the shade is a difference the sample can tell from chance.
 * A negative difference sits at its size too, and the legend gives its sign.
 */
export function HealthDetectableEffectLine({ effect }: { effect: HealthDetectableEffect }): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const color = getVariantColor(effect.variant, getExperimentVariants(experiment))
    const zone = Math.min(100, (effect.detectable / effect.scaleMax) * 100)
    const marker = Math.min(100, (Math.abs(effect.difference) / effect.scaleMax) * 100)
    const sign = effect.difference > 0 ? '+' : ''

    return (
        <div
            className="flex max-w-xl flex-col gap-1.5"
            role="img"
            aria-label={`${effect.variant} differs from the control by ${sign}${formatHealthPercentage(effect.difference)}. This sample can reliably detect differences of ${formatHealthPercentage(effect.detectable)} or more.`}
            data-attr="experiment-health-detectable-effect"
        >
            <span className="text-xs font-semibold text-secondary">{effect.variant} against the control</span>
            <div className="relative h-3 rounded-full bg-fill-secondary" aria-hidden="true">
                <span
                    className="absolute inset-y-0 left-0 rounded-l-full bg-fill-warning-secondary"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: `${zone}%` }}
                />
                <span
                    className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface-primary"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ left: `${marker}%`, backgroundColor: color }}
                />
            </div>
            <div className="flex justify-between text-xs text-secondary tabular-nums" aria-hidden="true">
                <span>0%</span>
                <span>{formatHealthPercentage(effect.scaleMax / 2)}</span>
                <span>{formatHealthPercentage(effect.scaleMax)}</span>
            </div>
            <span className="text-center text-xs text-secondary" aria-hidden="true">
                Size of the difference from the control
            </span>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-secondary" aria-hidden="true">
                <span className="flex items-center gap-1.5">
                    <span className="inline-block size-2.5 rounded-sm bg-fill-warning-secondary" />
                    Smaller than this sample can reliably detect
                </span>
                <span className="flex items-center gap-1.5">
                    <span
                        className="inline-block size-2.5 rounded-full"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ backgroundColor: color }}
                    />
                    {`Difference of ${effect.variant}, ${sign}${formatHealthPercentage(effect.difference)}`}
                </span>
            </div>
        </div>
    )
}
