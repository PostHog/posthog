import { signedPercent } from '../../../../utils/goal/format'
import { outcomeTone } from '../../../../utils/goal/status'

const AXIS_STEPS = [0.05, 0.1, 0.2, 0.25, 0.5, 1, 2]

function axisBounds(low: number, high: number): { min: number; max: number } {
    const fit = (step: number): { min: number; max: number; ticks: number } => {
        const min = Math.min(-step, Math.floor(Math.min(0, low) / step - 1e-9) * step)
        const max = Math.max(step, Math.ceil(Math.max(0, high) / step - 1e-9) * step)
        return { min, max, ticks: Math.round((max - min) / step) + 1 }
    }
    return AXIS_STEPS.map(fit).find((axis) => axis.ticks <= 6) ?? fit(AXIS_STEPS[AXIS_STEPS.length - 1] * 2)
}

export function GoalEffectBar({
    low,
    high,
    outcome,
    metric,
    early = false,
}: {
    low: number
    high: number
    outcome: string
    metric: string
    early?: boolean
}): JSX.Element {
    const axis = axisBounds(low, high)
    const at = (value: number): number => ((value - axis.min) / (axis.max - axis.min)) * 100
    const tone = outcomeTone(outcome)
    const anchor = (position: number): string =>
        position < 8 ? 'translate-x-0' : position > 92 ? '-translate-x-full' : '-translate-x-1/2'
    return (
        <figure className="m-0 flex w-full max-w-sm min-w-0 flex-col gap-1">
            <div className="relative h-4 text-xs font-semibold tabular-nums" aria-hidden>
                <span className={`absolute ${anchor(at(low))} ${tone.text}`} style={{ left: `${at(low)}%` }}>
                    {signedPercent(low)}
                </span>
                <span className={`absolute ${anchor(at(high))} ${tone.text}`} style={{ left: `${at(high)}%` }}>
                    {signedPercent(high)}
                </span>
            </div>
            <div className="relative h-3" aria-hidden>
                <div className="absolute inset-x-0 top-1/2 h-px bg-border-primary" />
                <div className="absolute inset-y-0 w-px bg-border-primary" style={{ left: `${at(0)}%` }} />
                <div
                    className={`absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full ${tone.bar}`}
                    style={{ left: `${at(low)}%`, width: `${Math.max(at(high) - at(low), 1)}%` }}
                />
            </div>
            <div className="relative h-4 text-xs text-tertiary" aria-hidden>
                <span className={`absolute whitespace-nowrap ${anchor(at(0))}`} style={{ left: `${at(0)}%` }}>
                    No change
                </span>
            </div>
            <figcaption className="text-xs text-secondary">
                {early
                    ? 'Early result, test against control. It can still change.'
                    : `Change in ${metric.charAt(0).toLowerCase() + metric.slice(1)}, test against control`}
            </figcaption>
        </figure>
    )
}
