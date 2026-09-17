import { type ReactNode } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import { formatPercentage } from 'lib/utils/numbers'

import { formatNumber } from './formatters'

export interface ShareBarLabel {
    key: string
    label: string
    icon?: ReactNode
    value: number
}

export function ShareBarLabels({ rows, totalCalls }: { rows: ShareBarLabel[]; totalCalls: number }): JSX.Element {
    const { scales } = useChartLayout()
    return (
        <>
            {rows.map((row) => (
                <div
                    key={row.key}
                    className="absolute left-0 right-0 flex items-center justify-between gap-2 text-xs"
                    style={{ top: (scales.x(row.key) ?? 0) - 26 }}
                >
                    <span className="flex min-w-0 items-center gap-1.5" title={row.label}>
                        {row.icon}
                        <span className="truncate">{row.label}</span>
                    </span>
                    <span className="shrink-0 text-secondary tabular-nums">
                        {formatPercentage(totalCalls > 0 ? (row.value / totalCalls) * 100 : 0, { compact: true })} ·{' '}
                        {formatNumber(row.value)} {row.value === 1 ? 'call' : 'calls'}
                    </span>
                </div>
            ))}
        </>
    )
}
