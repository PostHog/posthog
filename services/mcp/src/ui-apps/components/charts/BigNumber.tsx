import type { ReactElement } from 'react'

import { formatNumber } from '../utils'

// TODO(quill): replace with a Quill primitive (e.g. `BigNumber` /
// `Stat` / `Metric`) once Quill ships one. The current "large value +
// optional label" shape is a common stat-card pattern that Quill doesn't
// cover yet — Quill ships content primitives (Card, Item, Field) but no
// metric-emphasis component.

export interface BigNumberProps {
    value: number
    label?: string | undefined
}

export function BigNumber({ value, label }: BigNumberProps): ReactElement {
    return (
        <div style={{ textAlign: 'center', padding: '2rem' }}>
            <div
                style={{
                    fontSize: '3rem',
                    fontWeight: 'bold',
                    color: 'var(--color-text-primary, #101828)',
                }}
            >
                {formatNumber(value)}
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
