// Every comparison card draws its bars with this row, so a comparison reads the same on every page.

import { ReactNode } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export interface ComparisonBarMarker {
    fraction: number
    tooltip?: string
}

function fillClassName(muted: boolean, hasSegments: boolean): string {
    if (hasSegments) {
        return muted ? 'opacity-50' : ''
    }
    return muted ? 'bg-[var(--muted)]' : 'bg-[var(--data-color-1)]'
}

export function ComparisonBarRow({
    label,
    value,
    fraction,
    muted = false,
    marker,
    children,
}: {
    label: string
    value: string
    /** Bar length as a share of the track, 0–1. */
    fraction: number
    /** The baseline row (previous window, repo), drawn quieter than the row it is compared with. */
    muted?: boolean
    marker?: ComparisonBarMarker | null
    /** Segments that fill the bar instead of one color, e.g. a pass/fail or before/after split. */
    children?: ReactNode
}): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <span className="w-24 shrink-0 truncate text-[11px] text-tertiary">{label}</span>
            <div className="relative h-2.5 flex-1">
                <div
                    className={cn('h-full overflow-hidden rounded-sm', fillClassName(muted, children != null))}
                    style={{ width: `${Math.max(fraction * 100, 2)}%` }}
                >
                    {children}
                </div>
                {marker && (
                    <Tooltip title={marker.tooltip}>
                        <div
                            className="absolute -top-0.5 h-3.5 w-0.5 -translate-x-1/2 rounded-sm bg-[var(--text-3000)]"
                            style={{ left: `${marker.fraction * 100}%` }}
                        />
                    </Tooltip>
                )}
            </div>
            <span className="w-14 shrink-0 text-right text-xs font-medium tabular-nums">{value}</span>
        </div>
    )
}
