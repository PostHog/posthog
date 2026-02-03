import type { ReactElement } from 'react'

import { type HorizontalBar, HorizontalBarChart } from './charts'
import type { FunnelVisualizerProps } from './types'
import { formatNumber, formatPercent, normalizeFunnelSteps } from './utils'

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

    const firstCount = steps[0]?.count || 1

    const bars: HorizontalBar[] = steps.map((step) => ({
        label: step.name,
        value: step.count,
        innerText: formatPercent(step.count / firstCount),
    }))

    const funnelColor = (index: number): string => {
        if (index === 0) {
            return 'var(--posthog-chart-1, #1d4ed8)'
        }
        // Fade color for subsequent steps
        return `color-mix(in srgb, var(--posthog-chart-1, #1d4ed8) ${100 - index * 15}%, var(--color-background-secondary, #f9fafb))`
    }

    const lastCount = steps[steps.length - 1]?.count ?? 0

    return (
        <div>
            <HorizontalBarChart bars={bars} color={funnelColor} />

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
                    <strong>Overall conversion:</strong> {formatPercent(lastCount / firstCount)} (
                    {formatNumber(lastCount)} of {formatNumber(firstCount)})
                </div>
            )}
        </div>
    )
}
