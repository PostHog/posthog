import type { ReactElement } from 'react'

import { buildYTickFormatter, type YFormatterConfig } from '@posthog/quill-charts'

import { formatNumber } from '../utils'

// TODO(quill): replace with a Quill primitive (e.g. `BigNumber` /
// `Stat` / `Metric`) once Quill ships one. The current "large value +
// optional label" shape is a common stat-card pattern that Quill doesn't
// cover yet — Quill ships content primitives (Card, Item, Field) but no
// metric-emphasis component.

export interface BigNumberProps {
    value: number
    label?: string | undefined
    /** Unit settings from the insight (percentage, prefix, decimal places, …). Compact number when omitted. */
    format?: YFormatterConfig | undefined
}

export function BigNumber({ value, label, format }: BigNumberProps): ReactElement {
    const formatted = format ? buildYTickFormatter(format)(value) : formatNumber(value)

    return (
        <div style={{ textAlign: 'center', padding: '2rem' }}>
            <div
                style={{
                    fontSize: '3rem',
                    fontWeight: 'bold',
                    color: 'var(--color-text-primary, #101828)',
                }}
            >
                {formatted}
            </div>
            {label && (
                <div
                    style={{
                        fontSize: '0.875rem',
                        color: 'var(--color-text-secondary, #6b7280)',
                        marginTop: '0.5rem',
                    }}
                >
                    {label}
                </div>
            )}
        </div>
    )
}
