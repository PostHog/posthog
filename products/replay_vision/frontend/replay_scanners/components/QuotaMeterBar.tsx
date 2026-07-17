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

interface QuotaMeterBarProps {
    /** Solid segment: actual usage as a percentage of the cap. */
    usedPct: number
    /** Striped/solid projection segments, rendered in order after the used segment. */
    projected: QuotaMeterSegment[]
    valueNow: number
    label: string
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

/** Quota meter: solid used segment plus projection segments; later segments absorb overflow past 100%. */
export function QuotaMeterBar({ usedPct, projected, valueNow, label, className }: QuotaMeterBarProps): JSX.Element {
    const widths = clampSegmentWidths([usedPct, ...projected.map((segment) => segment.pct)])
    return (
        <div
            className={clsx('flex h-3 rounded overflow-hidden bg-fill-tertiary', className)}
            role="meter"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.min(Math.round(valueNow), 100)}
            aria-label={label}
        >
            <div className="bg-muted transition-[width] duration-500 ease-out" style={{ width: `${widths[0]}%` }} />
            {projected.map(({ barClass, striped }, index) => (
                <div
                    key={index}
                    className={clsx(
                        'transition-[width,background-color] duration-500 ease-out',
                        striped && 'QuotaMeterBar__stripes QuotaMeterBar__stripes--animated',
                        barClass
                    )}
                    style={{ width: `${widths[index + 1]}%` }}
                />
            ))}
        </div>
    )
}

/** Legend entry with a chip matching a bar segment. */
export function QuotaMeterLegendItem({
    barClass,
    striped,
    children,
}: {
    barClass?: string
    striped?: boolean
    children: ReactNode
}): JSX.Element {
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
