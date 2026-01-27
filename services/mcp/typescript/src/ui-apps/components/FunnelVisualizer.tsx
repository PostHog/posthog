import type { ReactElement } from 'react'
import type { FunnelVisualizerProps } from './types'
import { normalizeFunnelSteps, formatNumber, formatPercent } from './utils'

const BAR_HEIGHT = 32
const BAR_GAP = 8
const LABEL_WIDTH = 120
const COUNT_WIDTH = 80

export function FunnelVisualizer({ results }: FunnelVisualizerProps): ReactElement {
    const steps = normalizeFunnelSteps(results)

    if (steps.length === 0) {
        return (
            <div
                style={{
                    padding: '2rem',
                    textAlign: 'center',
                    color: 'var(--color-text-secondary, #6b7280)',
                }}
            >
                No funnel data available
            </div>
        )
    }

    const maxCount = Math.max(...steps.map((s) => s.count), 1)
    const firstCount = steps[0]?.count || 1

    return (
        <div style={{ padding: '0.5rem 0' }}>
            {steps.map((step, index) => {
                const widthPercent = (step.count / maxCount) * 100
                const conversionRate = step.count / firstCount

                return (
                    <div
                        key={step.order}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.75rem',
                            marginBottom: index < steps.length - 1 ? `${BAR_GAP}px` : 0,
                        }}
                    >
                        {/* Step label */}
                        <div
                            style={{
                                width: `${LABEL_WIDTH}px`,
                                fontSize: '0.875rem',
                                color: 'var(--color-text-primary, #101828)',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                                flexShrink: 0,
                            }}
                            title={step.name}
                        >
                            {step.name}
                        </div>

                        {/* Bar container */}
                        <div
                            style={{
                                flex: 1,
                                height: `${BAR_HEIGHT}px`,
                                backgroundColor: 'var(--color-background-secondary, #f9fafb)',
                                borderRadius: '4px',
                                overflow: 'hidden',
                                position: 'relative',
                            }}
                        >
                            {/* Filled bar */}
                            <div
                                style={{
                                    height: '100%',
                                    width: `${widthPercent}%`,
                                    backgroundColor:
                                        index === 0
                                            ? 'var(--posthog-chart-1, #1d4ed8)'
                                            : `color-mix(in srgb, var(--posthog-chart-1, #1d4ed8) ${100 - index * 15}%, var(--color-background-secondary, #f9fafb))`,
                                    borderRadius: '4px',
                                    transition: 'width 0.3s ease',
                                }}
                            />

                            {/* Conversion rate inside bar */}
                            <div
                                style={{
                                    position: 'absolute',
                                    left: '8px',
                                    top: '50%',
                                    transform: 'translateY(-50%)',
                                    fontSize: '0.75rem',
                                    fontWeight: 500,
                                    color:
                                        widthPercent > 30
                                            ? 'var(--color-text-inverse, #fff)'
                                            : 'var(--color-text-secondary, #6b7280)',
                                }}
                            >
                                {formatPercent(conversionRate)}
                            </div>
                        </div>

                        {/* Count */}
                        <div
                            style={{
                                width: `${COUNT_WIDTH}px`,
                                textAlign: 'right',
                                fontSize: '0.875rem',
                                fontWeight: 500,
                                color: 'var(--color-text-primary, #101828)',
                                flexShrink: 0,
                            }}
                        >
                            {formatNumber(step.count)}
                        </div>
                    </div>
                )
            })}

            {/* Drop-off summary */}
            {steps.length >= 2 && (
                <div
                    style={{
                        marginTop: '1rem',
                        padding: '0.75rem',
                        backgroundColor: 'var(--color-background-secondary, #f9fafb)',
                        borderRadius: '4px',
                        fontSize: '0.8125rem',
                        color: 'var(--color-text-secondary, #6b7280)',
                    }}
                >
                    <strong>Overall conversion:</strong> {formatPercent((steps[steps.length - 1]?.count ?? 0) / firstCount)} (
                    {formatNumber(steps[steps.length - 1]?.count ?? 0)} of {formatNumber(firstCount)})
                </div>
            )}
        </div>
    )
}
