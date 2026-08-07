import './QuotaMeterBar.scss'

import clsx from 'clsx'
import type { ReactNode } from 'react'

export interface QuotaMeterSegment {
    /** Width as a percentage of the cap; may exceed the bar — segments are clamped cumulatively. */
    pct: number
    /** Background class, e.g. `bg-success` / `bg-warning` / `bg-danger` / `bg-accent`. */
    barClass: string
    /** Overlay the animated stripe pattern. */
    striped?: boolean
}

/** Shading for the non-billable slice of spend, so free credits don't read as money spent. */
export const QUOTA_METER_FREE_CLASS = 'QuotaMeterBar__free'

interface QuotaMeterBarProps {
    /** Solid segment: actual usage as a percentage of the cap. */
    usedPct: number
    /** Portion of `usedPct` that was covered by free credits; shaded separately, ahead of the billed remainder. */
    usedFreePct?: number
    /** Striped/solid projection segments, rendered in order after the used segment. */
    projected: QuotaMeterSegment[]
    valueNow: number
    label: string
    size?: 'small' | 'medium'
    className?: string
}

/** Segment widths fill left to right; later segments absorb overflow past 100%. */
export function clampSegmentWidths(pcts: number[]): number[] {
    let headroom = 100
    return pcts.map((pct) => {
        const width = Math.max(Math.min(pct, headroom), 0)
        headroom -= width
        return width
    })
}

/** Widths for `[free, billed, ...projected]`, with the free slice clamped inside the used slice. The bar and its
 * legends both derive widths from this, so a legend chip can never outlive its segment. */
export function quotaMeterWidths(usedPct: number, usedFreePct: number, projectedPcts: number[]): number[] {
    const freePct = Math.max(Math.min(usedFreePct, usedPct), 0)
    return clampSegmentWidths([freePct, usedPct - freePct, ...projectedPcts])
}

/** Quota meter: solid used segment plus projection segments; later segments absorb overflow past 100%. */
export function QuotaMeterBar({
    usedPct,
    usedFreePct = 0,
    projected,
    valueNow,
    label,
    size = 'medium',
    className,
}: QuotaMeterBarProps): JSX.Element {
    const widths = quotaMeterWidths(
        usedPct,
        usedFreePct,
        projected.map((segment) => segment.pct)
    )
    return (
        <div
            className={clsx(
                'flex overflow-hidden bg-fill-tertiary',
                size === 'small' ? 'h-1.5 rounded-full' : 'h-3 rounded',
                className
            )}
            role="meter"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.min(Math.round(valueNow), 100)}
            aria-label={label}
        >
            <div
                className={clsx('transition-[width] duration-500 ease-out', QUOTA_METER_FREE_CLASS)}
                style={{ width: `${widths[0]}%` }}
            />
            <div className="bg-muted transition-[width] duration-500 ease-out" style={{ width: `${widths[1]}%` }} />
            {projected.map(({ barClass, striped }, index) => (
                <div
                    key={index}
                    className={clsx(
                        'transition-[width,background-color] duration-500 ease-out',
                        striped && 'QuotaMeterBar__stripes QuotaMeterBar__stripes--animated',
                        barClass
                    )}
                    style={{ width: `${widths[index + 2]}%` }}
                />
            ))}
        </div>
    )
}

/** Legend entry with a chip matching a bar segment. Renders nothing when its segment has no width. */
export function QuotaMeterLegendItem({
    barClass,
    striped,
    width,
    children,
}: {
    barClass?: string
    striped?: boolean
    /** Clamped width of the matching segment; omit for entries that are always shown. */
    width?: number
    children: ReactNode
}): JSX.Element | null {
    if (width !== undefined && width <= 0) {
        return null
    }
    return (
        <div className="flex items-center gap-1">
            <span
                className={clsx(
                    'inline-block w-2.5 h-2.5 rounded-sm',
                    striped && 'QuotaMeterBar__stripes',
                    barClass ?? 'bg-muted'
                )}
            />
            {children}
        </div>
    )
}
