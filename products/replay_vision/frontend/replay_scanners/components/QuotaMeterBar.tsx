import './QuotaMeterBar.scss'

import clsx from 'clsx'
import type { ReactNode } from 'react'

import type { QuotaMeterModel } from '../../utils/quotaContributions'

export interface QuotaMeterSegment {
    /** Width as a percentage of the cap; may exceed it — the bar rescales to the total instead of truncating. */
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
    /** Caption under the limit marker. Always shown, so the limit reads the same whether or not it is exceeded. */
    limitLabel?: string
    className?: string
}

/** What the bar's full width represents: the limit, or the whole total once the segments overshoot it. */
export function meterScale(pcts: number[]): number {
    return Math.max(
        pcts.reduce((total, pct) => total + Math.max(pct, 0), 0),
        100
    )
}

/**
 * Segment widths as a percentage of the rendered bar.
 *
 * Past the limit the bar rescales to the total rather than truncating. Clamping made whichever segment came last
 * vanish exactly when it mattered most: a small amount of headroom left under the limit would swallow a large
 * segment whole, and the user could not see the size of what they were about to commit to.
 */
export function fitSegmentWidths(pcts: number[]): number[] {
    const scale = 100 / meterScale(pcts)
    return pcts.map((pct) => Math.max(pct, 0) * scale)
}

/**
 * Layout for `[free, billed, ...projected]`, with the free slice clamped inside the used slice.
 *
 * The bar, its legends and the limit marker all read one object, so the segment composition lives in a single
 * place: a legend chip can never outlive its segment, and the marker can never disagree with the widths.
 */
export function quotaMeterLayout(
    usedPct: number,
    usedFreePct: number,
    projectedPcts: number[]
): { widths: number[]; limitMarkerPct: number } {
    const freePct = Math.max(Math.min(usedFreePct, usedPct), 0)
    const pcts = [freePct, usedPct - freePct, ...projectedPcts]
    return { widths: fitSegmentWidths(pcts), limitMarkerPct: 10000 / meterScale(pcts) }
}

/** Widths alone, for callers that only size legend chips. */
export function quotaMeterWidths(usedPct: number, usedFreePct: number, projectedPcts: number[]): number[] {
    return quotaMeterLayout(usedPct, usedFreePct, projectedPcts).widths
}

/** Quota meter: solid used segment plus projection segments, rescaled with a limit marker when they overshoot. */
export function QuotaMeterBar({
    usedPct,
    usedFreePct = 0,
    projected,
    valueNow,
    label,
    size = 'medium',
    limitLabel = 'Spend limit',
    className,
}: QuotaMeterBarProps): JSX.Element {
    const { widths, limitMarkerPct } = quotaMeterLayout(
        usedPct,
        usedFreePct,
        projected.map((segment) => segment.pct)
    )
    const overshoots = limitMarkerPct < 100
    // Keep the caption inside the card when the marker sits near either end, instead of centering it off the edge.
    const captionAnchor = limitMarkerPct > 85 ? 'translateX(-100%)' : limitMarkerPct < 15 ? 'none' : 'translateX(-50%)'
    return (
        <div className={className}>
            <div className="relative">
                <div
                    className={clsx(
                        'flex overflow-hidden bg-fill-tertiary',
                        size === 'small' ? 'h-1.5 rounded-full' : 'h-3 rounded'
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
                    <div
                        className="bg-muted transition-[width] duration-500 ease-out"
                        style={{ width: `${widths[1]}%` }}
                    />
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
                <div
                    className={clsx(
                        'absolute w-0.5 rounded-full bg-text-3000 transition-[left] duration-500 ease-out',
                        size === 'small' ? '-top-1 h-3.5' : '-top-1 h-5'
                    )}
                    // At the limit the marker sits on the bar's own end, so pull it back inside rather than
                    // letting it hang half off the edge.
                    style={{ left: `${limitMarkerPct}%`, transform: overshoots ? undefined : 'translateX(-100%)' }}
                />
            </div>
            {limitLabel && (
                // Its own row in normal flow, so the caption can never land on whatever the parent renders next.
                <div className="relative mt-1 h-4">
                    <span
                        className="absolute whitespace-nowrap text-[11px] font-medium text-secondary transition-[left] duration-500 ease-out"
                        style={{ left: `${limitMarkerPct}%`, transform: captionAnchor }}
                    >
                        {limitLabel}
                    </span>
                </div>
            )}
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
    /** Rendered width of the matching segment; omit for entries that are always shown. */
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

/**
 * Bar and legend for a `QuotaMeterModel`, together.
 *
 * The pairing is the point: widths are computed once and drive both, so a legend chip cannot label a
 * segment the bar didn't draw. Assembling them per card meant three copies and two width computations.
 */
export function QuotaMeter({
    model,
    label,
    size,
    className,
}: {
    model: QuotaMeterModel
    label: string
    size?: 'small' | 'medium'
    className?: string
}): JSX.Element {
    const { projection, segments, periodEndPct } = model
    const [freeWidth, billedWidth, ...segmentWidths] = quotaMeterWidths(
        projection.usedPct,
        projection.usedFreePct,
        segments.map((segment) => segment.pct)
    )
    return (
        <>
            <QuotaMeterBar
                className={className}
                size={size}
                usedPct={projection.usedPct}
                usedFreePct={projection.usedFreePct}
                projected={segments}
                valueNow={periodEndPct}
                label={label}
            />
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                <QuotaMeterLegendItem barClass={QUOTA_METER_FREE_CLASS} width={freeWidth}>
                    Free
                </QuotaMeterLegendItem>
                <QuotaMeterLegendItem width={billedWidth}>{freeWidth > 0 ? 'Billed' : 'Spent'}</QuotaMeterLegendItem>
                {segments.map((segment, index) => (
                    <QuotaMeterLegendItem
                        key={segment.key}
                        barClass={segment.barClass}
                        striped={segment.striped}
                        width={segmentWidths[index]}
                    >
                        {segment.label}
                    </QuotaMeterLegendItem>
                ))}
            </div>
        </>
    )
}
