import { ReactNode } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

function fillClassName(muted: boolean, hasSegments: boolean): string {
    if (hasSegments) {
        return muted ? 'opacity-50' : ''
    }
    return muted ? 'bg-[var(--muted)]' : 'bg-[var(--data-color-1)]'
}

export function ComparisonBarRow({
    label,
    labelTooltip,
    value,
    max,
    formatValue,
    muted = false,
    marker,
    children,
}: {
    label: string
    /** Shown on hover over the label, e.g. the full name a narrow label truncates. */
    labelTooltip?: string
    value: number
    /** The largest figure on the card's shared scale. Omit it for a bar that fills the track, e.g. a share split. */
    max?: number
    formatValue: (value: number) => string
    /** The baseline row (previous window, repo), drawn quieter than the row it is compared with. */
    muted?: boolean
    /** A companion figure pinned as a tick on the same scale, named in its tooltip (e.g. "90th percentile"). */
    marker?: { value: number; label: string } | null
    /** Segments that fill the bar instead of one color, e.g. a pass/fail or before/after split. */
    children?: ReactNode
}): JSX.Element {
    const fraction = max == null ? 1 : max > 0 ? value / max : 0
    return (
        <div className="flex items-center gap-2">
            <Tooltip title={labelTooltip}>
                <span className="w-24 shrink-0 truncate text-[11px] text-tertiary">{label}</span>
            </Tooltip>
            <div className="relative h-2.5 flex-1">
                <div
                    className={cn('h-full overflow-hidden rounded-sm', fillClassName(muted, children != null))}
                    style={{ width: `${Math.max(fraction * 100, 2)}%` }}
                >
                    {children}
                </div>
                {marker && max != null && max > 0 && (
                    <Tooltip title={`${marker.label} ${formatValue(marker.value)}`}>
                        <div
                            className="absolute -top-0.5 h-3.5 w-0.5 -translate-x-1/2 rounded-sm bg-[var(--text-3000)]"
                            style={{ left: `${(marker.value / max) * 100}%` }}
                        />
                    </Tooltip>
                )}
            </div>
            <span className="w-14 shrink-0 text-right text-xs font-medium tabular-nums">{formatValue(value)}</span>
        </div>
    )
}
