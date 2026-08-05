import clsx from 'clsx'

import { FunnelStepWithConversionMetrics } from '~/types'

import { StepBar } from './StepBar'

interface StepBarsProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
}

export function StepBars({ step, stepIndex }: StepBarsProps): JSX.Element {
    return (
        <div className={clsx('StepBars', stepIndex === 0 && 'StepBars--first')}>
            <div className="StepBars__grid">
                {Array.from({ length: 5 }, (_, i) => (
                    <div
                        key={`gridline-${stepIndex}-${i}`}
                        className="StepBars__gridline StepBars__gridline--horizontal"
                    />
                ))}
            </div>
            {step.nested_breakdown?.map((series, i) => (
                <StepBar key={`bar-${stepIndex}-${i}`} step={series} stepIndex={stepIndex} />
            )) || <StepBar step={step} stepIndex={stepIndex} />}
        </div>
    )
}
