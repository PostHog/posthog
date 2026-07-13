import { ReactNode } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

/**
 * Compact horizontal bar with a fill and an optional tick marker (e.g. median duration as the fill, p95
 * as the tick). Tick triangle and fill width are inline styles because they're data-driven.
 */
export function RangeBar({
    fraction,
    tickFraction,
    fillColor = 'var(--brand-blue)',
    tickColor = 'var(--muted)',
    className,
    tooltip,
}: {
    /** 0–1 — how far the bar fills. */
    fraction: number
    /** 0–1 — optional marker (a small triangle above the bar); omit for a plain fill. */
    tickFraction?: number | null
    fillColor?: string
    tickColor?: string
    className?: string
    tooltip?: ReactNode
}): JSX.Element {
    const fill = Math.max(0, Math.min(100, fraction * 100))
    const tick = tickFraction == null ? null : Math.max(0, Math.min(100, tickFraction * 100))
    const bar = (
        <span className={cn('relative inline-block', className)}>
            <span className="block h-1.5 overflow-hidden rounded-full bg-border-light">
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <span className="block h-full rounded-full" style={{ width: `${fill}%`, backgroundColor: fillColor }} />
            </span>
            {tick != null && (
                <span
                    className="absolute"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        left: `${tick}%`,
                        top: -4,
                        marginLeft: -3,
                        width: 0,
                        height: 0,
                        borderLeft: '3px solid transparent',
                        borderRight: '3px solid transparent',
                        borderTop: `4px solid ${tickColor}`,
                    }}
                />
            )}
        </span>
    )
    return tooltip ? <Tooltip title={tooltip}>{bar}</Tooltip> : bar
}
